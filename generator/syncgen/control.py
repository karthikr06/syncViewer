"""In-memory power-action log for demo VMs (forgotten when the generator restarts)."""
import dataclasses
import threading

from syncgen.engine import Vm

ACTIONS = ("start", "stop", "restart", "deallocate")
OFF = ("stopped", "deallocated")

# (account_ref, vm_id) -> [(epoch, power_state, healed)], oldest first
_events: dict[tuple[str, str], list[tuple[int, str, bool]]] = {}
_lock = threading.Lock()


class ActionError(ValueError):
    pass


def reset() -> None:
    with _lock:
        _events.clear()


def _last(account_ref: str, vm: Vm, epoch: int | None = None):
    events = _events.get((account_ref, vm.id), [])
    if epoch is not None:
        events = [e for e in events if e[0] <= epoch]
    return events[-1] if events else None


def has_events(account_ref: str, vm: Vm) -> bool:
    return (account_ref, vm.id) in _events


def power_state(account_ref: str, vm: Vm, epoch: int | None = None) -> str:
    last = _last(account_ref, vm, epoch)
    return last[1] if last else vm.power_state


def behaviour_at(account_ref: str, vm: Vm, epoch: int) -> Vm | None:
    """The VM at `epoch`: None while off; a healthy normal VM after a start or restart."""
    last = _last(account_ref, vm, epoch)
    if last is None:
        return None if vm.role == "stopped" else vm
    _, state, healed = last
    if state in OFF:
        return None
    if healed and vm.role in ("stopped", "unresponsive"):
        return dataclasses.replace(vm, role="normal", power_state="running")
    return vm


def apply(account_ref: str, vm: Vm, action: str, epoch: int) -> tuple[str, str]:
    """Perform an action; returns (from_state, to_state). Raises ActionError if not allowed."""
    if action not in ACTIONS:
        raise ActionError(f"unknown action {action!r}")
    with _lock:
        current = power_state(account_ref, vm)
        if action == "start":
            if current not in OFF:
                raise ActionError(f"cannot start a VM that is {current}")
            new = ("running", True)
        elif action == "stop":
            if current != "running":
                raise ActionError(f"cannot stop a VM that is {current}")
            new = ("stopped", False)
        elif action == "deallocate":
            if current == "deallocated":
                raise ActionError("the VM is already deallocated")
            new = ("deallocated", False)
        else:  # restart
            if current != "running":
                raise ActionError(f"cannot restart a VM that is {current}")
            new = ("running", True)
        _events.setdefault((account_ref, vm.id), []).append((epoch, new[0], new[1]))
        return current, new[0]
