(function () {
  const scriptElement = document.currentScript;
  const digestDataPath = scriptElement?.dataset.digestPath || '/data/digest/today.json';
  const PREVIEW_LIMIT = 280;
  const DEFAULT_SCORE_LABELS = {
    relevance: '相关性',
    novelty: '新颖性',
    theoreticalDepth: '理论深度',
    readability: '可读性',
    potentialImpact: '潜在影响',
    total: '总分',
  };
  const SCORE_ORDER = ['relevance', 'novelty', 'theoreticalDepth', 'readability', 'potentialImpact'];
  let scoreLabels = DEFAULT_SCORE_LABELS;

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

  function hasScoreValue(value) {
    return Number.isFinite(Number(value));
  }

  function renderScores(scores) {
    if (!scores || typeof scores !== 'object' || !hasScoreValue(scores.total)) {
      return null;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'paper-card__scores';

    const total = document.createElement('div');
    total.className = 'paper-card__score-total';
    total.append(
      createTextElement('span', '', scoreLabels.total || '总分'),
      createTextElement('strong', '', Number(scores.total).toFixed(1)),
    );

    const details = document.createElement('div');
    details.className = 'paper-card__score-list';
    SCORE_ORDER.forEach((key) => {
      if (!hasScoreValue(scores[key])) {
        return;
      }

      const item = document.createElement('span');
      item.append(
        document.createTextNode(`${scoreLabels[key] || key} `),
        createTextElement('strong', '', Number(scores[key]).toFixed(1)),
      );
      details.appendChild(item);
    });

    wrapper.append(total, details);
    return wrapper;
  }

  function renderTagGroup(label, tags, modifier) {
    const cleanTags = (Array.isArray(tags) ? tags : []).map(normalizeText).filter(Boolean).slice(0, 5);
    if (!cleanTags.length) {
      return null;
    }

    const group = document.createElement('div');
    group.className = `paper-card__tag-group paper-card__tag-group--${modifier}`;
    group.appendChild(createTextElement('span', 'paper-card__tag-label', label));

    const tagList = document.createElement('div');
    tagList.className = 'paper-card__tags';
    cleanTags.forEach((tag) => {
      tagList.appendChild(createTextElement('span', '', tag));
    });
    group.appendChild(tagList);
    return group;
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
    const summaryText = normalizeText(paper.summaryZh) || makePreview(paper.abstract);
    const abstract = createTextElement('p', 'paper-card__abstract', summaryText || '暂无简介。');

    const tagGroups = document.createElement('div');
    tagGroups.className = 'paper-card__tag-groups';
    const paradigmTags = renderTagGroup('范式', paper.researchParadigmTags, 'paradigm');
    const contentTags = renderTagGroup('内容', paper.contentTags || paper.tags, 'content');
    if (paradigmTags) {
      tagGroups.appendChild(paradigmTags);
    }
    if (contentTags) {
      tagGroups.appendChild(contentTags);
    }

    const scores = renderScores(paper.scores);

    const link = document.createElement('a');
    link.className = 'paper-card__link';
    link.href = paper.url || '#';
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = '查看论文';

    article.append(meta, title, authors, abstract);
    if (tagGroups.childElementCount) {
      article.appendChild(tagGroups);
    }
    if (scores) {
      article.appendChild(scores);
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
    scoreLabels = data.scoreLabels && typeof data.scoreLabels === 'object'
      ? { ...DEFAULT_SCORE_LABELS, ...data.scoreLabels }
      : DEFAULT_SCORE_LABELS;
    dateElement.textContent = formatDate(data.date);
    renderMetrics(sections);

    const fragment = document.createDocumentFragment();
    sections.forEach((section) => {
      fragment.appendChild(renderSection(section));
    });

    sectionsElement.replaceChildren(fragment);
    const warnings = Array.isArray(data.warnings) ? data.warnings.filter(Boolean) : [];
    if (warnings.length) {
      statusElement.hidden = false;
      statusElement.classList.remove('digest-status--error');
      statusElement.textContent = `部分来源未成功：${warnings[0]}${warnings.length > 1 ? ` 等 ${warnings.length} 条` : ''}`;
    } else {
      statusElement.hidden = true;
    }
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
