# 数据导入指南

本工具不会代替你登录平台、自动滚动或实时同步收藏。导入器只读取本地 JSON，并可选下载其中的公开封面 URL。请仅处理你有权访问的内容，遵守平台条款；遇到验证码或风控时停止。

## 通用 JSON

小红书与抖音都使用 JSON 数组：

```json
[
  {
    "platform": "xiaohongshu",
    "collection": "视觉灵感",
    "title": "标题",
    "author": "作者昵称",
    "url": "https://www.xiaohongshu.com/explore/0123456789abcdef01234567",
    "cover": "https://example.com/cover.jpg"
  }
]
```

字段说明：

- `platform`：导入小红书时写 `xiaohongshu`，导入抖音时写 `douyin`。
- `collection`：收藏夹名称，会作为筛选条件保留。
- `title`：标题；空值会显示为“未命名素材”。
- `author`：作者昵称，可为空字符串。
- `url`：原始作品链接，用于生成稳定 ID。
- `cover`：公开封面 URL，可为空字符串。

仓库中的 `examples/xiaohongshu.json` 和 `examples/douyin.json` 是虚构示例，不会指向真实作品。复制结构时请换成自己的合法数据，不要把私人版本提交到 Git。

## 导入命令

```bash
python cli.py import-xhs /path/to/xiaohongshu.json
python cli.py import-douyin /path/to/douyin.json
python cli.py annotate
python cli.py reindex
python cli.py health
```

默认下载封面。只导入文字元数据：

```bash
python cli.py import-douyin /path/to/douyin.json --no-download
```

`ready` 表示条目可用；`needs_review` 通常表示封面缺失或下载失败；`failed` 表示该条未导入，返回 JSON 中会包含原因。

## 稳定 ID 与重复导入

- 小红书 ID：`ins_xhs_` + 笔记 ID。
- 抖音 ID：`ins_douyin_` + 作品 ID。
- 网页和本地文件根据规范化 URL 或文件内容哈希生成 ID。

再次导入同一作品会更新标题、作者、链接、收藏夹和封面信息，不会清空已有备注、人工标注或标签。新增内容后需要重新运行 `annotate` 和 `reindex`。

## 可选：转换抖音 AX 快照

`extract_douyin_ax.py` 是一个**离线文本转换器**，适用于已经保存到本地的 ego lite / 浏览器无障碍树（AX）文本快照。它不控制浏览器、不读取 Cookie、不处理账号密码，也不保证适配平台未来的页面结构。

1. 在浏览器中只读打开你有权访问的收藏夹。
2. 将 AX 文本快照保存到项目内的 `private/` 目录，例如 `private/page-01.txt`。该目录已被 Git 忽略。
3. 合并多个快照并按作品 ID 去重：

```bash
python extract_douyin_ax.py private/page-01.txt private/page-02.txt \
  --collection "我的收藏夹" \
  --output private/douyin.json
```

4. 检查输出中的标题、作者、链接、封面和实际条数，再导入：

```bash
python cli.py import-douyin private/douyin.json
```

若你明确知道收藏夹应有条数，可增加 `--expected 100`。数量不一致时转换器会拒绝写结果，避免把不完整提取误认为完成。页面标称数量与可读作品数量可能不同，不应虚构补齐。

## 公开网页与本地文件

```bash
python cli.py import-url https://example.com
python cli.py import-file /path/to/local-image.png
```

网页读取仅提取标题、作者、描述和封面等公开元数据。图片文件会作为封面保存；其他文件作为附件保存。文件来源路径和导入记录都属于私人数据，仅保存在本地数据库中。

## 发布前检查

收藏 JSON、AX 快照、数据库、封面和备份可能包含账号、昵称、路径或私人偏好。请把它们放在 `private/`、`data/` 或 `backups/`，不要复制到 `examples/`。发布前运行：

```bash
git status --short
```

只应看到你明确准备公开的文件。
