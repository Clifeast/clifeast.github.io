#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");

const ROOT_DIR = path.resolve(__dirname, "..");
const CONTENT_DIR = path.join(ROOT_DIR, "content", "articles");
const OUTPUT_DIR = path.join(ROOT_DIR, "articles");
const DATA_FILE = path.join(ROOT_DIR, "data", "articles.json");
const CHECK_MODE = process.argv.includes("--check");

const requiredFields = ["title", "date", "publishedAt", "slug"];
const staleFiles = [];
let writtenFiles = 0;

function escapeHTML(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function parseFrontmatter(filePath) {
  const raw = fs.readFileSync(filePath, "utf8").replace(/\r\n/g, "\n");
  const match = raw.match(/^---\n([\s\S]*?)\n---\n?([\s\S]*)$/);

  if (!match) {
    throw new Error(`${path.relative(ROOT_DIR, filePath)} is missing frontmatter`);
  }

  const meta = {};
  match[1]
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .forEach((line) => {
      const separatorIndex = line.indexOf(":");

      if (separatorIndex === -1) {
        throw new Error(`Invalid frontmatter line in ${filePath}: ${line}`);
      }

      const key = line.slice(0, separatorIndex).trim();
      const value = line.slice(separatorIndex + 1).trim();
      meta[key] = value;
    });

  requiredFields.forEach((field) => {
    if (!meta[field]) {
      throw new Error(`${path.relative(ROOT_DIR, filePath)} is missing "${field}"`);
    }
  });

  return {
    meta,
    content: match[2].trim(),
    sourcePath: filePath,
  };
}

function getArticles() {
  return fs
    .readdirSync(CONTENT_DIR)
    .filter((file) => file.endsWith(".html"))
    .map((file) => parseFrontmatter(path.join(CONTENT_DIR, file)))
    .sort((a, b) => b.meta.publishedAt.localeCompare(a.meta.publishedAt));
}

function addLazyLoading(content) {
  return content.replace(/<img(?![^>]*\bloading=)/g, '<img loading="lazy"');
}

function indent(content, spaces) {
  const padding = " ".repeat(spaces);
  return content
    .split("\n")
    .map((line) => (line ? `${padding}${line}` : line))
    .join("\n");
}

function renderArticlePage(article) {
  const { meta } = article;
  const description = meta.description || `${meta.title} · 草树之后`;
  const articleMeta = meta.meta || meta.date;
  const body = indent(addLazyLoading(article.content), 12);

  return `<!DOCTYPE html>
<html lang="zh-CN">

<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${escapeHTML(meta.title)} · 草树之后</title>
  <meta name="description" content="${escapeHTML(description)}" />
  <link rel="icon" type="image/png" href="/assets/images/profileblack.png" />
  <link rel="stylesheet" href="/assets/styles/general.css" />
  <link rel="stylesheet" href="/assets/styles/index.css" />
  <link rel="stylesheet" href="/assets/styles/articles.css" />
  <script defer src="/assets/scripts/layout.js"></script>
</head>

<body>
  <div class="page article-page">
    <header class="site-header" data-component="site-header"></header>

    <main class="content article-main">
      <div class="article-container">
        <header class="article-header">
          <h1 class="article-title">${escapeHTML(meta.title)}</h1>
          <p class="article-meta">${escapeHTML(articleMeta)}</p>
        </header>

        <article class="article-body">
${body}
        </article>

        <div class="article-actions">
          <a class="btn btn-ghost" href="/articles/">返回文章列表</a>
          <a class="btn btn-primary" href="/#latest">查看最新文章</a>
        </div>
      </div>
    </main>

    <footer class="site-footer" data-component="site-footer"></footer>
  </div>
</body>

</html>
`;
}

function renderArticlesData(articles) {
  const data = articles.map(({ meta }) => {
    const article = {
      title: meta.title,
      date: meta.date,
      publishedAt: meta.publishedAt,
      link: `/articles/${meta.slug}.html`,
    };

    if (meta.description) {
      article.description = meta.description;
    }

    return article;
  });

  return `${JSON.stringify(data, null, 2)}\n`;
}

function writeFileIfChanged(filePath, content) {
  const current = fs.existsSync(filePath) ? fs.readFileSync(filePath, "utf8") : null;

  if (current === content) {
    return;
  }

  const relativePath = path.relative(ROOT_DIR, filePath);

  if (CHECK_MODE) {
    staleFiles.push(relativePath);
    return;
  }

  fs.mkdirSync(path.dirname(filePath), { recursive: true });
  fs.writeFileSync(filePath, content);
  writtenFiles += 1;
  console.log(`Wrote ${relativePath}`);
}

function main() {
  const articles = getArticles();

  articles.forEach((article) => {
    writeFileIfChanged(
      path.join(OUTPUT_DIR, `${article.meta.slug}.html`),
      renderArticlePage(article),
    );
  });

  writeFileIfChanged(DATA_FILE, renderArticlesData(articles));

  if (CHECK_MODE && staleFiles.length > 0) {
    console.error(`Generated files are stale:\n${staleFiles.map((file) => `- ${file}`).join("\n")}`);
    process.exit(1);
  }

  if (CHECK_MODE) {
    console.log("Generated files are up to date.");
  } else {
    console.log(writtenFiles === 0 ? "Generated files already up to date." : `Updated ${writtenFiles} generated file(s).`);
  }
}

main();
