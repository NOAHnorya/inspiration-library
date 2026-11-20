"""MCP server for the inspiration library (stdio, no extra dependencies).

Any MCP-capable agent (Claude Code, Codex, Cursor, Kimi Code, Gemini CLI, DSH...)
can search the library, cite items by stable @ins_ IDs, start a collection
sync, and hand back records it read with its own browser.

    python mcp_server.py [--data-dir PATH] [--config PATH]

Logs go to stderr; stdout carries only JSON-RPC messages.
"""
import argparse
import base64
import io
import json
import os
from pathlib import Path
import sys
import traceback

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from agent_tools import AgentTools  # noqa: E402
from core import Library  # noqa: E402
from drivers import build_task, detect, resolve_driver_name, task_paths  # noqa: E402
from maintenance import Maintenance  # noqa: E402
from sync_collections import read_status, run as run_sync, spawn, submit, load_existing, source_path  # noqa: E402
from sync_config import load_sync_config  # noqa: E402
from tagging import Catalog  # noqa: E402
from drivers.base import native_id  # noqa: E402

SERVER_INFO = {"name": "inspiration-library", "version": "1.1.0"}
SUPPORTED_VERSIONS = ["2025-06-18", "2025-03-26", "2024-11-05"]
INSTRUCTIONS = (
    "本地审美灵感库（小红书 / 抖音收藏 + 网页 + 本地文件）。先用 find_inspiration 检索，"
    "把结果里的 @ins_… 引用写进创作方案；引用前可用 validate_references 校验。"
    "同步收藏夹用 sync_collections；返回 waiting_for_agent 时，用你自己的浏览器按任务步骤只读读取，"
    "再调用 submit_collection_records 提交。遇到登录或验证码要停下让用户处理，不要绕过。"
)

STR_LIST = {"type": "array", "items": {"type": "string"}}
FILTERS = {
    "tags": {**STR_LIST, "description": "标签，如 Y2K、高饱和、海报。list_tags 可查全部标签"},
    "match": {"type": "string", "enum": ["all", "any"], "default": "all", "description": "多个标签同时满足(all)或任一(any)"},
    "exclude": {**STR_LIST, "description": "排除的标签"},
    "platform": {"type": "string", "enum": ["", "xiaohongshu", "douyin", "web", "file"], "default": ""},
    "collection": {"type": "string", "default": "", "description": "收藏夹名称"},
}
TOOLS = [
    {"name": "find_inspiration",
     "description": "按关键词和标签检索灵感，返回带 @ins_ 引用 ID、标题、来源链接、本地封面路径和标签的精简结果。",
     "inputSchema": {"type": "object", "properties": {
         "query": {"type": "string", "default": "", "description": "关键词，支持中文模糊匹配"},
         **FILTERS, "limit": {"type": "integer", "default": 8, "minimum": 1, "maximum": 50}}}},
    {"name": "get_inspiration",
     "description": "查看一条灵感的完整信息（标签、标注、备注、来源）。include_cover=true 时附带封面图片。",
     "inputSchema": {"type": "object", "required": ["reference"], "properties": {
         "reference": {"type": "string", "description": "@ins_… 或 ins_…"},
         "include_cover": {"type": "boolean", "default": False}}}},
    {"name": "compare_inspiration",
     "description": "对比 2–5 条灵感的共同点与差异（风格、配色、构图等）。",
     "inputSchema": {"type": "object", "required": ["references"], "properties": {
         "references": {**STR_LIST, "minItems": 2, "maxItems": 5}}}},
    {"name": "create_reference_brief",
     "description": "把 2–5 条灵感组合成一份创作参考稿，可写明目标。",
     "inputSchema": {"type": "object", "required": ["references"], "properties": {
         "references": {**STR_LIST, "minItems": 1, "maxItems": 5},
         "goal": {"type": "string", "default": "", "description": "例如：设计一个开发者工具落地页"}}}},
    {"name": "validate_references",
     "description": "检查一段文字里的 @ins_ 引用是否都存在。",
     "inputSchema": {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}},
    {"name": "similar_inspiration",
     "description": "按封面颜色与布局找相似灵感。",
     "inputSchema": {"type": "object", "required": ["reference"], "properties": {
         "reference": {"type": "string"}, **FILTERS, "limit": {"type": "integer", "default": 8}}}},
    {"name": "list_tags",
     "description": "列出可用标签及数量。",
     "inputSchema": {"type": "object", "properties": {"query": {"type": "string", "default": ""}}}},
    {"name": "library_status",
     "description": "灵感库概况：素材数量、健康检查、已配置的收藏夹、可用的同步方式、最近一次同步状态。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "sync_collections",
     "description": ("只读增量更新已配置的收藏夹。自动选择 ego-browser → KimiCU → 交给你（Agent）读取。"
                     "后台运行时用 library_status 查看进度；返回 waiting_for_agent 时按 tasks 里的步骤读取后调用 submit_collection_records。"),
     "inputSchema": {"type": "object", "properties": {
         "sources": {**STR_LIST, "description": "收藏夹 key，留空为全部"},
         "driver": {"type": "string", "enum": ["auto", "ego-browser", "kimicu", "handoff"], "default": "auto",
                    "description": "handoff = 由你用自己的浏览器工具读取"}}}},
    {"name": "get_sync_tasks",
     "description": "列出等待 Agent 读取的收藏夹任务（打开哪个链接、读哪些字段、何时停止、已有作品 ID）。",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "submit_collection_records",
     "description": "提交你用自己的浏览器读到的收藏夹条目（保持页面顺序），灵感库会去重、下载封面、打标签并建索引。",
     "inputSchema": {"type": "object", "required": ["source_key", "records"], "properties": {
         "source_key": {"type": "string"},
         "records": {"type": "array", "items": {"type": "object", "required": ["url"], "properties": {
             "url": {"type": "string"}, "title": {"type": "string"},
             "author": {"type": "string"}, "cover": {"type": "string"}}}}}}},
    {"name": "import_url",
     "description": "把一个公开网页加入灵感库（只读公开 HTML 元数据）。",
     "inputSchema": {"type": "object", "required": ["url"], "properties": {"url": {"type": "string"}}}},
    {"name": "import_file",
     "description": "把本机一个图片或项目文件加入灵感库。",
     "inputSchema": {"type": "object", "required": ["path"], "properties": {"path": {"type": "string"}}}},
]


