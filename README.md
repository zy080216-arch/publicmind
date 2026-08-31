# PublicMind

PublicMind 是一个本地人物知识档案生成器。输入一个人名和可选的身份线索，它会先寻找一个最可能对应的关键主页供用户确认身份。确认后才读取公开主页、访谈、报道与评论，并用 DeepSeek 整理“这个人做过什么、发表过哪些主要观点”。完整档案直接显示在网页中，Obsidian Vault 是可选下载。

## 使用流程

```text
首次配置 Brave Search + DeepSeek API Key
  → 输入人物姓名、身份线索和档案语言
  → 打开系统推荐的关键主页，确认是不是这个人
  → 可选：手动补充主页、文章、访谈或视频网址
  → 点击“确认是他，开始整理”
  → 自动检索、读取、归并与写作
  → 直接在网页阅读含人物影像的完整档案
  → 可继续就档案内容向 DeepSeek 提问
  → 可选：下载 Vault.zip，用 Obsidian 打开
```

最终 Vault 的阅读结构为：

```text
人物知识库/
├── 00 人物全景.md
├── 01 生平与经历.md
├── 02 做过的事情.md
├── 03 核心观点.md
├── 04 观点演变.md
├── 05 外部评价.md
├── 06 时间线.md
├── 公开信息源.md
├── 观点/
└── 来源/
```

网页和 `00 人物全景.md` 都把“公开主页与信息源”作为最前面的独立板块，统一列出 X、GitHub、YouTube、官网/技术博客以及本次实际收录的网址，不再把来源链接零散附在每条观点下面。每篇来源笔记仍保留标题、作者、日期、抓取时间、原始 URL、正文和内容指纹。

档案会在信息源板块之后展示最多 4 张人物图片：先读取 Wikipedia 主图，再从 Wikimedia Commons 补充公开图片。图片保留原始页面、作者和许可信息；不依赖 Google 图片缩略图，也不直接盗链需要登录的社交平台。人物影像同时写入 `00 人物全景.md`，在 Obsidian 联网时可以显示。

网页中的“继续问这个人”会调用一次 DeepSeek，并只向模型提供该人物已保存的结构化档案与最相关原始资料片段。例如可以询问“Sam Altman 如何看待 Codex”。回答附少量原文入口；若现有知识库没有相关材料，会明确说明资料不足，不使用模型自身记忆补写。每次问询都会产生一次 DeepSeek API 调用。

语言提供三种选择：

- `中文导读`（默认）：人物概览、经历、观点、时间线和关键评价使用简体中文，来源长文保留原文。
- `English`：结构化人物档案使用英文，来源正文保持原文。
- `中英双语`：结构化档案字段同时生成中文和英文，来源正文仍不做全文翻译。

三种模式都只调用一次结构化报告生成，不为每篇长文追加全文翻译调用，以控制 DeepSeek token 消耗。

系统内部仍保留身份匹配、来源角色区分和原文证据，但不会把置信度、审核类型或抓取术语丢给最终读者。本人主张、媒体描述和第三方评价会在写作阶段分开。

每次新建人物时还会通过 Wikipedia 官方只读 API 查询基础身份与生平条目。Wikipedia 的拼写建议会用于处理近似姓名，例如 `rafa nadel → rafa nadal → rafael nadal`。百科基线不会因为普通搜索排序较低而被淘汰；它会强制进入正式材料，并在没有更明确官方主页时优先用于身份确认。Wikipedia 暂时不可用时，Brave 的其他检索仍可继续。

## API Key

网页右上角的“API 设置”可以完成一次性配置。密钥保存在本机数据库旁的 `data/settings.json`，权限会尽量设为仅当前用户可读写；接口只返回“是否已配置”，永远不会把密钥返回给前端。不要把真实 Key 粘贴进聊天、README 或 Git。

### 1. Brave Search

在 [Brave Search API Keys](https://api-dashboard.search.brave.com/app/keys) 创建 Key。

截至 2026-08-31，Brave 官方价格页显示 Search 套餐为 5 美元 / 1000 次请求，并每月自动赠送 5 美元额度。因此按现行价格，每月前约 1000 次搜索相当于免费，超出后按量计费；它不是无限免费的 API。套餐和开户要求以后可能变化，请以 [Brave 官方价格页](https://api-dashboard.search.brave.com/app/plans) 为准。

### 2. DeepSeek

在 [DeepSeek API Keys](https://platform.deepseek.com/api_keys) 创建 Key。PublicMind 已固定为 DeepSeek 的 OpenAI 兼容格式：

```text
Base URL: https://api.deepseek.com
Endpoint: /chat/completions
Default model: deepseek-v4-flash
```

当前模型名来自 2026-08-31 的 [DeepSeek 官方模型与价格文档](https://api-docs.deepseek.com/quick_start/pricing)。未来若官方再次更新模型，可以通过 `PUBLICMIND_LLM_MODEL` 覆盖默认值。

无界面运行时也可以使用环境变量：

```bash
export BRAVE_SEARCH_API_KEY="在本机填写"
export DEEPSEEK_API_KEY="在本机填写"
export PUBLICMIND_LLM_MODEL="deepseek-v4-flash"
```

## 启动

项目当前兼容这台 Mac 的 Python 3.9，也支持更高版本。

```bash
git clone https://github.com/zy080216-arch/publicmind.git
cd PublicMind
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e '.[youtube]'
uvicorn app.backend.api:create_app --factory --host 127.0.0.1 --port 8000
```

打开 `http://127.0.0.1:8000`。网页和 API 同源，不需要 Node.js，不需要 Safari 插件，也不会尝试在网页里直接跨站爬取；真正的检索与网页读取由本机 FastAPI 服务完成。

运行验收：

```bash
python3 -m unittest discover -v
node --check app/frontend/app.js
python3 -m pip check
```

测试使用假搜索、假网页和假 LLM，不消耗真实 API 额度。完整测试覆盖：检索角色分离、Wikipedia 身份纠错、Wikimedia 图片与许可解析、人物知识库问询、网页/YouTube 接口、幂等抓取、不可变原文证据、模型虚构 URL 过滤、一键任务、中文 Vault 与 Obsidian 内链。

## 分享与本地数据

PublicMind 以 MIT License 开源。你可以复制、修改和分发代码；每位使用者应在自己的电脑运行服务，并使用自己的 Brave Search 与 DeepSeek API Key。

以下内容只保存在本机，不会进入 Git：

- `data/settings.json`：本机 API Key。
- `data/*.db`：人物、来源和报告数据库。
- `data/raw/`、`data/processed/`：抓取和处理后的资料。
- `data/exports/`：导出的 Obsidian Vault。

不要把真实 API Key 写进 README、Issue、提交记录或截图。详细安全边界见 [SECURITY.md](SECURITY.md)。当前版本是单用户本地应用，不应直接暴露到公网。

## 边界

- 只处理无需绕过访问控制的公开资料，不绕过登录、付费墙、验证码或 robots 限制。
- 单个网页读取失败不会中断整个建库流程；只要仍有可用资料，就会继续生成。
- 模型只能使用实际抓取到的文档，输出中的来源 URL 还会经过白名单校验。
- 当前默认最多选择 12 个来源、向模型提供最多 18 篇文档，以控制时间和 API 成本。
- 同名歧义较大时，应在“身份线索”中加入机构、领域、用户名或代表作品。
