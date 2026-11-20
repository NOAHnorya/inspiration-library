---
name: inspiration-library
description: 用户本地的审美灵感库（小红书/抖音收藏、网页、本地文件）。当用户要找设计、审美、内容或选题灵感，说“参考我收藏的…”，要同步小红书/抖音收藏夹，或要基于收藏素材做网页、海报、视频方案时使用。
---

# 灵感库

用户的审美灵感都在本地灵感库里，每条有稳定引用 ID（`@ins_…`）。仓库位置：`{{REPO}}`。

## 优先用 MCP

已接入时，`inspiration` 服务提供这些工具：`find_inspiration`、`get_inspiration`、`compare_inspiration`、`create_reference_brief`、`validate_references`、`similar_inspiration`、`list_tags`、`library_status`、`sync_collections`、`get_sync_tasks`、`submit_collection_records`、`import_url`、`import_file`。

## 没有 MCP 时用命令行

所有命令输出 JSON：

```bash
cd "{{REPO}}"
"{{PYTHON}}" cli.py find "复古未来主义 网页" --tag 高饱和 --limit 8
"{{PYTHON}}" cli.py get ins_xxx
"{{PYTHON}}" cli.py brief ins_a ins_b --goal "开发者工具落地页"
"{{PYTHON}}" cli.py validate-refs "参考 @ins_a 和 @ins_b"
"{{PYTHON}}" cli.py sync            # 同步收藏夹
"{{PYTHON}}" cli.py doctor          # 概况、可用的同步方式
```

## 工作方式

1. 用户要灵感时先检索，把 `@ins_…` 引用写进方案，交付前校验引用。
2. 需要看图：`get_inspiration` 加 `include_cover: true`，或打开结果里的本地封面路径。
3. 同步返回 `waiting_for_agent` 时：按任务 `steps` 用你自己的浏览器工具只读读取收藏夹，每条记 `url`、`title`、`author`、`cover`，保持页面顺序，读到连续 20 条已知作品就停，然后提交（`submit_collection_records`，或 `cli.py sync --submit KEY --records 文件`）。

## 必须遵守

- 只读：不点赞、不收藏、不评论、不改设置；不碰 Cookie、密码、Token。
- 遇到登录、验证码、滑块或“操作过于频繁”立即停止，请用户本人处理，不要绕过。
- 用户的收藏数据和 `sync_sources.json` 不要上传或公开。