READ_ONLY = {"find_inspiration", "get_inspiration", "compare_inspiration", "create_reference_brief",
             "validate_references", "similar_inspiration", "list_tags", "library_status", "get_sync_tasks"}
for _tool in TOOLS:
    _read_only = _tool["name"] in READ_ONLY
    _tool["annotations"] = {"readOnlyHint": _read_only, "destructiveHint": False, "idempotentHint": _read_only,
                            "openWorldHint": _tool["name"] in {"sync_collections", "import_url"}}


class InspirationServer:
    def __init__(self, data_dir=None, config_path=None):
        self.library = Library(data_dir)
        self.catalog = Catalog(self.library)
        self.agent = AgentTools(self.catalog)
        self.maintenance = Maintenance(self.library, self.catalog)
        self.config_path = config_path

    def config(self):
        try:
            return load_sync_config(self.config_path)
        except (ValueError, OSError) as exc:
            return {"error": str(exc), "sources": []}

    def pending_tasks(self):
        folder = self.library.data_dir / "handoff"
        tasks = []
        for path in sorted(folder.glob("*.task.json")) if folder.exists() else []:
            task = json.loads(path.read_text(encoding="utf-8"))
            task["known_id_count"] = len(task.get("known_ids", []))
            tasks.append(task)
        return tasks

    def cover_image(self, item):
        if not item.get("cover_local"):
            return None
        from PIL import Image
        with Image.open(self.library.data_dir / item["cover_local"]) as source:
            image = source.convert("RGB")
            image.thumbnail((768, 768))
            buffer = io.BytesIO()
            image.save(buffer, "JPEG", quality=82)
        return {"type": "image", "data": base64.b64encode(buffer.getvalue()).decode(), "mimeType": "image/jpeg"}

    def call(self, name, args):
        filters = [args.get("tags") or [], args.get("match", "all"), args.get("exclude") or [],
                   args.get("platform", ""), args.get("collection", "")]
        if name == "find_inspiration":
            return self.agent.find_inspiration(args.get("query", ""), *filters, int(args.get("limit", 8)))
        if name == "get_inspiration":
            item = self.agent.get_inspiration(args["reference"])
            extra = self.cover_image(item) if args.get("include_cover") else None
            return (item, extra)
        if name == "compare_inspiration":
            return self.agent.compare_inspiration(args["references"])
        if name == "create_reference_brief":
            return self.agent.create_reference_brief(args["references"], args.get("goal", ""))
        if name == "validate_references":
            return self.agent.validate_references(args["text"])
        if name == "similar_inspiration":
            item = self.agent.resolve(args["reference"])
            return self.maintenance.visual_search(item["id"], *filters, int(args.get("limit", 8)))
        if name == "list_tags":
            return self.catalog.list_tags(args.get("query", ""))
        if name == "library_status":
            config = self.config()
            return {"stats": self.library.stats(), "health": self.maintenance.health_check(),
                    "sources": [{key: source.get(key) for key in ("key", "platform", "collection", "driver")}
                                for source in config.get("sources", [])],
                    "config_error": config.get("error"), "drivers": detect(), "auto_driver": resolve_driver_name("auto"),
                    "sync": read_status(self.library.data_dir), "pending_agent_tasks": len(self.pending_tasks())}
        if name == "sync_collections":
            return self.sync(args.get("sources") or [], args.get("driver") or "auto")
        if name == "get_sync_tasks":
            return {"tasks": self.pending_tasks()}
        if name == "submit_collection_records":
            return submit(args["source_key"], args["records"], self.config_path)
        if name == "import_url":
            return self.library.import_url(args["url"])
        if name == "import_file":
            return self.library.import_file(args["path"])
        raise ValueError("未知工具: " + name)

    def sync(self, keys, driver):
        config = load_sync_config(self.config_path)
        selected = [source for source in config["sources"] if not keys or source["key"] in keys]
        names = {resolve_driver_name(driver if driver != "auto" else source["driver"]) for source in selected}
        if names == {"handoff"}:
            tasks = []
            for source in selected:
                existing = load_existing(source_path(source, config))
                known = {native_id(record) for record in existing if native_id(record)}
                task = build_task(source, known, self.library.data_dir)
                task_path, _ = task_paths(self.library.data_dir, source["key"])
                task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                task["known_id_count"] = len(task["known_ids"])
                tasks.append(task)
            return {"state": "waiting_for_agent",
                    "message": "请用你自己的浏览器工具按步骤只读读取，然后调用 submit_collection_records。",
                    "tasks": tasks}
        status = spawn(keys, self.config_path, None if driver == "auto" else driver, self.library.data_dir)
        return {**status, "message": "已在后台开始同步（" + "、".join(sorted(names)) + "），稍后用 library_status 查看结果。"}


