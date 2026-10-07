"""Runs a chat turn through the ADK coordinator, scoped to the authenticated user."""
import asyncio
import logging
import threading
import time
import uuid

from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings
from app.models import AgentRun
from app.schemas.requests import ChatResponse

log = logging.getLogger("agent")
APP_NAME = "syncviewer"
NOT_CONFIGURED = ("The AI assistant is not configured on this server (no GOOGLE_API_KEY). "
                  "Digests and rule-based recommendations still work.")
FAILED = "Sorry, the assistant ran into a problem. Please try again in a moment."
BUSY = "The AI assistant is busy or rate-limited right now. Please try again in a minute."
TIMEOUT_SECONDS = 120

_lock = threading.Lock()
_state: dict = {}


def _loop() -> asyncio.AbstractEventLoop:
    """One long-lived event loop in a daemon thread. ADK/genai keep async HTTP clients bound to
    the loop that created them, so a fresh `asyncio.run` per request would break the second call."""
    with _lock:
        loop = _state.get("loop")
        if loop is None or loop.is_closed():
            loop = asyncio.new_event_loop()
            threading.Thread(target=loop.run_forever, name="adk-loop", daemon=True).start()
            _state["loop"] = loop
        return loop


def _runtime(session_factory: sessionmaker[Session], settings: Settings):
    """Build the ADK pieces once per process (agents and in-memory sessions are reusable)."""
    with _lock:
        if "runner" not in _state:
            from google.adk.runners import Runner
            from google.adk.sessions import InMemorySessionService

            from app.agent.agents import build_agents
            from app.agent.tools import adk_tools

            adk_tools.configure(session_factory)
            service = InMemorySessionService()
            _state["service"] = service
            _state["runner"] = Runner(app_name=APP_NAME, agent=build_agents(settings.gemini_model),
                                      session_service=service)
        return _state["service"], _state["runner"]


async def _chat(service, runner, owner: str, role: str, session_id: str, message: str):
    from google.genai import types

    session = await service.get_session(app_name=APP_NAME, user_id=owner, session_id=session_id)
    if session is None:
        # owner_id and role come from the authenticated request, never from model output
        await service.create_session(app_name=APP_NAME, user_id=owner, session_id=session_id,
                                     state={"owner_id": owner, "role": role})
    content = types.Content(role="user", parts=[types.Part(text=message)])
    reply, tools, tokens_in, tokens_out = [], [], 0, 0
    async for event in runner.run_async(user_id=owner, session_id=session_id, new_message=content):
        for call in event.get_function_calls() or []:
            tools.append(call.name)
        if event.usage_metadata:
            tokens_in += event.usage_metadata.prompt_token_count or 0
            tokens_out += event.usage_metadata.candidates_token_count or 0
        if event.is_final_response() and event.content and event.content.parts:
            reply.append("".join(p.text or "" for p in event.content.parts))
    return "\n".join(r for r in reply if r).strip(), tools, tokens_in, tokens_out


def _log_run(factory: sessionmaker[Session], owner: uuid.UUID, model: str, tools: list[str],
             tin: int, tout: int, started: float, status: str) -> None:
    try:
        with factory() as s:
            s.add(AgentRun(owner_id=owner, trigger="chat", tools_called=tools, model=model,
                           input_tokens=tin, output_tokens=tout,
                           duration_ms=int((time.monotonic() - started) * 1000), status=status))
            s.commit()
    except Exception:  # noqa: BLE001 - logging must never break the answer
        log.exception("could not record agent run")


def _is_quota_error(exc: BaseException) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(s in text for s in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))


def run_chat(session_factory: sessionmaker[Session], settings: Settings, owner_id: uuid.UUID,
             message: str, session_id: str | None, role: str = "user") -> ChatResponse:
    sid = session_id or uuid.uuid4().hex
    if not settings.google_api_key:
        return ChatResponse(reply=NOT_CONFIGURED, session_id=sid, configured=False)
    started = time.monotonic()
    try:
        service, runner = _runtime(session_factory, settings)
        future = asyncio.run_coroutine_threadsafe(
            _chat(service, runner, str(owner_id), role, sid, message), _loop())
        try:
            text, tools, tin, tout = future.result(timeout=TIMEOUT_SECONDS)
        except TimeoutError:
            future.cancel()
            raise
    except Exception as exc:  # noqa: BLE001
        log.exception("agent run failed")
        _log_run(session_factory, owner_id, settings.gemini_model, [], 0, 0, started, "error")
        return ChatResponse(reply=BUSY if _is_quota_error(exc) else FAILED, session_id=sid,
                            configured=True)
    _log_run(session_factory, owner_id, settings.gemini_model, tools, tin, tout, started, "ok")
    return ChatResponse(reply=text or FAILED, session_id=sid, configured=True, tools_called=tools)
