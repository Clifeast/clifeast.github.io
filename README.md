# clifeast.github.io

这是赏鹤阳的个人博客与写作展示站点源码。站点使用原生 HTML、CSS 与少量 JavaScript 构建，并托管在 GitHub Pages 上。

## 功能亮点

- 首页展示个人介绍、最新文章与联系方式。
- 文章列表页位于 `/articles/`，基于 `data/articles.json` 动态渲染。
- 文章正文由 `content/articles/` 中的源文件生成，避免手动重复维护标题、日期和摘要。
- 论文日报位于 `/digest/`，基于 `data/digest/today.json` 动态渲染。
- 公共头部、页脚与文章卡片渲染逻辑集中在 `assets/scripts/` 中。
- 采用响应式设计，在桌面端与移动端均能获得良好浏览体验。

## 项目结构

```text
├── index.html                  # 首页
├── articles/
│   ├── index.html              # 文章列表页
│   └── *.html                  # 生成后的文章正文页
├── content/
│   └── articles/               # 文章源文件，包含 frontmatter 与正文 HTML 片段
├── data/
│   ├── articles.json           # 生成后的文章元数据
│   └── digest/                 # 生成后的论文日报 JSON
├── digest/
│   └── index.html              # 论文日报页面入口
├── assets/
│   ├── images/                 # 站点图像资源
│   ├── scripts/                # 公共布局、文章列表与论文日报渲染脚本
│   ├── source/                 # 设计源文件
│   └── styles/                 # 全局、首页、列表页、正文页与日报样式
├── tools/
│   ├── build-articles.js       # 文章生成脚本
│   └── build-digest.py         # 论文日报生成脚本
```

## 本地预览

首次拉取项目后安装依赖：

```bash
npm install
npx playwright install chromium
```

由于首页和文章列表页会通过 `fetch()` 读取 JSON，建议使用静态服务器预览：

```bash
python3 -m http.server 8000
```

随后访问 <http://localhost:8000> 即可查看站点。

## 更新文章

1. 在 `content/articles/` 中新增或修改文章源文件。
2. 在文件顶部填写 frontmatter：

```text
---
title: 文章标题
date: 展示给读者的日期
publishedAt: 2026-06-16
slug: article-slug
description: 可选摘要
meta: 可选正文页日期说明
---
```

3. 在 frontmatter 下方编写正文 HTML 片段。
4. 运行生成命令：

```bash
node tools/build-articles.js
```

脚本会更新 `articles/*.html` 和 `data/articles.json`。提交这些生成结果后，GitHub Pages 即可直接发布。

## 更新论文日报

日报的栏目配置位于 `content/digest/sections.json`。生成脚本按一个很薄的状态化 pipeline 运行：

- `recent-agt` / `recent-ai`：只抓 digest 日期前一天的 arXiv 新论文；每天确定性随机选一个 arXiv 类别，候选太多时确定性抽样，再批量交给 LLM 粗排，最终入选论文才临时下载 PDF 做中文精读介绍。
- `classic-ai`：优先从 OpenAlex 高影响论文里选第一个未推送条目，失败时使用 curated list；推送过的 identity 记录在 `data/digest/state.json`。
- `conference-agt`：每天按权重确定性随机选一个 venue，用 `state.json` 中的 cursor 顺次推进；EC/WINE 直接轮换，TCS/AI 会议先由 LLM 判断是否 AGT/EconCS，再按阈值采纳。

脚本会写入 `data/digest/YYYY-MM-DD.json` 和 `data/digest/today.json`，并额外写入 `data/digest/debug/run-YYYY-MM-DD.json` 便于排查。业务状态只保留在 `data/digest/state.json`；没有长期 HTTP cache、PDF cache 或 LLM cache。生成当天日报：

```bash
npm run build:digest
```

也可以指定日期生成归档：

```bash
npm run build:digest -- --date 2026-06-16
```

脚本会更新 `data/digest/today.json` 和对应日期的 `data/digest/YYYY-MM-DD.json`。

如果某日期已经在 `state.json` 标记为 completed，默认会复用已有 JSON，不会再次推进 state；需要重跑并推进 cursor/seenIds 时加 `--force`。如需离线 smoke test，可加 `--no-network --dry-run`。

真实 LLM 评分默认使用阿里云百炼 Qwen OpenAI-compatible Chat API。没有 API key 时会自动使用 Mock fallback。粗排默认 `qwen-plus`，只发送标题和摘要；精读默认 `qwen-long`，仅对最终入选 arXiv 论文下载 PDF、上传到 Qwen file interface 后读取：

```bash
export DASHSCOPE_API_KEY="..."
export QWEN_SCORE_MODEL="qwen-plus"        # 可改为 qwen-flash
export QWEN_ENRICH_MODEL="qwen-long"       # 可按需改为 qwen-doc-turbo
export QWEN_API_BASE="https://dashscope.aliyuncs.com/compatible-mode/v1"
```

兼容入口：

```bash
python3 scripts/build_digest.py --date 2026-06-16
python3 scripts/build_digest.py --date 2026-06-16 --force
python3 scripts/build_digest.py --date 2026-06-16 --no-network --dry-run
```

## 校验

可以用以下命令确认文章生成结果没有过期：

```bash
npm run build:articles -- --check
```

启动本地静态服务器后，可以运行 Playwright 渲染检查：

```bash
npm run verify:site
```

该命令会打开首页、文章列表页和两篇正文页，检查文章卡片、图片加载、控制台错误和资源请求，并把截图保存到 `/private/tmp/clifeast-playwright`。
