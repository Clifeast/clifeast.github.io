const headerTemplate = `
  <div class="site-header__inner">
    <a class="brand" href="/">
      <img src="/assets/images/profileblack.png" alt="赏鹤阳头像" class="brand-logo" />
      <div class="brand-meta">
        <span class="brand-name">赏鹤阳 · 草树之后</span>
      </div>
    </a>
    <nav class="site-nav">
      <a href="/#about">关于</a>
      <a href="/#latest">最新</a>
      <a href="/#contact">联系</a>
      <a class="nav-digest" href="/digest/" aria-label="进入 arXiv + AGT Daily Digest">论文日报</a>
      <a class="btn btn-primary nav-cta" href="/articles/">我的文章</a>
    </nav>
  </div>
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
    .replace('href="/articles/"', `href="${ctaHref}"`)
    .replace('>我的文章<', `>${ctaLabel}<`);

  document.querySelectorAll('[data-component="site-header"]').forEach((element) => {
    element.innerHTML = headerHTML;
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
