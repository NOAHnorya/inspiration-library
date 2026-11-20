"""Handoff driver: lets the user's own agent do the reading.

Any agent with a browser tool (Claude in Chrome, Codex, OpenClaw, Kimi, DSH...)
can sync this way. The library writes a task file describing exactly what to
read and in which format; the agent reads the collection with its own tools and
hands the records back through the MCP tool `submit_collection_records` or by
writing the result file and running `python cli.py sync --only <key>`.
"""
import json
from pathlib import Path

from core import now

from .base import STOP_AFTER_KNOWN, Driver, HandoffPending, normalize_records

RECORD_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "required": ["url", "title"],
        "properties": {
            "url": {"type": "string", "description": "作品链接。抖音：https://www.douyin.com/video/<数字ID> 或 /note/<数字ID>；小红书：收藏夹里笔记卡片的完整链接，路径末尾是 24 位笔记 ID"},
            "title": {"type": "string"},
            "author": {"type": "string"},
            "cover": {"type": "string", "description": "封面图片 URL，可留空"},
        },
    },
}


def handoff_dir(data_dir):
    path = Path(data_dir) / "handoff"
    path.mkdir(parents=True, exist_ok=True)
    return path


def task_paths(data_dir, key):
    folder = handoff_dir(data_dir)
    return folder / (key + ".task.json"), folder / (key + ".result.json")


def build_task(source, known_ids, data_dir):
    task_path, result_path = task_paths(data_dir, source["key"])
    url = source["profile_url"] if source["platform"] == "douyin" else source["url"]
    platform_name = "抖音" if source["platform"] == "douyin" else "小红书"
    steps = [
        f"用你自己的浏览器工具，在用户已登录{platform_name}的浏览器里打开：{url}",
    ]
    if source["platform"] == "douyin":
        steps.append(f"在「收藏 → 收藏夹」里点开名为「{source['collection']}」的收藏夹。"
                     + (f"先确认页面上的账号昵称是「{source['account_marker']}」。" if source.get("account_marker") else ""))
    steps += [
        "从上往下读取作品卡片，每条记下 url、title、author、cover，保持页面顺序（最新收藏在前）。",
        f"向下滚动继续读取，每次滚动后停 2–3 秒。读到连续 {STOP_AFTER_KNOWN} 条 known_ids 里已有的作品，或页面到底，就停止。",
        "只读：不要点赞、收藏、关注、评论，也不要打开任何设置。",
        "如果出现登录、验证码、滑块或“操作过于频繁”，立即停止，告诉用户去浏览器里处理，不要尝试绕过。",
        f"完成后调用 MCP 工具 submit_collection_records，参数 source_key=\"{source['key']}\"、records=读到的数组；"
        f"没有 MCP 时，把 JSON 数组写入 {result_path}，再运行 python cli.py sync --only {source['key']}",
    ]
    return {
        "source_key": source["key"], "platform": source["platform"], "collection": source["collection"],
        "url": url, "account_marker": source.get("account_marker", ""),
        "steps": steps, "record_schema": RECORD_SCHEMA, "known_ids": sorted(known_ids),
        "result_path": str(result_path), "task_path": str(task_path), "created_at": now(),
    }


class HandoffDriver(Driver):
    name = "handoff"
    label = "交给你自己的 Agent 用它的浏览器去读"

    @classmethod
    def check(cls):
        return True, "任何带浏览器工具的 Agent 都可以"

    def read_collection(self, source, known_ids, status):
        data_dir = self.config["data_dir"]
        task_path, result_path = task_paths(data_dir, source["key"])
        if result_path.exists():
            records = json.loads(result_path.read_text(encoding="utf-8"))
            result_path.replace(result_path.with_name(source["key"] + ".imported-" + now()[:19].replace(":", "") + ".json"))
            if task_path.exists():
                task_path.unlink()
            return normalize_records(records, source)
        task = build_task(source, known_ids, data_dir)
        task_path.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        raise HandoffPending("已生成读取任务，等待你的 Agent 读取「" + source["collection"] + "」后提交结果。", task)
