#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require("playwright");

const BASE_URL = process.env.BASE_URL || "http://localhost:8000";
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || "/private/tmp/clifeast-playwright";

function pageURL(pathname) {
  return new URL(pathname, BASE_URL).toString();
}

async function getBrokenImages(page) {
  return page.$$eval("img", (images) =>
    images
      .filter((image) => !image.complete || image.naturalWidth === 0)
      .map((image) => image.currentSrc || image.src || image.alt),
  );
}

async function loadLazyImages(page) {
  await page.evaluate(async () => {
    const delay = (milliseconds) =>
      new Promise((resolve) => {
        window.setTimeout(resolve, milliseconds);
      });

    const scrollStep = Math.max(window.innerHeight, 600);
    const maxScrollY = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);

    for (let scrollY = 0; scrollY <= maxScrollY; scrollY += scrollStep) {
      window.scrollTo(0, scrollY);
      await delay(80);
    }

    window.scrollTo(0, 0);
  });

  await page.waitForLoadState("networkidle");
}

async function visit(page, name, pathname, screenshotName) {
  await page.goto(pageURL(pathname), { waitUntil: "networkidle" });
  await page.screenshot({
    path: path.join(SCREENSHOT_DIR, screenshotName),
    fullPage: false,
  });
  await loadLazyImages(page);

  return {
    name,
    url: page.url(),
    title: await page.title(),
    brokenImages: await getBrokenImages(page),
  };
}

async function main() {
  fs.mkdirSync(SCREENSHOT_DIR, { recursive: true });

  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({
    viewport: {
      width: 1280,
      height: 900,
    },
  });

  const consoleIssues = [];
  const failedResponses = [];

  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type())) {
      consoleIssues.push(`${message.type()}: ${message.text()}`);
    }
  });

  page.on("response", (response) => {
    if (response.status() >= 400) {
      failedResponses.push(`${response.status()} ${response.url()}`);
    }
  });

  const home = await visit(page, "home", "/", "home.png");
  home.latestCards = await page.locator("#latest-posts .post-card").count();
  home.latestLinks = await page.$$eval("#latest-posts a", (links) =>
    links.map((link) => ({
      text: link.textContent.trim(),
      href: link.href,
    })),
  );

  const articleList = await visit(page, "article list", "/articles/", "articles.png");
  articleList.articleCards = await page.locator(".article-feed .article-card").count();
  articleList.navCTA = await page.locator(".nav-cta").innerText();

  const digest = await visit(page, "digest", "/digest/", "digest.png");
  digest.sectionCount = await page.locator(".digest-section").count();
  digest.paperCards = await page.locator(".paper-card").count();

  const dongbei = await visit(page, "dongbei", "/articles/dongbei.html", "dongbei.png");
  dongbei.imageCount = await page.locator(".article-body img").count();
  dongbei.sectionCount = await page.locator(".article-body h2").count();

  const qingcai = await visit(page, "qingcai", "/articles/qingcai.html", "qingcai.png");
  qingcai.paragraphCount = await page.locator(".article-body p").count();

  await browser.close();

  const result = {
    baseURL: BASE_URL,
    screenshots: SCREENSHOT_DIR,
    pages: [home, articleList, digest, dongbei, qingcai],
    failedResponses,
    consoleIssues,
  };

  console.log(JSON.stringify(result, null, 2));

  const brokenImages = result.pages.flatMap((sitePage) =>
    sitePage.brokenImages.map((image) => `${sitePage.name}: ${image}`),
  );

  if (failedResponses.length > 0 || consoleIssues.length > 0 || brokenImages.length > 0) {
    process.exitCode = 1;
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
