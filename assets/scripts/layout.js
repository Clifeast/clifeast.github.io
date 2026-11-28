const headerTemplate = `
  <div class="site-header__inner">
    <a class="brand" href="/">
      <img src="/assets/images/profileblack.png" alt="赏鹤阳头像" class="brand-logo" width="26" height="26" />
      <div class="brand-meta">
        <span class="brand-name brand-name--full">赏鹤阳 · 草树之后</span>
        <span class="brand-name brand-name--compact">赏鹤阳 · 草树之后</span>
      </div>
    </a>
    <div class="site-header__actions">
      <nav class="site-nav" aria-label="主导航">
        <a class="nav-link" href="/#about">关于</a>
        <a class="nav-link" href="/#latest">最新</a>
        <a class="nav-link" href="/#contact">联系</a>
        <a class="nav-cta" href="/articles/">我的文章</a>
      </nav>
      <button
        type="button"
        class="theme-toggle"
        id="themeToggle"
        aria-label="切换浅色或深色主题"
        title="切换浅色 / 深色模式"
      >
        <svg class="icon-sun" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <circle cx="12" cy="12" r="4"></circle>
          <path d="M12 2v2"></path>
          <path d="M12 20v2"></path>
          <path d="m4.93 4.93 1.41 1.41"></path>
          <path d="m17.66 17.66 1.41 1.41"></path>
          <path d="M2 12h2"></path>
          <path d="M20 12h2"></path>
          <path d="m6.34 17.66-1.41 1.41"></path>
          <path d="m19.07 4.93-1.41 1.41"></path>
        </svg>
        <svg class="icon-moon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.75" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
          <path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"></path>
        </svg>
      </button>
      <button class="site-menu-toggle" type="button" aria-label="打开导航菜单" aria-expanded="false"
        aria-controls="site-menu-drawer">
        <span></span><span></span><span></span>
      </button>
    </div>
  </div>
  <div class="site-menu-backdrop" hidden></div>
  <aside class="site-menu-drawer" id="site-menu-drawer" aria-label="移动端导航" aria-hidden="true">
    <div class="site-menu-drawer__header">
      <span>导航</span>
      <button class="site-menu-close" type="button" aria-label="关闭导航菜单">×</button>
    </div>
    <nav class="site-menu-drawer__links">
      <a href="/#about">关于</a>
      <a href="/#latest">最新</a>
      <a href="/#contact">联系</a>
      <a class="site-menu-drawer__cta" href="/articles/">我的文章</a>
    </nav>
  </aside>
`;

const footerTemplate = `
  <div class="footer-inner">
    <p class="footer-copy">© <span data-current-year></span> 赏鹤阳 · 草树之后</p>
    <div class="footer-meta">
      <span>草树之后 · Beijing</span>
      <span class="footer-sep" aria-hidden="true">/</span>
      <a href="#top" class="footer-top-link">返回顶部 ↑</a>
    </div>
  </div>
`;

function ensureChromeElements() {
  if (!document.querySelector('.scroll-progress')) {
    const progress = document.createElement('div');
    progress.className = 'scroll-progress';
    progress.setAttribute('aria-hidden', 'true');
    const bar = document.createElement('div');
    bar.className = 'scroll-progress-bar';
    bar.id = 'scrollProgressBar';
    progress.appendChild(bar);
    document.body.prepend(progress);
  }

  if (!document.querySelector('.ambient-backdrop')) {
    const backdrop = document.createElement('div');
    backdrop.className = 'ambient-backdrop';
    backdrop.setAttribute('aria-hidden', 'true');
    document.body.prepend(backdrop);
  }

  if (!document.getElementById('top')) {
    const main = document.querySelector('main');
    if (main) {
      main.id = 'top';
    }
  }
}

function initThemeToggle() {
  const root = document.documentElement;
  if (!root.getAttribute('data-theme')) {
    try {
      const saved = localStorage.getItem('theme');
      const prefersDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      const theme = saved === 'dark' || saved === 'light' ? saved : (prefersDark ? 'dark' : 'light');
      root.setAttribute('data-theme', theme);
    } catch (_) {
      root.setAttribute('data-theme', 'light');
    }
  }

  document.querySelectorAll('.theme-toggle').forEach((button) => {
    button.addEventListener('click', () => {
      const current = root.getAttribute('data-theme') === 'dark' ? 'dark' : 'light';
      const next = current === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try {
        localStorage.setItem('theme', next);
      } catch (_) {
        // Ignore storage restrictions
      }
    });
  });
}

