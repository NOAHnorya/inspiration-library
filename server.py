import json
import os
from pathlib import Path
import subprocess
import sys
from typing import List, Optional

from fastapi import FastAPI, Query, Body
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from core import Library, ROOT, now
from tagging import Catalog
from agent_tools import AgentTools
from groups import Groups
from maintenance import Maintenance
from sync_config import load_sync_config, public_sources, resolve_config_path

library = Library()
catalog = Catalog(library)
agent = AgentTools(catalog)
groups = Groups(library)
maintenance = Maintenance(library, catalog)
app = FastAPI(title="灵感库", version="1.0")
app.mount("/assets/items", StaticFiles(directory=library.items_dir), name="assets")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


class ItemPatch(BaseModel):
    notes: Optional[str] = None
    annotation: Optional[dict] = None
    add_tags: List[str] = Field(default_factory=list)
    remove_tags: List[str] = Field(default_factory=list)
    lock_tags: List[str] = Field(default_factory=list)
    unlock_tags: List[str] = Field(default_factory=list)


class ImportPath(BaseModel):
    path: str
    download: bool = True


class ImportURL(BaseModel):
    url: str
    download: bool = True


class IDsRequest(BaseModel):
    ids: List[str]
    goal: str = ""


class GroupInput(BaseModel):
    name: str
    description: str = ""
    item_ids: List[str] = Field(default_factory=list)


@app.exception_handler(KeyError)
def missing_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=404, content={"ok": False, "error": str(exc)})


@app.exception_handler(ValueError)
def invalid_handler(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=400, content={"ok": False, "error": str(exc)})


@app.get("/api/health")
def health():
    return {"ok": True, "stats": library.stats()}


@app.get("/api/items")
def search_items(q: str = "", tags: List[str] = Query([]), match: str = "all",
                 exclude: List[str] = Query([]), platform: str = "", collection: str = "",
                 limit: int = Query(60, ge=1, le=200), offset: int = Query(0, ge=0),
                 semantic: bool = True, min_score: float = 0.16, sort: str = "relevance"):
    return catalog.search(q, tags, match, exclude, platform, collection, limit, offset, semantic, min_score, sort)


@app.get("/api/items/{item_id}")
def get_item(item_id: str):
    item = library.get_item(item_id)
    if not item:
        raise KeyError("素材不存在: " + item_id)
    return item


@app.patch("/api/items/{item_id}")
def patch_item(item_id: str, patch: ItemPatch):
    return catalog.update_item(item_id, patch.notes, patch.annotation, patch.add_tags,
                               patch.remove_tags, patch.lock_tags, patch.unlock_tags)


@app.post("/api/items/{item_id}/annotate")
def annotate_item(item_id: str, regenerate: bool = False):
    return catalog.auto_annotate(item_id, regenerate)


@app.post("/api/items/{item_id}/retry-cover")
def retry_cover(item_id: str):
    item = library.get_item(item_id)
    if not item:
        raise KeyError("素材不存在: " + item_id)
    asset = library.download_asset(item_id, item["cover_url"])
    status = "ready" if asset else "needs_review"
    with library.connect() as conn:
        conn.execute("UPDATE items SET import_status=?,updated_at=? WHERE id=?", (status, now(), item_id))
    return {"ok": bool(asset), "status": status, "asset": asset}


@app.get("/api/tags")
def tag_list(query: str = ""):
    return catalog.list_tags(query)


@app.get("/api/filters")
def filters():
    with library.connect() as conn:
        platforms = [r[0] for r in conn.execute("SELECT DISTINCT platform FROM items ORDER BY platform")]
        collections = [r[0] for r in conn.execute("SELECT DISTINCT collection FROM items WHERE collection!='' ORDER BY collection")]
    return {"platforms": platforms, "collections": collections}


@app.get("/api/imports")
def import_list(limit: int = 100):
    return library.list_imports(limit)


@app.post("/api/import/xhs")
def import_xhs(data: ImportPath):
    results = library.import_xhs(data.path, data.download)
    return {"count": len(results), "ready": sum(r["status"] == "ready" for r in results),
            "needs_review": sum(r["status"] == "needs_review" for r in results),
            "failed": sum(r["status"] == "failed" for r in results), "results": results}


