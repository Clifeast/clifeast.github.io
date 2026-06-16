# clifeast.github.io

这是赏鹤阳的个人博客与写作展示站点源码。站点使用原生 HTML、CSS 与少量 JavaScript 构建，并托管在 GitHub Pages 上。

## 功能亮点

- 首页展示个人介绍、最新文章与联系方式。
- 文章列表页位于 `/articles/`，基于 `data/articles.json` 动态渲染。
- 文章正文由 `content/articles/` 中的源文件生成，避免手动重复维护标题、日期和摘要。
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
│   └── articles.json           # 生成后的文章元数据
├── assets/
│   ├── images/                 # 站点图像资源
│   ├── scripts/                # 公共布局与文章列表渲染脚本
│   ├── source/                 # 设计源文件
│   └── styles/                 # 全局、首页、列表页与正文页样式
├── tools/
│   └── build-articles.js       # 文章生成脚本
└── subpages/
    └── articlelist.html        # 旧文章列表地址的兼容跳转页
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