function initScrollEffects() {
  const header = document.querySelector('.site-header');
  const progressBar = document.getElementById('scrollProgressBar');

  function handleScroll() {
    const scrollTop = window.scrollY || document.documentElement.scrollTop;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;

    if (header) {
      header.classList.toggle('is-scrolled', scrollTop > 12);
    }

    if (progressBar && docHeight > 0) {
      const pct = Math.min(100, Math.max(0, (scrollTop / docHeight) * 100));
      progressBar.style.width = `${pct}%`;
    } else if (progressBar) {
      progressBar.style.width = '0%';
    }
  }

  window.addEventListener('scroll', handleScroll, { passive: true });
  handleScroll();
}

function initActiveNavigation() {
  const currentPath = window.location.pathname;
  const navLinks = Array.from(document.querySelectorAll('.site-nav .nav-link'));

  if (currentPath.startsWith('/digest')) {
    navLinks.forEach((link) => {
      link.classList.toggle('is-active', link.getAttribute('href') === '/digest/');
    });
    return;
  }

  if (currentPath === '/' || currentPath === '/index.html') {
    const sectionPairs = navLinks
      .map((link) => {
        const href = link.getAttribute('href') || '';
        const hashIndex = href.indexOf('#');
        if (hashIndex === -1) return null;
        const target = document.querySelector(href.slice(hashIndex));
        return target ? { link, target } : null;
      })
      .filter(Boolean);

    if ('IntersectionObserver' in window && sectionPairs.length > 0) {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting) {
              const activeHash = `/#${entry.target.id}`;
              navLinks.forEach((link) => {
                link.classList.toggle('is-active', link.getAttribute('href') === activeHash);
              });
            }
          });
        },
        { rootMargin: '-28% 0px -58% 0px', threshold: 0 },
      );

      sectionPairs.forEach(({ target }) => observer.observe(target));
    }
  }
}

function initLightbox() {
  const trigger = document.getElementById('visualTrigger');
  const lightbox = document.getElementById('visualLightbox');
  const closeButton = document.getElementById('lightboxClose');

  if (trigger && lightbox) {
    const openLightbox = () => {
      lightbox.hidden = false;
      document.body.style.overflow = 'hidden';
      closeButton?.focus();
    };

    const closeLightbox = () => {
      if (lightbox.hidden) return;
      lightbox.hidden = true;
      document.body.style.overflow = '';
      trigger.focus();
    };

    trigger.addEventListener('click', openLightbox);
    closeButton?.addEventListener('click', closeLightbox);
    lightbox.querySelectorAll('[data-close-lightbox]').forEach((el) => {
      el.addEventListener('click', closeLightbox);
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        closeLightbox();
      }
    });
  }

  const articleImages = Array.from(document.querySelectorAll('.article-body img'));
  if (!articleImages.length) {
    return;
  }

  let articleLightbox = null;
  let activeIndex = -1;
  let lastTrigger = null;

  function ensureArticleLightbox() {
    if (articleLightbox) {
      return articleLightbox;
    }

    const dialog = document.createElement('div');
    dialog.className = 'lightbox';
    dialog.id = 'articleImageLightbox';
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('aria-label', '文章图片大图预览');
    dialog.hidden = true;
    dialog.innerHTML = `
      <div class="lightbox-backdrop" data-close-article-lightbox></div>
      <div class="lightbox-content">
        <button type="button" class="lightbox-close" aria-label="关闭大图预览">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M18 6 6 18"></path>
            <path d="m6 6 12 12"></path>
          </svg>
        </button>
        <div class="lightbox-stage"></div>
      </div>
    `;
    document.body.appendChild(dialog);

    const closeBtn = dialog.querySelector('.lightbox-close');
    const backdrop = dialog.querySelector('[data-close-article-lightbox]');

    closeBtn?.addEventListener('click', closeArticleLightbox);
    backdrop?.addEventListener('click', closeArticleLightbox);

    articleLightbox = dialog;
    return dialog;
  }

  function renderArticleLightboxImage(index) {
    const dialog = ensureArticleLightbox();
    const sourceImage = articleImages[index];
    if (!sourceImage) return;

    activeIndex = index;
    const stage = dialog.querySelector('.lightbox-stage');

    const img = document.createElement('img');
    img.className = 'lightbox-img';
    img.src = sourceImage.currentSrc || sourceImage.src;
    img.alt = sourceImage.alt || '';
    stage.replaceChildren(img);
  }

  function openArticleLightbox(index, triggerEl) {
    const dialog = ensureArticleLightbox();
    lastTrigger = triggerEl || articleImages[index];
    renderArticleLightboxImage(index);
    dialog.hidden = false;
    document.body.style.overflow = 'hidden';
    dialog.querySelector('.lightbox-close')?.focus();
  }

  function closeArticleLightbox() {
    if (!articleLightbox || articleLightbox.hidden) return;
    articleLightbox.hidden = true;
    articleLightbox.querySelector('.lightbox-stage')?.replaceChildren();
    document.body.style.overflow = '';
    activeIndex = -1;
    lastTrigger?.focus();
  }

  articleImages.forEach((img, index) => {
    img.setAttribute('tabindex', '0');
    img.setAttribute('role', 'button');
    img.setAttribute('title', '点击查看大图');
    if (img.alt) {
      img.setAttribute('aria-label', `查看大图：${img.alt}`);
    } else {
      img.setAttribute('aria-label', '点击查看大图');
    }

    img.addEventListener('click', () => {
      openArticleLightbox(index, img);
    });
    img.addEventListener('keydown', (event) => {
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        openArticleLightbox(index, img);
      }
    });
  });

  document.addEventListener('keydown', (event) => {
    if (!articleLightbox || articleLightbox.hidden) return;

    if (event.key === 'Escape') {
      closeArticleLightbox();
    } else if (event.key === 'ArrowRight' && articleImages.length > 1) {
      renderArticleLightboxImage((activeIndex + 1) % articleImages.length);
    } else if (event.key === 'ArrowLeft' && articleImages.length > 1) {
      renderArticleLightboxImage((activeIndex - 1 + articleImages.length) % articleImages.length);
    }
  });
}

