import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from agent_setup import AGENT_IDS
from core import Library, ROOT
from wizard import doctor, run_init
from tagging import Catalog
from agent_tools import AgentTools
from maintenance import Maintenance


def emit(value):
    print(json.dumps(value, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(prog="inspiration")
    parser.add_argument("--data-dir")
    commands = parser.add_subparsers(dest="command", required=True)

    xhs = commands.add_parser("import-xhs")
    xhs.add_argument("path")
    xhs.add_argument("--no-download", action="store_true")
    douyin = commands.add_parser("import-douyin")
    douyin.add_argument("path")
    douyin.add_argument("--no-download", action="store_true")
    url = commands.add_parser("import-url")
    url.add_argument("url")
    url.add_argument("--no-download", action="store_true")
    file = commands.add_parser("import-file")
    file.add_argument("path")
    commands.add_parser("stats")
    commands.add_parser("verify-baseline")

    get = commands.add_parser("get")
    get.add_argument("id")
    listing = commands.add_parser("list")
    listing.add_argument("--limit", type=int, default=100)
    listing.add_argument("--offset", type=int, default=0)
    imports = commands.add_parser("imports")
    imports.add_argument("--limit", type=int, default=100)

    annotate = commands.add_parser("annotate")
    annotate.add_argument("--id")
    annotate.add_argument("--regenerate", action="store_true")
    search = commands.add_parser("search")
    search.add_argument("q", nargs="?", default="")
    search.add_argument("--tag", action="append", default=[])
    search.add_argument("--match", choices=["all", "any"], default="all")
    search.add_argument("--exclude", action="append", default=[])
    search.add_argument("--platform", default="")
    search.add_argument("--collection", default="")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--offset", type=int, default=0)
    search.add_argument("--no-semantic", action="store_true")
    search.add_argument("--min-score", type=float, default=0.16)
    search.add_argument("--sort", choices=["relevance", "collection_asc", "collection_desc"], default="collection_asc")
    tags = commands.add_parser("tags")
    tags.add_argument("--query", default="")
    update = commands.add_parser("update")
    update.add_argument("id")
    update.add_argument("--notes")
    update.add_argument("--annotation")
    update.add_argument("--add-tag", action="append", default=[])
    update.add_argument("--remove-tag", action="append", default=[])
    update.add_argument("--lock-tag", action="append", default=[])
    update.add_argument("--unlock-tag", action="append", default=[])
    merge = commands.add_parser("merge-tags")
    merge.add_argument("source")
    merge.add_argument("target")
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("--benchmark", default=str(ROOT / "data" / "retrieval_benchmark.json"))
    find = commands.add_parser("find")
    find.add_argument("q", nargs="?", default="")
    find.add_argument("--tag", action="append", default=[])
    find.add_argument("--match", choices=["all", "any"], default="all")
    find.add_argument("--exclude", action="append", default=[])
    find.add_argument("--platform", default="")
    find.add_argument("--collection", default="")
    find.add_argument("--limit", type=int, default=5)
    find.add_argument("--no-semantic", action="store_true")
    compare = commands.add_parser("compare")
    compare.add_argument("ids", nargs="+")
    brief = commands.add_parser("brief")
    brief.add_argument("ids", nargs="+")
    brief.add_argument("--goal", default="")
    validate = commands.add_parser("validate-refs")
    validate.add_argument("text")
    similar = commands.add_parser("similar")
    similar.add_argument("id")
    similar.add_argument("--tag", action="append", default=[])
    similar.add_argument("--match", choices=["all", "any"], default="all")
    similar.add_argument("--exclude", action="append", default=[])
    similar.add_argument("--platform", default="")
    similar.add_argument("--collection", default="")
    similar.add_argument("--limit", type=int, default=10)
    commands.add_parser("health")
    commands.add_parser("reindex")
    backup = commands.add_parser("backup")
    backup.add_argument("--output")
    restore = commands.add_parser("restore")
    restore.add_argument("archive")
    restore.add_argument("target_dir")

    init_cmd = commands.add_parser("init", help="首次设置：接入你的 Agent、配置收藏夹")
    init_cmd.add_argument("--agent", choices=AGENT_IDS)
    init_cmd.add_argument("--driver", choices=["auto", "ego-browser", "kimicu", "handoff"])
    init_cmd.add_argument("--xhs", action="append", help="小红书收藏专辑链接，可重复")
    init_cmd.add_argument("--xhs-name", action="append", help="与 --xhs 一一对应的名字")
    init_cmd.add_argument("--douyin", action="append", help="抖音收藏夹名称，可重复")
    init_cmd.add_argument("--douyin-account", help="抖音昵称，用于核对账号")
    init_cmd.add_argument("--config", help="sync_sources.json 位置，默认在仓库根目录")
    init_cmd.add_argument("--sync", action="store_true", help="配置完立即同步一次")
    init_cmd.add_argument("--yes", action="store_true", help="不逐项确认（供 Agent 调用）")
    doctor_cmd = commands.add_parser("doctor", help="检查环境：数据、收藏夹、可用的同步方式和 Agent")
    doctor_cmd.add_argument("--config")
    sync_cmd = commands.add_parser("sync", help="只读增量同步收藏夹")
    sync_cmd.add_argument("--only", action="append")
    sync_cmd.add_argument("--driver", choices=["auto", "ego-browser", "kimicu", "handoff"])
    sync_cmd.add_argument("--config")
    sync_cmd.add_argument("--submit", metavar="KEY", help="导入 Agent 读取的结果")
    sync_cmd.add_argument("--records", metavar="PATH")

    args = parser.parse_args()
    if args.data_dir:
        os.environ["INSPIRATION_DATA_DIR"] = str(Path(args.data_dir).expanduser().resolve())
    if args.command == "init":
        emit(run_init(args, args.data_dir))
        return
    if args.command == "doctor":
        emit(doctor(args.data_dir, args.config))
        return
    if args.command == "sync":
        import sync_collections
        if args.submit:
            if not args.records:
                raise ValueError("--submit 需要 --records 文件")
            records = json.loads(Path(args.records).read_text(encoding="utf-8"))
            emit(sync_collections.submit(args.submit, records, args.config))
        else:
            emit(sync_collections.run(args.only, args.config, args.driver))
        return
    library = Library(args.data_dir)
    catalog = Catalog(library)
    agent = AgentTools(catalog)
    maintenance = Maintenance(library, catalog)

    if args.command == "import-xhs":
        results = library.import_xhs(args.path, not args.no_download)
        emit({"ok": all(r["status"] != "failed" for r in results), "count": len(results),
              "ready": sum(r["status"] == "ready" for r in results),
              "needs_review": sum(r["status"] == "needs_review" for r in results),
              "failed": sum(r["status"] == "failed" for r in results), "results": results})
    elif args.command == "import-douyin":
        results = library.import_douyin(args.path, not args.no_download)
        emit({"ok": all(r["status"] != "failed" for r in results), "count": len(results),
              "ready": sum(r["status"] == "ready" for r in results),
              "needs_review": sum(r["status"] == "needs_review" for r in results),
              "failed": sum(r["status"] == "failed" for r in results), "results": results})
    elif args.command == "import-url":
        emit(library.import_url(args.url, not args.no_download))
    elif args.command == "import-file":
        emit(library.import_file(args.path))
    elif args.command == "stats":
        emit(library.stats())
    elif args.command == "verify-baseline":
        baseline_path = ROOT / "data" / "baseline.json"
        baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        sources = [baseline] + baseline.get("additional_sources", [])
        checks = []
        for entry in sources:
            source = ROOT / entry["source"]
            digest = hashlib.sha256(source.read_bytes()).hexdigest()
            checks.append({"source": str(source), "ok": digest == entry["sha256"],
                           "expected_sha256": entry["sha256"], "actual_sha256": digest})
        emit({"ok": all(check["ok"] for check in checks), "sources": checks})
    elif args.command == "get":
        item = library.get_item(args.id)
        if not item:
            raise KeyError("素材不存在: " + args.id)
        emit(item)
    elif args.command == "list":
        emit(library.list_items(args.limit, args.offset))
    elif args.command == "imports":
        emit(library.list_imports(args.limit))
    elif args.command == "annotate":
        if args.id:
            emit(catalog.auto_annotate(args.id, args.regenerate))
        else:
            items = catalog.annotate_all(args.regenerate)
            emit({"ok": True, "count": len(items), "provider": "local_rules_visual_v1"})
    elif args.command == "search":
        emit(catalog.search(args.q, args.tag, args.match, args.exclude, args.platform,
                            args.collection, args.limit, args.offset, not args.no_semantic, args.min_score, args.sort))
    elif args.command == "tags":
        emit(catalog.list_tags(args.query))
    elif args.command == "update":
        patch = json.loads(args.annotation) if args.annotation else None
        emit(catalog.update_item(args.id, args.notes, patch, args.add_tag, args.remove_tag,
                                 args.lock_tag, args.unlock_tag))
    elif args.command == "merge-tags":
        emit({"ok": True, "name": catalog.merge_tags(args.source, args.target)})
    elif args.command == "evaluate":
        emit(catalog.evaluate(args.benchmark))
    elif args.command == "find":
        emit(agent.find_inspiration(args.q, args.tag, args.match, args.exclude, args.platform,
                                    args.collection, args.limit, not args.no_semantic))
    elif args.command == "compare":
        emit(agent.compare_inspiration(args.ids))
    elif args.command == "brief":
        emit(agent.create_reference_brief(args.ids, args.goal))
    elif args.command == "validate-refs":
        emit(agent.validate_references(args.text))
    elif args.command == "similar":
        emit(maintenance.visual_search(args.id, args.tag, args.match, args.exclude,
                                       args.platform, args.collection, args.limit))
    elif args.command == "health":
        emit(maintenance.health_check())
    elif args.command == "reindex":
        emit(maintenance.reindex_all())
    elif args.command == "backup":
        emit(maintenance.backup(args.output))
    elif args.command == "restore":
        emit(maintenance.restore(args.archive, args.target_dir))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)
