"""`python cli.py init` — first-run setup, interactive or driven by flags.

Agents can run it non-interactively, for example:
    python cli.py init --agent codex --xhs "https://www.xiaohongshu.com/board/<id>" --xhs-name 设计灵感 --yes
"""
import json
from pathlib import Path
import re
import sys

import agent_setup
from core import Library, ROOT
from drivers import detect as detect_drivers, resolve_driver_name

XHS_BOARD = re.compile(r"https://www\.xiaohongshu\.com/board/([0-9a-f]{24})")
DOUYIN_FAVORITES = "https://www.douyin.com/user/self?from_tab_name=main&showSubTab=favorite_folder&showTab=favorite_collection"


def say(text=""):
    print(text, file=sys.stderr if not sys.stdin.isatty() else sys.stdout)


def ask(question, default=""):
    suffix = f"（回车 = {default}）" if default else ""
    answer = input(f"{question}{suffix}：").strip()
    return answer or default


def choose(question, options, default_index=0):
    for index, (_, label) in enumerate(options, 1):
        say(f"  {index}. {label}")
    while True:
        answer = ask(question, str(default_index + 1))
        if answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1][0]
        say("请输入列表里的数字。")


def yes(question, default=True):
    answer = ask(question + (" [Y/n]" if default else " [y/N]")).lower()
    return default if not answer else answer in ("y", "yes", "是", "好")


def load_config(path):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"driver": "auto", "browser_app": "com.citrolabs.ego.lite", "sources": []}


def next_key(config, prefix):
    used = {source["key"] for source in config["sources"]}
    number = 1
    while f"{prefix}_{number}" in used:
        number += 1
    return f"{prefix}_{number}"


def add_xhs(config, url, name):
    match = XHS_BOARD.search(url or "")
    if not match:
        raise ValueError("小红书收藏夹链接应形如 https://www.xiaohongshu.com/board/<24位ID>（在网页版“收藏 → 专辑”里打开后复制）")
    if any(match.group(1) in source.get("url", "") for source in config["sources"]):
        return None
    key = next_key(config, "xhs")
    source = {"key": key, "platform": "xiaohongshu", "collection": name or "小红书收藏",
              "url": f"https://www.xiaohongshu.com/board/{match.group(1)}?source=web_profile_page",
              "file": f"private/{key}.json"}
    config["sources"].append(source)
    return source


def add_douyin(config, name, account=""):
    if not name:
        raise ValueError("请填写抖音收藏夹名称（和抖音网页版“收藏 → 收藏夹”里显示的一致）")
    if any(source["platform"] == "douyin" and source["collection"] == name for source in config["sources"]):
        return None
    key = next_key(config, "douyin")
    source = {"key": key, "platform": "douyin", "collection": name, "profile_url": DOUYIN_FAVORITES,
              "file": f"private/{key}.json"}
    if account:
        source["account_marker"] = account
    config["sources"].append(source)
    return source


def write_config(path, config):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def doctor(data_dir=None, config_path=None):
    library = Library(data_dir)
    from maintenance import Maintenance
    from tagging import Catalog
    from sync_config import load_sync_config, resolve_config_path
    try:
        config = load_sync_config(config_path)
        sources = [{key: source.get(key) for key in ("key", "platform", "collection", "driver")}
                   for source in config["sources"]]
        config_error = None
    except (ValueError, OSError) as exc:
        sources, config_error = [], str(exc)
    return {"repo": str(ROOT), "python": sys.executable, "data_dir": str(library.data_dir),
            "sync_config": str(resolve_config_path(config_path)), "config_error": config_error,
            "sources": sources, "stats": library.stats(),
            "health_ok": Maintenance(library, Catalog(library)).health_check()["ok"],
            "drivers": detect_drivers(), "auto_driver": resolve_driver_name("auto"),
            "agents": agent_setup.detect_agents()}


