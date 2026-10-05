from fastapi import FastAPI

from app.core.config import load_settings_or_exit

settings = load_settings_or_exit(["DATABASE_URL"])

app = FastAPI(
    title="SyncViewer API",
    docs_url=None if settings.is_production else "/docs",
    openapi_url=None if settings.is_production else "/openapi.json",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
