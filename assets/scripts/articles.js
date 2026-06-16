(() => {
  const scriptElement = document.currentScript;
  const articlesDataPath = scriptElement?.dataset.articlesPath || "/data/articles.json";
  const latestLimit = Number(scriptElement?.dataset.latestLimit || 3);

  function createElement(tagName, className, textContent) {
    const element = document.createElement(tagName);

    if (className) {
      element.className = className;
    }

    if (textContent) {
      element.textContent = textContent;
    }

    return element;
  }

  function clear(element) {
    element.replaceChildren();
  }

  function renderLatestMessage(container, title, description, date = "") {
    clear(container);

    const card = createElement("article", "card post-card");

    if (date) {
      card.append(createElement("span", "post-card__date", date));
    }

    card.append(createElement("h3", "post-card__title", title));
    card.append(createElement("p", "post-card__description", description));
    container.append(card);
  }

  function renderListMessage(container, title, description) {
    clear(container);

    const card = createElement("article", "card article-card");
    const header = createElement("div", "article-card__header");

    header.append(createElement("h2", "article-card__title", title));
    card.append(header);
    card.append(createElement("p", "article-card__description", description));
    container.append(card);
  }

  function createLatestCard(post) {
    const card = createElement("article", "card post-card");
    const title = createElement("h3", "post-card__title", post.title);
    const link = createElement("a", "post-card__link", "阅读全文 →");

    link.href = post.link;

    card.append(createElement("span", "post-card__date", post.date));
    card.append(title);

    if (post.description) {
      card.append(createElement("p", "post-card__description", post.description));
    }

    card.append(link);
    return card;
  }

  function createArticleCard(article) {
    const card = createElement("article", "card article-card");
    const header = createElement("div", "article-card__header");
    const actions = createElement("div", "article-card__actions");
    const link = createElement("a", "btn btn-primary", "阅读全文");

    link.href = article.link;

    header.append(createElement("h2", "article-card__title", article.title));
    header.append(createElement("span", "article-card__meta", article.date));
    actions.append(link);

    card.append(header);

    if (article.description) {
      card.append(createElement("p", "article-card__description", article.description));
    }

    card.append(actions);
    return card;
  }

  async function loadArticles() {
    const response = await fetch(articlesDataPath);

    if (!response.ok) {
      throw new Error(`Unable to load articles: ${response.status}`);
    }

    const articles = await response.json();

    if (!Array.isArray(articles)) {
      throw new Error("Articles data must be an array");
    }

    return articles;
  }

  function renderLatest(container, articles) {
    clear(container);

    if (articles.length === 0) {
      renderLatestMessage(container, "暂时还没有文章", "可以稍后再来看看。");
      return;
    }

    articles.slice(0, latestLimit).forEach((post) => {
      container.append(createLatestCard(post));
    });
  }

  function renderList(container, articles) {
    clear(container);

    if (articles.length === 0) {
      renderListMessage(container, "暂时没有文章", "可以稍后再来，或回到首页看看最近的动态。");
      return;
    }

    articles.forEach((article) => {
      container.append(createArticleCard(article));
    });
  }

  async function initArticles() {
    const latestContainer = document.querySelector('[data-articles-view="latest"]');
    const listContainer = document.querySelector('[data-articles-view="list"]');

    if (!latestContainer && !listContainer) {
      return;
    }

    try {
      const articles = await loadArticles();

      if (latestContainer) {
        renderLatest(latestContainer, articles);
      }

      if (listContainer) {
        renderList(listContainer, articles);
      }
    } catch (error) {
      console.error("加载文章失败：", error);

      if (latestContainer) {
        renderLatestMessage(latestContainer, "无法获取文章", "请检查本地服务器或稍后重试。", "出错了");
      }

      if (listContainer) {
        renderListMessage(listContainer, "无法获取文章", "请检查本地服务器或稍后重试。");
      }
    }
  }

  document.addEventListener("DOMContentLoaded", initArticles);
})();
