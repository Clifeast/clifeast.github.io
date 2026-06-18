const headerTemplate = `
  <div class="site-header__inner">
    <a class="brand" href="/">
      <img src="/assets/images/profileblack.png" alt="赏鹤阳头像" class="brand-logo" />
      <div class="brand-meta">
        <span class="brand-name brand-name--full">赏鹤阳 · 草树之后</span>
        <span class="brand-name brand-name--compact">草树之后</span>
      </div>
    </a>
    <nav class="site-nav">
      <a href="/#about">关于</a>
      <a href="/#latest">最新</a>
      <a href="/#contact">联系</a>
      <a class="nav-digest" href="/digest/" aria-label="进入 arXiv + AGT Daily Digest">论文日报</a>
      <a class="btn btn-primary nav-cta" href="/articles/">我的文章</a>
    </nav>
    <button class="site-menu-toggle" type="button" aria-label="打开导航菜单" aria-expanded="false"
      aria-controls="site-menu-drawer">
      <span></span><span></span><span></span>
    </button>
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
      <a href="/digest/">论文日报</a>
      <a class="site-menu-drawer__cta" href="/articles/">我的文章</a>
    </nav>
  </aside>
`;

const footerTemplate = `
  <p>© <span data-current-year></span> 赏鹤阳 · 草树之后</p>
`;

function applySharedLayout() {
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
}

document.addEventListener('DOMContentLoaded', applySharedLayout);