function initSmoothAnchors() {
  const prefersReduced =
    window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  if (prefersReduced) {
    return;
  }

  document.addEventListener('click', (event) => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const href = link.getAttribute('href');
    if (!href) return;

    const isSamePageHash =
      href.startsWith('#') ||
      (href.startsWith('/#') && (window.location.pathname === '/' || window.location.pathname === '/index.html'));
    if (!isSamePageHash) return;

    const id = href.slice(href.indexOf('#') + 1);
    const target = id ? document.getElementById(id) : null;
    if (!target) return;

    event.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    if (window.history && window.history.pushState) {
      window.history.pushState(null, '', `#${id}`);
    }
  });
}

function applySharedLayout() {
  ensureChromeElements();

  const currentPath = window.location.pathname;
  let ctaHref = '/articles/';
  let ctaLabel = '我的文章';

  if (currentPath === '/articles/' || currentPath.endsWith('/articles/index.html')) {
    ctaHref = '/';
    ctaLabel = '返回主页';
  }

  const headerHTML = headerTemplate
    .replaceAll('href="/articles/"', `href="${ctaHref}"`)
    .replaceAll('>我的文章<', `>${ctaLabel}<`);

  document.querySelectorAll('[data-component="site-header"]').forEach((element) => {
    element.innerHTML = headerHTML;

    const toggle = element.querySelector('.site-menu-toggle');
    const closeButton = element.querySelector('.site-menu-close');
    const drawer = element.querySelector('.site-menu-drawer');
    const backdrop = element.querySelector('.site-menu-backdrop');

    const setMenuOpen = (open) => {
      element.classList.toggle('site-header--menu-open', open);
      toggle?.setAttribute('aria-expanded', String(open));
      toggle?.setAttribute('aria-label', open ? '关闭导航菜单' : '打开导航菜单');
      drawer?.setAttribute('aria-hidden', String(!open));
      if (backdrop) {
        backdrop.hidden = !open;
      }
      document.body.classList.toggle('site-menu-open', open);
    };

    toggle?.addEventListener('click', () => {
      setMenuOpen(toggle.getAttribute('aria-expanded') !== 'true');
    });
    closeButton?.addEventListener('click', () => setMenuOpen(false));
    backdrop?.addEventListener('click', () => setMenuOpen(false));
    drawer?.querySelectorAll('a').forEach((link) => {
      link.addEventListener('click', () => setMenuOpen(false));
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && toggle?.getAttribute('aria-expanded') === 'true') {
        setMenuOpen(false);
        toggle.focus();
      }
    });
  });

  document.querySelectorAll('[data-component="site-footer"]').forEach((element) => {
    element.innerHTML = footerTemplate;
  });

  const currentYear = new Date().getFullYear();
  document.querySelectorAll('[data-current-year]').forEach((element) => {
    element.textContent = currentYear;
  });

  initThemeToggle();
  initScrollEffects();
  initActiveNavigation();
  initSmoothAnchors();
  initLightbox();
}

document.addEventListener('DOMContentLoaded', applySharedLayout);