@app.post("/api/import/douyin")
def import_douyin(data: ImportPath):
    results = library.import_douyin(data.path, data.download)
    return {"count": len(results), "ready": sum(r["status"] == "ready" for r in results),
            "needs_review": sum(r["status"] == "needs_review" for r in results),
            "failed": sum(r["status"] == "failed" for r in results), "results": results}


@app.post("/api/import/url")
def import_url(data: ImportURL):
    return library.import_url(data.url, data.download)


@app.post("/api/import/file")
def import_file(data: ImportPath):
    return library.import_file(data.path)


@app.get("/api/agent/find")
def agent_find(q: str = "", tags: List[str] = Query([]), match: str = "all",
               exclude: List[str] = Query([]), platform: str = "", collection: str = "",
               limit: int = 5, semantic: bool = True):
    return agent.find_inspiration(q, tags, match, exclude, platform, collection, limit, semantic)


@app.post("/api/agent/compare")
def agent_compare(data: IDsRequest):
    return agent.compare_inspiration(data.ids)


@app.post("/api/agent/brief")
def agent_brief(data: IDsRequest):
    return agent.create_reference_brief(data.ids, data.goal)


@app.get("/api/groups")
def group_list():
    return groups.list()


@app.post("/api/groups")
def group_create(data: GroupInput):
    return groups.create(data.name, data.description, data.item_ids)


@app.get("/api/groups/{group_id}")
def group_get(group_id: str):
    return groups.get(group_id)


@app.put("/api/groups/{group_id}")
def group_update(group_id: str, data: GroupInput):
    return groups.update(group_id, data.name, data.description, data.item_ids)


@app.get("/api/items/{item_id}/similar")
def similar_items(item_id: str, tags: List[str] = Query([]), match: str = "all",
                  exclude: List[str] = Query([]), platform: str = "", collection: str = "", limit: int = 10):
    return maintenance.visual_search(item_id, tags, match, exclude, platform, collection, limit)


@app.get("/api/maintenance/health")
def maintenance_health():
    return maintenance.health_check()


@app.post("/api/maintenance/reindex")
def maintenance_reindex():
    return maintenance.reindex_all()


@app.post("/api/maintenance/backup")
def maintenance_backup(data: dict = Body(default={})):
    return maintenance.backup(data.get("output"))


def sync_configuration():
    try:
        config = load_sync_config()
        return {"configured": True, "sources": public_sources(config)}
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        return {"configured": False, "sources": [], "configuration_error": str(exc)}


def read_sync_status():
    path = library.data_dir / "sync_status.json"
    status = {"state": "idle", "message": "尚未更新", "results": []}
    if path.exists():
        status = json.loads(path.read_text(encoding="utf-8"))
    status.update(sync_configuration())
    return status


@app.get("/api/sync/collections")
def get_sync_status():
    return read_sync_status()


@app.post("/api/sync/collections")
def start_collection_sync(data: dict = Body(default={})):
    current = read_sync_status()
    pid = current.get("pid")
    if current.get("state") == "running" and pid:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            pass
        else:
            raise ValueError("收藏更新正在进行，请勿重复启动")
    config = load_sync_config()
    allowed = {source["key"] for source in config["sources"]}
    selected = list(dict.fromkeys(data.get("sources", [])))
    if any(key not in allowed for key in selected):
        raise ValueError("未知的收藏夹")
    command = [sys.executable, str(ROOT / "sync_collections.py"), "--config", config["config_path"]]
    for key in selected:
        command.extend(["--only", key])
    log_path = library.data_dir / "sync.log"
    with log_path.open("ab") as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=dict(os.environ, INSPIRATION_DATA_DIR=str(library.data_dir),
                     INSPIRATION_SYNC_CONFIG=config["config_path"], PYTHONDONTWRITEBYTECODE="1"),
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    status = {"state": "running", "pid": process.pid, "started_at": now(),
              "message": "正在启动只读更新", "results": []}
    path = library.data_dir / "sync_status.json"
    temporary = path.with_suffix(".start.tmp")
    temporary.write_text(json.dumps(status, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    return {"ok": True, "status": status}


@app.get("/")
def index():
    return FileResponse(ROOT / "static" / "index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=int(os.environ.get("PORT", "8765")), log_level="info")
