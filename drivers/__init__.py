"""Pluggable "hands" for collection sync.

Order used by `driver: auto`: ego-browser, then KimiCU, then handoff to the
user's own agent. Manual JSON import (cli.py import-xhs / import-douyin) always
works without any driver.
"""
from .base import (Blocked, DriverUnavailable, HandoffPending, NeedsLogin, ensure_safe, native_id,
                   normalize_records)
from .ego_browser import EgoBrowserDriver
from .handoff import HandoffDriver, build_task, task_paths
from .kimicu import KimiCUDriver

DRIVERS = {driver.name: driver for driver in (EgoBrowserDriver, KimiCUDriver, HandoffDriver)}
AUTO_ORDER = ["ego-browser", "kimicu", "handoff"]
DRIVER_NAMES = ["auto"] + list(DRIVERS)


def detect():
    results = []
    for name in AUTO_ORDER:
        driver = DRIVERS[name]
        available, detail = driver.check()
        results.append({"name": name, "label": driver.label, "available": available, "detail": detail})
    return results


def resolve_driver_name(requested=None):
    if requested in (None, "", "auto"):
        for name in AUTO_ORDER:
            if DRIVERS[name].check()[0]:
                return name
        return "handoff"
    if requested not in DRIVERS:
        raise ValueError("未知的同步方式: " + requested + "，可选：" + "、".join(DRIVER_NAMES))
    return requested
