"""Deterministic fake-cloud engine.

Everything here is a pure function of (account_ref, scenario, resource index, timestamp).
No clocks, no global state: the same query always returns the same answer, so any window
can be backfilled and tests can compare against ground truth.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

GRID = 300  # seconds; outages are aligned to this grid
DAY = 86400
SCENARIOS = {"small": 5, "medium": 25, "large": 300}
METRICS = {
    "availability": "bool",
    "cpu_percent": "percent",
    "memory_percent": "percent",
    "disk_used_percent": "percent",
    "network_in_bytes": "bytes",
    "network_out_bytes": "bytes",
}
REGIONS = ["eastus", "westeurope", "southeastasia", "centralindia"]
KINDS = ["web", "api", "db", "batch", "cache"]
MASK = (1 << 64) - 1


def mix(x: int) -> int:
    """splitmix64 finalizer: cheap, well-distributed, deterministic."""
    x = (x + 0x9E3779B97F4A7C15) & MASK
    x = ((x ^ (x >> 30)) * 0xBF58476D1CE4E5B9) & MASK
    x = ((x ^ (x >> 27)) * 0x94D049BB133111EB) & MASK
    return x ^ (x >> 31)


def unit(x: int) -> float:
    """Hash -> float in [0, 1)."""
    return (mix(x) >> 11) / float(1 << 53)


def role_for(index: int) -> str:
    fixed = ["leak", "disk", "idle", "unresponsive", "stopped", "idle", "flaky"]
    if index < len(fixed):
        return fixed[index]
    if index % 10 == 3:
        return "idle"
    if index % 10 == 5:
        return "flaky"
    if index % 50 == 9:
        return "leak"
    if index % 50 == 19:
        return "disk"
    return "normal"


@dataclass(frozen=True)
class Vm:
    index: int
    seed: int
    id: str
    name: str
    role: str
    region: str
    size_sku: str
    power_state: str
    tags: dict[str, str]
    # recurring-fault parameters (fixed per VM)
    flaky_hour: int
    leak_period: int
    leak_phase: int
    disk_period: int
    disk_phase: int
    cpu_peak_hour: float


def make_vm(account_ref: str, index: int) -> Vm:
    seed = int.from_bytes(hashlib.sha256(f"{account_ref}:{index}".encode()).digest()[:8], "big")
    role = role_for(index)
    kind = KINDS[int(unit(seed ^ 1) * len(KINDS))]
    return Vm(
        index=index,
        seed=seed,
        id=f"vm-{seed & 0xFFFFFFFF:08x}",
        name=f"{kind}-{index:03d}",
        role=role,
        region=REGIONS[int(unit(seed ^ 2) * len(REGIONS))],
        size_sku="Standard_D8s_v5" if role == "idle" else
        ("Standard_D2s_v5" if unit(seed ^ 3) < 0.6 else "Standard_D4s_v5"),
        power_state="stopped" if role == "stopped" else "running",
        tags={"env": "prod" if unit(seed ^ 4) < 0.5 else "dev",
              "team": ["platform", "data", "web"][int(unit(seed ^ 5) * 3)]},
        flaky_hour=int(unit(seed ^ 6) * 24),
        leak_period=3 * DAY,
        leak_phase=int(unit(seed ^ 7) * 3 * DAY),
        disk_period=10 * DAY,
        disk_phase=int(unit(seed ^ 8) * 10 * DAY),
        cpu_peak_hour=10 + unit(seed ^ 9) * 8,
    )


def inventory(account_ref: str, scenario: str) -> list[Vm]:
    return [make_vm(account_ref, i) for i in range(SCENARIOS[scenario])]


def _day_index(epoch: int) -> int:
    return epoch // DAY


def outage_for_day(vm: Vm, day: int) -> tuple[int, int, str] | None:
    """(start_epoch, end_epoch, kind) of the VM's outage on a UTC day, or None. Never spans days."""
    if vm.role in ("stopped", "unresponsive"):
        return None
    base = day * DAY
    if vm.role == "flaky":  # same hour every day -> recurring pattern
        start = base + vm.flaky_hour * 3600
        return start, start + 900, "outage"
    h = (vm.seed ^ (day * 0x9E3779B1)) & MASK
    if unit(h) >= 0.3:  # ~30% of days have an outage
        return None
    start = base + int(unit(h ^ 0xA1) * (DAY - 3600) // GRID) * GRID
    duration = (2 + int(unit(h ^ 0xB2) * 9)) * GRID  # 10..50 min
    return start, start + duration, "outage"


def is_available(vm: Vm, epoch: int) -> bool:
    if vm.role == "unresponsive":
        return False
    out = outage_for_day(vm, _day_index(epoch))
    return not (out and out[0] <= epoch < out[1])


def _noise(vm: Vm, salt: int, epoch: int, amp: float) -> float:
    return (unit(vm.seed ^ (salt << 40) ^ (epoch // GRID)) * 2 - 1) * amp


def _clip(v: float) -> float:
    return max(0.0, min(100.0, v))


def _daily(vm: Vm, epoch: int) -> float:
    hour = (epoch % DAY) / 3600
    return math.cos((hour - vm.cpu_peak_hour) / 24 * 2 * math.pi)


def _weekday_factor(epoch: int) -> float:
    dow = (epoch // DAY + 4) % 7  # 1970-01-01 was a Thursday; Monday = 0
    return 0.7 if dow >= 5 else 1.0


def cpu(vm: Vm, epoch: int) -> float:
    if vm.role == "idle":
        return _clip(3 + 0.8 * _daily(vm, epoch) + _noise(vm, 1, epoch, 1.2))
    base = 35 + 15 * _daily(vm, epoch)
    return _clip(base * _weekday_factor(epoch) + _noise(vm, 1, epoch, 4))


def memory(vm: Vm, epoch: int) -> float:
    if vm.role == "leak":  # sawtooth; the periodic restart resets it
        frac = ((epoch + vm.leak_phase) % vm.leak_period) / vm.leak_period
        return _clip(30 + 62 * frac + _noise(vm, 2, epoch, 0.8))
    if vm.role == "idle":
        return _clip(14 + _noise(vm, 2, epoch, 1.5))
    return _clip(45 + 10 * _daily(vm, epoch) + _noise(vm, 2, epoch, 3))


def disk(vm: Vm, epoch: int) -> float:
    if vm.role == "disk":  # steady fill, periodic cleanup
        frac = ((epoch + vm.disk_phase) % vm.disk_period) / vm.disk_period
        return _clip(40 + 55 * frac)
    return _clip(35 + (vm.seed % 20) + _noise(vm, 3, epoch, 0.3))


def net(vm: Vm, epoch: int, salt: int) -> float:
    return max(0.0, cpu(vm, epoch) * 1.0e5 * (1 + _noise(vm, salt, epoch, 0.3)))


def value(vm: Vm, metric: str, epoch: int) -> float:
    if metric == "availability":
        return 1.0 if is_available(vm, epoch) else 0.0
    if metric == "cpu_percent":
        return round(cpu(vm, epoch), 3)
    if metric == "memory_percent":
        return round(memory(vm, epoch), 3)
    if metric == "disk_used_percent":
        return round(disk(vm, epoch), 3)
    if metric == "network_in_bytes":
        return round(net(vm, epoch, 4), 1)
    if metric == "network_out_bytes":
        return round(net(vm, epoch, 5) * 0.6, 1)
    raise KeyError(metric)


def grid_times(start: datetime, end: datetime, step: int) -> list[int]:
    s = math.ceil(start.timestamp() / step) * step
    e = end.timestamp()
    return list(range(s, int(math.ceil(e)), step)) if s < e else []


def series(vm: Vm, metric: str, start: datetime, end: datetime, step: int):
    """Samples at multiples of `step`. Stopped VMs emit nothing (as real clouds do)."""
    if vm.role == "stopped":
        return []
    return [(t, value(vm, metric, t)) for t in grid_times(start, end, step)]


def iso(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, UTC).isoformat().replace("+00:00", "Z")


def ground_truth(account_ref: str, scenario: str, start: datetime, end: datetime) -> dict:
    s_epoch, e_epoch = int(start.timestamp()), int(end.timestamp())
    vms = inventory(account_ref, scenario)
    faults: list[dict] = []
    resources = []
    for vm in vms:
        resources.append({"id": vm.id, "name": vm.name, "role": vm.role,
                          "power_state": vm.power_state, "size_sku": vm.size_sku})
        if vm.role == "stopped":
            faults.append({"resource_id": vm.id, "kind": "stopped", "start": iso(s_epoch),
                           "end": iso(e_epoch)})
            continue
        if vm.role == "unresponsive":
            faults.append({"resource_id": vm.id, "kind": "unresponsive", "start": iso(s_epoch),
                           "end": iso(e_epoch)})
        elif vm.role in ("leak", "disk", "idle"):
            kind = {"leak": "memory_leak", "disk": "disk_fill", "idle": "idle"}[vm.role]
            faults.append({"resource_id": vm.id, "kind": kind, "start": iso(s_epoch),
                           "end": iso(e_epoch)})
        for day in range(_day_index(s_epoch), _day_index(e_epoch) + 1):
            out = outage_for_day(vm, day)
            if out and out[0] >= s_epoch and out[1] <= e_epoch:
                faults.append({"resource_id": vm.id, "kind": "outage", "start": iso(out[0]),
                               "end": iso(out[1]),
                               "recurring": vm.role == "flaky"})
    uptime = {}
    ts = grid_times(start, end, GRID)
    for vm in vms:
        if vm.role == "stopped" or not ts:
            uptime[vm.id] = None
        else:
            uptime[vm.id] = round(100.0 * sum(is_available(vm, t) for t in ts) / len(ts), 4)
    return {"account_ref": account_ref, "scenario": scenario, "start": iso(s_epoch),
            "end": iso(e_epoch), "resources": resources, "faults": faults, "uptime_percent": uptime}


__all__ = ["timedelta"]
