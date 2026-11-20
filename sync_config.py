import json
import os
from pathlib import Path
import re

from core import ROOT

DEFAULT_CONFIG = ROOT / "sync_sources.json"
DRIVER_CHOICES = {"auto", "ego-browser", "kimicu", "handoff"}


def resolve_config_path(path=None):
    value = path or os.environ.get("INSPIRATION_SYNC_CONFIG") or DEFAULT_CONFIG
    return Path(value).expanduser().resolve()


def load_sync_config(path=None):
    config_path = resolve_config_path(path)
    if not config_path.is_file():
        raise ValueError("尚未配置收藏夹。运行 python cli.py init，或复制 sync_sources.example.json 为 sync_sources.json 后修改。")
    config = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(config, dict) or not isinstance(config.get("sources"), list):
        raise ValueError("同步配置必须包含 sources 数组")
    default_driver = config.get("driver", "auto")
    if default_driver not in DRIVER_CHOICES:
        raise ValueError("driver 只能是 " + "、".join(sorted(DRIVER_CHOICES)) + ": " + str(default_driver))
    sources = []
    keys = set()
    for source in config["sources"]:
        key = source.get("key", "")
        platform = source.get("platform", "")
        collection = source.get("collection", "").strip()
        filename = source.get("file", "").strip()
        driver = source.get("driver", default_driver)
        if not re.fullmatch(r"[a-z][a-z0-9_]{1,60}", key) or key in keys:
            raise ValueError("收藏夹 key 必须唯一，并使用小写字母、数字和下划线: " + key)
        if platform not in {"douyin", "xiaohongshu"}:
            raise ValueError("支持的平台为 douyin 和 xiaohongshu: " + key)
        if not collection or not filename:
            raise ValueError("收藏夹必须填写 collection 和 file: " + key)
        if driver not in DRIVER_CHOICES:
            raise ValueError("收藏夹的 driver 只能是 " + "、".join(sorted(DRIVER_CHOICES)) + ": " + key)
        if platform == "xiaohongshu" and not source.get("url", "").startswith("https://www.xiaohongshu.com/board/"):
            raise ValueError("小红书收藏夹需要有效的 board URL: " + key)
        if platform == "douyin" and not source.get("profile_url", "").startswith("https://www.douyin.com/user/"):
            raise ValueError("抖音收藏夹需要有效的用户收藏页 URL: " + key)
        normalized = dict(source)
        normalized.update(key=key, platform=platform, collection=collection, file=filename, driver=driver)
        sources.append(normalized)
        keys.add(key)
    return {"browser_app": config.get("browser_app", "com.citrolabs.ego.lite"), "driver": default_driver,
            "sources": sources, "config_path": str(config_path), "config_dir": str(config_path.parent)}


def public_sources(config):
    return [{"key": source["key"], "platform": source["platform"], "collection": source["collection"],
             "driver": source["driver"]} for source in config["sources"]]