def run_init(args, data_dir=None):
    interactive = sys.stdin.isatty() and not args.yes
    library = Library(data_dir)
    config_path = Path(args.config).expanduser().resolve() if args.config else ROOT / "sync_sources.json"
    say("\n灵感库初始化：接入你的 Agent，并配置要同步的收藏夹。\n")

    # 1. Which agent?
    detected = agent_setup.detect_agents()
    agent_id = args.agent
    if not agent_id:
        if not interactive:
            raise ValueError("非交互模式需要 --agent，可选：" + "、".join(agent_setup.AGENT_IDS))
        options = [(agent["id"], agent["label"] + ("（已检测到）" if agent["detected"] else "")) for agent in detected]
        first = next((index for index, agent in enumerate(detected) if agent["detected"]), len(options) - 1)
        say("1/4 你平时用哪个 Agent？")
        agent_id = choose("选择", options, first)
    if agent_id not in agent_setup.AGENT_IDS:
        raise ValueError("未知的 Agent：" + agent_id)

    # 2. Which "hands" can sync collections?
    drivers = detect_drivers()
    recommended = resolve_driver_name("auto")
    driver = args.driver or "auto"
    say("\n2/4 同步收藏夹的方式（自动选第一个可用的）：")
    for item in drivers:
        mark = "✓" if item["available"] else "–"
        say(f"  {mark} {item['label']}" + ("" if item["available"] else f"：{item['detail']}"))
    say(f"  → 将使用：{recommended}" + ("（你的 Agent 会按任务去浏览器里读）" if recommended == "handoff" else ""))
    if recommended == "handoff" and interactive:
        say("  想更省事：安装 ego lite（https://lite.ego.app/），它自带给 Agent 用的浏览器接口。")

    # 3. Collections
    config = load_config(config_path)
    config["driver"] = driver
    added = []
    for url, name in zip(args.xhs or [], (args.xhs_name or []) + [""] * len(args.xhs or [])):
        source = add_xhs(config, url, name)
        if source:
            added.append(source)
    for name in args.douyin or []:
        source = add_douyin(config, name, args.douyin_account or "")
        if source:
            added.append(source)
    if interactive:
        say("\n3/4 添加要同步的收藏夹" + (f"（已有 {len(config['sources'])} 个）" if config["sources"] else ""))
        while True:
            kind = choose("添加哪种", [("xhs", "小红书收藏专辑"), ("douyin", "抖音收藏夹"), ("done", "不添加了 / 以后再说")],
                          2 if config["sources"] else 0)
            try:
                if kind == "xhs":
                    source = add_xhs(config, ask("粘贴小红书专辑链接"), ask("给它起个名字", "小红书收藏"))
                elif kind == "douyin":
                    source = add_douyin(config, ask("抖音收藏夹名称"), ask("你的抖音昵称（用于核对账号，可留空）"))
                else:
                    break
                if source:
                    added.append(source)
                    say(f"  已添加：{source['collection']}")
            except ValueError as exc:
                say("  " + str(exc))
    if config["sources"]:
        write_config(config_path, config)

    # 4. Connect the agent
    say("\n4/4 接入 " + next(agent["label"] for agent in detected if agent["id"] == agent_id))
    changes, manual = agent_setup.plan(agent_id, library.data_dir, config_path)

    def confirm(change):
        if not interactive:
            return True
        say("\n" + change.summary)
        if change.path and change.path.exists():
            say("  （会先备份原文件）")
        return yes("  确认", True)

    applied = agent_setup.apply_changes(changes, confirm)
    if manual:
        say("\n" + manual)
    result = {"ok": all("error" not in item for item in applied), "agent": agent_id, "driver": driver,
              "auto_driver": recommended, "config": str(config_path) if config["sources"] else None,
              "added_sources": [source["key"] for source in added], "changes": applied, "manual": manual or None,
              "next": agent_setup.try_prompt(agent_id)}
    if args.sync and config["sources"]:
        from sync_collections import run as run_sync
        say("\n开始第一次同步（只读）…")
        result["sync"] = run_sync(None, str(config_path))
    say("\n完成。" + result["next"])
    return result
