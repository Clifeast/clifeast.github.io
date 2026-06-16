(function () {
  const scriptElement = document.currentScript;
  const digestDataPath = scriptElement?.dataset.digestPath || '/data/digest/today.json';
  const PREVIEW_LIMIT = 280;

  const dateElement = document.getElementById('digest-date');
  const metricsElement = document.getElementById('digest-metrics');
  const statusElement = document.getElementById('digest-status');
  const sectionsElement = document.getElementById('digest-sections');

  function formatDate(value) {
    if (!value) {
      return new Intl.DateTimeFormat('zh-CN', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        weekday: 'short',
      }).format(new Date());
    }

    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) {
      return value;
    }

    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
      weekday: 'short',
    }).format(date);
  }

  function normalizeText(value) {
    return String(value || '').replace(/\s+/g, ' ').trim();
  }

  function makePreview(value) {
    const text = normalizeText(value);
    if (text.length <= PREVIEW_LIMIT) {
      return text;
    }

    const trimmed = text.slice(0, PREVIEW_LIMIT).replace(/\s+\S*$/, '');
    return `${trimmed}...`;
  }

  function createTextElement(tagName, className, text) {
    const element = document.createElement(tagName);
    if (className) {
      element.className = className;
    }
    element.textContent = text;
    return element;
  }

  function renderMetrics(sections) {
    const fragment = document.createDocumentFragment();
    sections.forEach((section) => {
      const count = Array.isArray(section.papers) ? section.papers.length : 0;
      const chip = document.createElement('span');
      chip.textContent = `${section.title}: ${count}`;
      fragment.appendChild(chip);
    });

    metricsElement.replaceChildren(fragment);
  }

  function renderPaper(paper) {
    const article = document.createElement('article');
    article.className = 'paper-card';

    const meta = document.createElement('div');
    meta.className = 'paper-card__meta';
    meta.append(
      createTextElement('span', 'paper-card__source', paper.source || 'Unknown source'),
      createTextElement('span', 'paper-card__date', paper.date || 'Unknown date'),
    );

    const title = createTextElement('h3', 'paper-card__title', paper.title || 'Untitled paper');
    const authors = createTextElement(
      'p',
      'paper-card__authors',
      Array.isArray(paper.authors) && paper.authors.length ? paper.authors.join(', ') : 'Unknown authors',
    );
    const abstract = createTextElement('p', 'paper-card__abstract', makePreview(paper.abstract));

    const tags = document.createElement('div');
    tags.className = 'paper-card__tags';
    (Array.isArray(paper.tags) ? paper.tags : []).slice(0, 5).forEach((tag) => {
      tags.appendChild(createTextElement('span', '', tag));
    });

    const link = document.createElement('a');
    link.className = 'paper-card__link';
    link.href = paper.url || '#';
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = 'Paper link';

    article.append(meta, title, authors, abstract);
    if (tags.childElementCount) {
      article.appendChild(tags);
    }
    article.appendChild(link);
    return article;
  }

  function renderSection(section) {
    const wrapper = document.createElement('section');
    wrapper.className = 'digest-section';
    wrapper.id = section.id || '';

    const papers = Array.isArray(section.papers) ? section.papers : [];
    const header = document.createElement('div');
    header.className = 'digest-section__header';
    header.append(
      createTextElement('h2', 'digest-section__title', section.title || 'Untitled section'),
      createTextElement('span', 'digest-section__count', `${papers.length} 篇`),
    );

    wrapper.appendChild(header);

    if (!papers.length) {
      wrapper.appendChild(createTextElement('p', 'digest-empty', '今天暂时没有筛到合适论文。'));
      return wrapper;
    }

    const grid = document.createElement('div');
    grid.className = 'paper-grid';
    papers.forEach((paper) => {
      grid.appendChild(renderPaper(paper));
    });

    wrapper.appendChild(grid);
    return wrapper;
  }

  function renderDigest(data) {
    const sections = Array.isArray(data.sections) ? data.sections : [];
    dateElement.textContent = formatDate(data.date);
    renderMetrics(sections);

    const fragment = document.createDocumentFragment();
    sections.forEach((section) => {
      fragment.appendChild(renderSection(section));
    });

    sectionsElement.replaceChildren(fragment);
    statusElement.hidden = true;
  }

  function showError(error) {
    statusElement.hidden = false;
    statusElement.classList.add('digest-status--error');
    statusElement.textContent = `无法读取今日论文数据：${error.message}`;
  }

  async function init() {
    try {
      const response = await fetch(digestDataPath, { cache: 'no-store' });
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();
      renderDigest(data);
    } catch (error) {
      showError(error);
    }
  }

  document.addEventListener('DOMContentLoaded', init);
}());
