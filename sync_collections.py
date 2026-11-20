"""Read-only incremental sync of configured 小红书 / 抖音 collections.

The browser work is done by a pluggable driver (see drivers/). This module
owns everything after the records come back: merging into the local raw JSON,
importing new items, downloading covers, tagging and indexing.
"""
import argparse
import json
import os
from pathlib import Path

from core import Library, now
from drivers import (DRIVERS, Blocked, DriverUnavailable, HandoffPending, NeedsLogin, detect, native_id,
                     normalize_records, resolve_driver_name, task_paths)
from maintenance import Maintenance
from sync_config import load_sync_config
from tagging import Catalog


def source_path(source, config):
    path = Path(source["file"]).expanduser()
    return path if path.is_absolute() else Path(config["config_dir"]) / path


def load_existing(path):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []


PLACEHOLDER_TITLES = {"", "未命名素材"}


def merge_record(old, new):
    """Newer page data wins, but never replaces a known value with an empty one."""
    merged = dict(old)
    for field, value in new.items():
        if value in (None, "", {}, []) or (field == "title" and value in PLACEHOLDER_TITLES and old.get("title")):
            continue
        merged[field] = value
    return merged


def merge_records(path, records):
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = load_existing(path)
    known_ids = {native_id(record) for record in existing if native_id(record)}
    new_records = [record for record in records if native_id(record) not in known_ids]
    old_by_id = {native_id(record): record for record in existing if native_id(record)}
    merged = []
    seen = set()
    for record in records + existing:
        item_id = native_id(record)
        if not item_id or item_id in seen:
            continue
        merged.append(merge_record(old_by_id.get(item_id, {}), record))
        seen.add(item_id)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return new_records


def retry_covers(library, catalog, results):
    succeeded = 0
    for result in results:
        if result.get("status") != "needs_review" or not result.get("id"):
            continue
        item = library.get_item(result["id"])
        if not item or not item.get("cover_url"):
            continue
        asset = library.download_asset(item["id"], item["cover_url"])
        if not asset:
            continue
        with library.connect() as conn:
            conn.execute("UPDATE items SET import_status='ready',updated_at=? WHERE id=?", (now(), item["id"]))
        catalog.auto_annotate(item["id"], regenerate=True)
        result["status"] = "ready"
        succeeded += 1
    return succeeded


