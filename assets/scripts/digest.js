(function () {
  const scriptElement = document.currentScript;
  const digestDataPath = scriptElement?.dataset.digestPath || '/data/digest/today.json';
  const digestIndexPath = scriptElement?.dataset.digestIndexPath || '/data/digest/index.json';
  const PREVIEW_LIMIT = 280;
  const DEFAULT_SCORE_LABELS = {
    importance: '重要性',
    horizonValue: '视野价值',
    clarity: '清晰度',
    theoreticalDepth: '理论深度',
    overall: '整体判断',
    modelNaturalness: '问题与模型自然性',
    theoreticalStrength: '理论结果强度',
    guaranteeQuality: '保证与假设质量',
    readingValue: '阅读收益',
    aiRelevance: 'AI 相关度',
    agtRelevance: 'AGT 相关度',
    penalty: '惩罚',
    baseTotal: '基础分',
    bonus: 'AI 奖励',
    total: '总分',
  };
  const SCORE_ORDER = [
    'importance',
    'horizonValue',
    'clarity',
    'theoreticalDepth',
    'overall',
    'modelNaturalness',
    'theoreticalStrength',
    'guaranteeQuality',
    'readingValue',
    'penalty',
    'baseTotal',
    'aiRelevance',
    'bonus',
    'agtRelevance',
  ];
  const SUMMARY_SECTION_ORDER = [
    ['backgroundAndQuestion', '背景与问题'],
    ['modelAndSetup', '模型与设定'],
    ['contributionsAndResults', '贡献与结果'],
    ['methodsAndTechniques', '方法与技术'],
    ['limitationsAndReadingValue', '局限与阅读价值'],
  ];
  let scoreLabels = DEFAULT_SCORE_LABELS;
  let archiveOptions = [];
  let calendarMonth = '';
  let selectedDigest = 'today';

  const dateElement = document.getElementById('digest-date');
  const pickerRoot = document.querySelector('.digest-picker');
  const pickerTrigger = document.getElementById('digest-picker-trigger');
  const pickerPopover = document.getElementById('digest-picker-popover');
  const todayButton = document.getElementById('digest-today-button');
  const calendarElement = document.getElementById('digest-calendar');
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

  function formatMonth(value) {
    const date = new Date(`${value}-01T00:00:00`);
    if (Number.isNaN(date.getTime())) {
      return value;
    }
    return new Intl.DateTimeFormat('zh-CN', {
      year: 'numeric',
      month: 'long',
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

  function formatScoreValue(key, value) {
    const number = Number(value);
    if (!Number.isFinite(number)) {
      return '';
    }
    return key === 'total' || key === 'bonus' ? number.toFixed(1) : String(Math.round(number));
  }

  function renderScores(scores, sectionId) {
    if (!scores || typeof scores !== 'object' || !hasScoreValue(scores.total)) {
      return null;
    }

    const wrapper = document.createElement('div');
    wrapper.className = `paper-card__scores${sectionId === 'recent-agt' ? ' paper-card__scores--agt' : ''}`;

    const total = document.createElement('div');
    total.className = 'paper-card__score-total';
    total.append(
      createTextElement('span', '', scoreLabels.total || '总分'),
      createTextElement('strong', '', formatScoreValue('total', scores.total)),
    );
    if (hasScoreValue(scores.bonus)) {
      total.classList.add('paper-card__score-total--with-bonus');
      const bonus = document.createElement('span');
      bonus.className = 'paper-card__score-bonus';
      bonus.append(
        document.createTextNode(`${scoreLabels.bonus || 'AI 奖励'} `),
        createTextElement('strong', '', formatScoreValue('bonus', scores.bonus)),
      );
      total.appendChild(bonus);
    }

    const details = document.createElement('div');
    details.className = `paper-card__score-list${sectionId === 'recent-agt' ? ' paper-card__score-list--agt' : ''}`;
    SCORE_ORDER.forEach((key) => {
      if (key === 'bonus' || !hasScoreValue(scores[key])) {
        return;
      }

      const item = document.createElement('span');
      item.className = 'paper-card__score-item';
      item.append(
        createTextElement('span', 'paper-card__score-label', scoreLabels[key] || key),
        createTextElement('strong', '', formatScoreValue(key, scores[key])),
      );
      details.appendChild(item);
    });

    wrapper.append(total, details);
    return wrapper;
  }

  function renderSummary(paper) {
    const sections = paper.summarySections && typeof paper.summarySections === 'object'
      ? paper.summarySections
      : null;
    if (sections) {
      const entries = SUMMARY_SECTION_ORDER
        .map(([key, label]) => [label, normalizeText(sections[key])])
        .filter(([, text]) => text);
      if (entries.length) {
        const wrapper = document.createElement('div');
        wrapper.className = 'paper-card__summary-sections';
        entries.forEach(([label, text]) => {
          const block = document.createElement('section');
          block.className = 'paper-card__summary-section';
          block.append(
            createTextElement('h4', '', label),
            createTextElement('p', '', text),
          );
          wrapper.appendChild(block);
        });
        return wrapper;
      }
    }

    const summaryText = makePreview(paper.abstract);
    return createTextElement('p', 'paper-card__abstract', summaryText || '暂无简介。');
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

  function renderPaper(paper, sectionId) {
    const article = document.createElement('article');
    article.className = `paper-card${sectionId === 'recent-agt' ? ' paper-card--agt' : ''}`;

    const meta = document.createElement('div');
    meta.className = 'paper-card__meta';
    meta.append(
      createTextElement('span', 'paper-card__date', paper.date || 'Unknown date'),
    );

    const title = createTextElement('h3', 'paper-card__title', paper.title || 'Untitled paper');
    const authors = createTextElement(
      'p',
      'paper-card__authors',
      Array.isArray(paper.authors) && paper.authors.length ? paper.authors.join(', ') : 'Unknown authors',
    );
    const summary = renderSummary(paper);

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

    const scores = renderScores(paper.scores, sectionId);

    const link = document.createElement('a');
    link.className = 'paper-card__link';
    link.href = paper.url || '#';
    link.target = '_blank';
    link.rel = 'noreferrer';
    link.textContent = '查看论文';

    article.append(meta, title, authors, summary);
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
      grid.appendChild(renderPaper(paper, section.id || ''));
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

  function digestPathForValue(value) {
    if (!value || value === 'today') {
      return digestDataPath;
    }
    return `/data/digest/${encodeURIComponent(value)}.json`;
  }

  function setPickerOpen(open) {
    if (!pickerPopover || !pickerTrigger) {
      return;
    }
    pickerPopover.hidden = !open;
    pickerTrigger.setAttribute('aria-expanded', String(open));
    pickerRoot?.classList.toggle('digest-picker--open', open);
  }

  function updatePickerLabel() {
    if (!pickerTrigger) {
      return;
    }
    pickerTrigger.textContent = '选择简报';
  }

  function monthFromDate(value) {
    return normalizeText(value).slice(0, 7);
  }

  function addMonths(month, offset) {
    const date = new Date(`${month}-01T00:00:00`);
    date.setMonth(date.getMonth() + offset);
    const year = date.getFullYear();
    const monthNumber = String(date.getMonth() + 1).padStart(2, '0');
    return `${year}-${monthNumber}`;
  }

  function renderCalendar() {
    if (!calendarElement) {
      return;
    }

    const dates = new Set(archiveOptions);
    const months = [...new Set(archiveOptions.map(monthFromDate).filter(Boolean))].sort();
    if (!calendarMonth) {
      calendarMonth = months[months.length - 1] || monthFromDate(new Date().toISOString().slice(0, 10));
    }
    const firstMonth = months[0] || calendarMonth;
    const lastMonth = months[months.length - 1] || calendarMonth;
    const canPrev = calendarMonth > firstMonth;
    const canNext = calendarMonth < lastMonth;

    const header = document.createElement('div');
    header.className = 'digest-calendar__header';
    const prev = document.createElement('button');
    prev.className = 'digest-calendar__nav';
    prev.type = 'button';
    prev.textContent = '‹';
    prev.disabled = !canPrev;
    prev.setAttribute('aria-label', '上个月');
    prev.addEventListener('click', (event) => {
      event.stopPropagation();
      calendarMonth = addMonths(calendarMonth, -1);
      renderCalendar();
    });
    const label = createTextElement('span', 'digest-calendar__month', formatMonth(calendarMonth));
    const next = document.createElement('button');
    next.className = 'digest-calendar__nav';
    next.type = 'button';
    next.textContent = '›';
    next.disabled = !canNext;
    next.setAttribute('aria-label', '下个月');
    next.addEventListener('click', (event) => {
      event.stopPropagation();
      calendarMonth = addMonths(calendarMonth, 1);
      renderCalendar();
    });
    header.append(prev, label, next);

    const weekdays = document.createElement('div');
    weekdays.className = 'digest-calendar__weekdays';
    ['一', '二', '三', '四', '五', '六', '日'].forEach((day) => {
      weekdays.appendChild(createTextElement('span', '', day));
    });

    const grid = document.createElement('div');
    grid.className = 'digest-calendar__grid';
    const firstDay = new Date(`${calendarMonth}-01T00:00:00`);
    const daysInMonth = new Date(firstDay.getFullYear(), firstDay.getMonth() + 1, 0).getDate();
    const leading = (firstDay.getDay() + 6) % 7;
    for (let index = 0; index < leading; index += 1) {
      grid.appendChild(createTextElement('span', 'digest-calendar__blank', ''));
    }
    for (let day = 1; day <= daysInMonth; day += 1) {
      const date = `${calendarMonth}-${String(day).padStart(2, '0')}`;
      const button = document.createElement('button');
      button.className = 'digest-calendar__day';
      button.type = 'button';
      button.textContent = String(day);
      button.disabled = !dates.has(date);
      if (selectedDigest === date) {
        button.classList.add('digest-calendar__day--selected');
      }
      button.setAttribute('aria-label', dates.has(date) ? `${formatDate(date)} 简报` : `${date} 无简报`);
      button.addEventListener('click', () => {
        loadSelectedDigest(date);
      });
      grid.appendChild(button);
    }

    calendarElement.replaceChildren(header, weekdays, grid);
  }

  async function loadArchiveOptions() {
    try {
      const response = await fetch(digestIndexPath);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();
      const dates = Array.isArray(data.dates) ? data.dates : [];
      archiveOptions = dates.map(normalizeText).filter(Boolean);
      calendarMonth = monthFromDate(archiveOptions[0] || new Date().toISOString().slice(0, 10));
      renderCalendar();
    } catch (error) {
      archiveOptions = [];
      renderCalendar();
    }
  }

  async function loadDigest(path) {
    const response = await fetch(path);
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    return response.json();
  }

  async function loadSelectedDigest(value) {
    try {
      const nextDigest = value || 'today';
      statusElement.hidden = false;
      statusElement.classList.remove('digest-status--error');
      statusElement.textContent = '正在切换简报...';
      const data = await loadDigest(digestPathForValue(nextDigest));
      selectedDigest = nextDigest;
      if (selectedDigest !== 'today') {
        calendarMonth = monthFromDate(selectedDigest);
      }
      todayButton?.classList.toggle('digest-picker__today--active', selectedDigest === 'today');
      updatePickerLabel();
      renderCalendar();
      renderDigest(data);
      setPickerOpen(false);
    } catch (error) {
      showError(error);
    }
  }

  async function init() {
    try {
      await loadArchiveOptions();
      selectedDigest = 'today';
      todayButton?.classList.add('digest-picker__today--active');
      updatePickerLabel();
      const data = await loadDigest(digestPathForValue(selectedDigest));
      renderDigest(data);
    } catch (error) {
      showError(error);
    }
  }

  todayButton?.addEventListener('click', () => {
    loadSelectedDigest('today');
  });

  pickerTrigger?.addEventListener('click', () => {
    setPickerOpen(pickerPopover?.hidden ?? true);
  });

  pickerPopover?.addEventListener('click', (event) => {
    event.stopPropagation();
  });

  document.addEventListener('click', (event) => {
    if (!pickerRoot || pickerPopover?.hidden) {
      return;
    }
    if (!pickerRoot.contains(event.target)) {
      setPickerOpen(false);
    }
  });

  document.addEventListener('keydown', (event) => {
    if (event.key === 'Escape') {
      setPickerOpen(false);
    }
  });

  document.addEventListener('DOMContentLoaded', init);
}());