def respond(message_id, result=None, error=None):
    payload = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle(server, message):
    method = message.get("method")
    message_id = message.get("id")
    if message_id is None:
        return
    if method == "initialize":
        requested = message.get("params", {}).get("protocolVersion")
        version = requested if requested in SUPPORTED_VERSIONS else SUPPORTED_VERSIONS[0]
        respond(message_id, {"protocolVersion": version, "capabilities": {"tools": {"listChanged": False}},
                             "serverInfo": SERVER_INFO, "instructions": INSTRUCTIONS})
    elif method == "ping":
        respond(message_id, {})
    elif method == "tools/list":
        respond(message_id, {"tools": TOOLS})
    elif method == "tools/call":
        params = message.get("params", {})
        try:
            value = server.call(params.get("name"), params.get("arguments") or {})
            extra = None
            if isinstance(value, tuple):
                value, extra = value
            content = [{"type": "text", "text": json.dumps(value, ensure_ascii=False, indent=2)}]
            if extra:
                content.append(extra)
            respond(message_id, {"content": content, "isError": False})
        except Exception as exc:
            print(traceback.format_exc(), file=sys.stderr)
            respond(message_id, {"content": [{"type": "text", "text": "错误：" + str(exc)}], "isError": True})
    elif method in ("resources/list", "prompts/list"):
        respond(message_id, {method.split("/")[0]: []})
    else:
        respond(message_id, error={"code": -32601, "message": "Method not found: " + str(method)})


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--data-dir", default=os.environ.get("INSPIRATION_DATA_DIR"))
    parser.add_argument("--config", default=os.environ.get("INSPIRATION_SYNC_CONFIG"))
    args = parser.parse_args()
    if args.data_dir:
        os.environ["INSPIRATION_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.config:
        os.environ["INSPIRATION_SYNC_CONFIG"] = str(Path(args.config).expanduser().resolve())
    server = InspirationServer(args.data_dir, args.config)
    print("inspiration-library MCP ready, data: " + str(server.library.data_dir), file=sys.stderr)
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            respond(None, error={"code": -32700, "message": "Parse error"})
            continue
        handle(server, message)


if __name__ == "__main__":
    main()
