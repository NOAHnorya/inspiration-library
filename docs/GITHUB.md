# GitHub 发布指南

请从**干净的发布副本**上传，不要直接选择存放私人收藏的工作目录。发布包中不应包含 `data/`、`backups/`、`private/`、真实收藏 JSON 或任何浏览器快照。

## 发布前检查

在项目根目录运行：

```bash
python -m pip install -r requirements.txt
python cli.py import-file examples/y2k-poster.png
python cli.py import-file examples/minimal-poster.png
python cli.py annotate
python cli.py reindex
python cli.py find "Y2K 海报"
python cli.py health
```

再启动 `python server.py`，确认 http://127.0.0.1:8765 可以搜索和打开示例。验证产生的 `data/` 不要上传。

隐私检查：

```bash
git status --short
```

确认列表只有程序、文档、示例和许可证。不要上传 Cookie、Token、密码、账号导出、真实收藏或私人备份。

## 方法一：GitHub 网页上传（新手）

1. 登录 GitHub，选择 **New repository**。
2. Repository name 填 `inspiration-library`，选择 **Public**。
3. 为避免与本地历史冲突，不要同时生成 README、`.gitignore` 或 License；项目已经包含这些文件。
4. 创建后选择 **uploading an existing file**，上传干净发布副本中的文件和目录。
5. 确认没有 `data/`、`backups/`、私人 JSON 或 `.venv/`，再提交。
6. 打开仓库首页，按 README 的“5 分钟跑起来”从克隆到示例检索复查一遍。

GitHub 网页可能限制一次上传的文件数量；如果无法保留目录结构，使用下面的命令行方式。

## 方法二：Git + GitHub CLI

先安装并登录 [GitHub CLI](https://cli.github.com/)，在干净发布副本中执行：

```bash
git init
git add .
git status --short
git commit -m "Initial release"
gh repo create inspiration-library --public --source=. --remote=origin --push
```

`gh repo create` 会实际创建公开仓库。执行前再次检查 `git status --short`，并将描述、主页等信息按需补充：

```bash
gh repo edit --description "本地优先的灵感素材管理、标签检索与 Agent 引用工具" --homepage "https://github.com/YOUR_USERNAME/inspiration-library"
```

## 发布后建议

- 在 GitHub 仓库设置中确认 Topics，例如 `inspiration`、`knowledge-base`、`sqlite`、`fastapi`、`local-first`。
- 用 Releases 发布源代码压缩包，并在说明中写清已验证的 Python 版本。
- 不要把你的私人灵感库作为“示例数据”随仓库发布。
- 若曾误提交敏感内容，不要只删除最新文件；立即停止公开分享，并按 GitHub 的敏感数据移除流程处理历史和已泄露凭据。
