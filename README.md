# clifeast.github.io

这是赏鹤阳的个人博客与写作展示站点源码。站点使用原生 HTML、CSS 与少量 JavaScript 构建，并托管在 GitHub Pages 上。

## 功能亮点

- 现代化的单页式首页，包含个人介绍、最新文章与联系方式等模块。
- 文章列表页基于 `articles.json` 数据动态渲染，方便扩展与维护。
- 采用响应式设计，在桌面端与移动端均能获得良好浏览体验。

## 项目结构

```text
├── index.html              # 首页
├── subpages/
│   └── articlelist.html    # 文章列表页
├── articles/               # 文章正文
├── styles/
│   ├── general.css         # 全局基础样式
│   ├── index.css           # 首页样式
│   └── article-list.css    # 文章列表页样式
├── articles.json           # 文章元数据（标题、日期、简介、链接）
└── image/                  # 站点使用的图像资源
```

## 本地预览

直接使用任意静态服务器或浏览器打开 `index.html` 即可预览。若已安装 Python，可以通过以下命令在本地快速启动开发服务器：

```bash
python -m http.server 8000
```

随后访问 <http://localhost:8000> 即可查看站点。

## 更新文章

1. 在 `articles/` 目录下添加新的文章 HTML 文件。
2. 在 `articles.json` 中追加对应的文章信息，字段包括：
   - `title`：文章标题；
   - `date`：发表日期（字符串格式，可自定义）；
   - `description`：可选字段，用于在列表中展示的简短摘要；
   - `link`：文章链接，使用以 `/` 开头的站内绝对路径。

完成后提交修改并推送即可在页面上看到最新内容。