def import_new(library, catalog, source, records):
    incoming = library.data_dir / ("sync_" + source["key"] + "_new.json")
    incoming.write_text(json.dumps(records, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if not records:
        return {"imported": 0, "needs_review": 0, "cover_retries_succeeded": 0}
    importer = library.import_douyin if source["platform"] == "douyin" else library.import_xhs
    results = importer(incoming, True)
    for result in results:
        if result.get("id"):
            catalog.auto_annotate(result["id"])
    retries = retry_covers(library, catalog, results)
    return {"imported": sum(result["status"] == "ready" for result in results),
            "needs_review": sum(result["status"] == "needs_review" for result in results),
            "cover_retries_succeeded": retries}


def backfill_collection_positions(library, sources, config):
    results = []
    for source in sources:
        path = source_path(source, config)
        if not path.exists():
            results.append({"key": source["key"], "updated": 0, "missing_file": True})
            continue
        records = load_existing(path)
        prefix = "ins_douyin_" if source["platform"] == "douyin" else "ins_xhs_"
        updated = 0
        with library.connect() as conn:
            for position, record in enumerate(records):
                item_id = native_id(record)
                if not item_id:
                    continue
                cursor = conn.execute("UPDATE items SET collection_position=? WHERE id=?",
                                      (position, prefix + item_id))
                updated += cursor.rowcount
        results.append({"key": source["key"], "updated": updated})
    return {"sources": results, "updated": sum(result["updated"] for result in results)}


def ingest(library, catalog, source, records, config):
    """Merge driver or agent records for one source and import what is new."""
    path = source_path(source, config)
    new_records = merge_records(path, records)
    imported = import_new(library, catalog, source, new_records)
    backfill_collection_positions(library, [source], config)
    return {"found": len(records), "new": len(new_records), **imported}


class Status:
    def __init__(self, path):
        self.path = path
        self.value = {}

    def update(self, **values):
        self.value.update(values)
        self.value["updated_at"] = now()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)

    def progress(self, source, round_number, found, new):
        self.update(message=f"{source['collection']}：第 {round_number} 次读取，已见 {found} 条，新增 {new} 条",
                    current={"key": source["key"], "collection": source["collection"], "driver": source.get("driver_used"),
                             "round": round_number, "found": found, "new": new})


def finish_state(results):
    states = {result["status"] for result in results}
    if states & {"needs_login", "blocked"}:
        return "paused"
    if "waiting_for_agent" in states:
        return "waiting_for_agent"
    if "failed" in states:
        return "failed"
    return "done"


def run(keys=None, config_path=None, driver_override=None):
    config = load_sync_config(config_path)
    selected = [source for source in config["sources"] if not keys or source["key"] in keys]
    if not selected:
        raise ValueError("没有选中需要更新的收藏夹")
    unknown = set(keys or []) - {source["key"] for source in config["sources"]}
    if unknown:
        raise ValueError("配置中不存在收藏夹: " + ", ".join(sorted(unknown)))
    library = Library()
    status = Status(library.data_dir / "sync_status.json")
    status.update(state="running", pid=os.getpid(), started_at=now(), message="准备只读更新",
                  current=None, results=[], finished_at=None, error=None)
    catalog = Catalog(library)
    maintenance = Maintenance(library, catalog)
    driver_config = {**config, "data_dir": str(library.data_dir)}
    groups = {}
    for source in selected:
        name = resolve_driver_name(driver_override or source["driver"])
        groups.setdefault(name, []).append({**source, "driver_used": name})
    results = []
    total_new = 0
    stopped = False
    try:
        for name, sources in groups.items():
            if stopped:
                break
            try:
                driver = DRIVERS[name](driver_config)
            except DriverUnavailable as exc:
                for source in sources:
                    results.append({"key": source["key"], "platform": source["platform"], "driver": name,
                                    "collection": source["collection"], "status": "failed", "error": str(exc)})
                status.update(results=results)
                continue
            with driver:
                for source in sources:
                    status.update(message="打开收藏夹：" + source["collection"],
                                  current={"key": source["key"], "collection": source["collection"], "driver": name})
                    base = {"key": source["key"], "platform": source["platform"],
                            "collection": source["collection"], "driver": name}
                    try:
                        existing = load_existing(source_path(source, config))
                        known_ids = {native_id(record) for record in existing if native_id(record)}
                        records = driver.read_collection(source, known_ids, status)
                        outcome = ingest(library, catalog, source, records, config)
                        total_new += outcome["new"]
                        result = {**base, "status": "done", **outcome}
                    except HandoffPending as exc:
                        result = {**base, "status": "waiting_for_agent", "error": str(exc),
                                  "task_path": exc.task["task_path"], "result_path": exc.task["result_path"]}
                    except NeedsLogin as exc:
                        result = {**base, "status": "needs_login", "error": str(exc)}
                    except Blocked as exc:
                        result = {**base, "status": "blocked", "error": str(exc)}
                        stopped = True
                    except Exception as exc:
                        result = {**base, "status": "failed", "error": str(exc)}
                    results.append(result)
                    status.update(results=results)
                    if stopped:
                        break
        if total_new:
            maintenance.build_visual_index()
        health = maintenance.health_check()
        status.update(state=finish_state(results), current=None, results=results, finished_at=now(),
                      message=f"更新结束：新增 {total_new} 条", stats=library.stats(), health_ok=health["ok"])
    except Exception as exc:
        status.update(state="failed", current=None, results=results, finished_at=now(),
                      message="更新失败", error=str(exc))
        raise
    return status.value


def submit(key, records, config_path=None):
    """Accept records an agent read with its own browser (handoff driver)."""
    config = load_sync_config(config_path)
    source = next((source for source in config["sources"] if source["key"] == key), None)
    if not source:
        raise ValueError("配置中不存在收藏夹: " + key)
    library = Library()
    catalog = Catalog(library)
    cleaned = normalize_records(records, source)
    if not cleaned:
        raise ValueError("没有有效条目。请检查链接格式：抖音为 /video/数字ID 或 /note/数字ID，小红书链接末尾为 24 位笔记 ID。")
    outcome = ingest(library, catalog, source, cleaned, config)
    if outcome["new"]:
        Maintenance(library, catalog).build_visual_index()
    task_path, _ = task_paths(library.data_dir, key)
    if task_path.exists():
        task_path.unlink()
    result = {"key": key, "platform": source["platform"], "collection": source["collection"],
              "driver": "handoff", "status": "done", "skipped_invalid": len(records) - len(cleaned), **outcome}
    status = Status(library.data_dir / "sync_status.json")
    if status.path.exists():
        status.value = json.loads(status.path.read_text(encoding="utf-8"))
    previous = [item for item in status.value.get("results", []) if item.get("key") != key]
    results = previous + [result]
    status.update(state=finish_state(results), results=results, current=None, finished_at=now(),
                  message="已导入 Agent 读取的「" + source["collection"] + f"」：新增 {outcome['new']} 条",
                  stats=library.stats())
    return result


def read_status(data_dir):
    path = Path(data_dir) / "sync_status.json"
    status = {"state": "idle", "message": "尚未更新", "results": []}
    if path.exists():
        status = json.loads(path.read_text(encoding="utf-8"))
    pid = status.get("pid")
    if status.get("state") == "running" and pid:
        try:
            os.kill(pid, 0)
        except (ProcessLookupError, PermissionError, OSError):
            status.update(state="failed", message="上次更新进程已退出，请重试")
    return status


def spawn(keys=None, config_path=None, driver=None, data_dir=None):
    """Start a sync in the background (used by the web UI and the MCP server)."""
    import subprocess
    import sys
    library = Library(data_dir)
    current = read_status(library.data_dir)
    if current.get("state") == "running":
        raise ValueError("收藏更新正在进行，请勿重复启动")
    config = load_sync_config(config_path)
    allowed = {source["key"] for source in config["sources"]}
    selected = list(dict.fromkeys(keys or []))
    if any(key not in allowed for key in selected):
        raise ValueError("未知的收藏夹: " + ", ".join(key for key in selected if key not in allowed))
    root = Path(__file__).resolve().parent
    command = [sys.executable, str(root / "sync_collections.py"), "--config", config["config_path"]]
    for key in selected:
        command.extend(["--only", key])
    if driver:
        command.extend(["--driver", driver])
    log_path = library.data_dir / "sync.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command, cwd=root,
            env=dict(os.environ, INSPIRATION_DATA_DIR=str(library.data_dir),
                     INSPIRATION_SYNC_CONFIG=config["config_path"], PYTHONDONTWRITEBYTECODE="1"),
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
        )
    status = {"state": "running", "pid": process.pid, "started_at": now(),
              "message": "正在启动只读更新", "results": []}
    path = library.data_dir / "sync_status.json"
    temporary = path.with_suffix(".start.tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return status


def main():
    parser = argparse.ArgumentParser(description="只读增量更新已配置的小红书 / 抖音收藏夹")
    parser.add_argument("--config")
    parser.add_argument("--only", action="append")
    parser.add_argument("--driver", choices=["auto"] + list(DRIVERS))
    parser.add_argument("--rebuild-order", action="store_true")
    parser.add_argument("--list-drivers", action="store_true")
    parser.add_argument("--submit", metavar="KEY", help="导入 Agent 读取的结果（配合 --records）")
    parser.add_argument("--records", metavar="PATH")
    args = parser.parse_args()
    if args.list_drivers:
        result = {"drivers": detect(), "auto": resolve_driver_name("auto")}
    elif args.rebuild_order:
        config = load_sync_config(args.config)
        result = backfill_collection_positions(Library(), config["sources"], config)
    elif args.submit:
        if not args.records:
            parser.error("--submit 需要 --records")
        result = submit(args.submit, json.loads(Path(args.records).read_text(encoding="utf-8")), args.config)
    else:
        result = run(args.only, args.config, args.driver)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
