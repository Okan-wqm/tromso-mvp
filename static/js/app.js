// Shell behaviour: collapsible rail (remembered), phone off-canvas menu, user menu.
(() => {
  const root = document.documentElement;
  const KEY = 'suderra.nav';
  const phone = window.matchMedia('(max-width: 767px)');

  const store = {
    get() { try { return localStorage.getItem(KEY); } catch (e) { return null; } },
    set(value) { try { localStorage.setItem(KEY, value); } catch (e) { /* private mode */ } },
  };

  // Desktop: collapse / expand
  const toggle = document.querySelector('[data-nav-toggle]');
  const syncToggle = () => {
    const collapsed = root.dataset.nav === 'collapsed';
    const label = collapsed ? 'Expand menu' : 'Collapse menu';
    toggle.setAttribute('aria-expanded', String(!collapsed));
    toggle.title = label;
    toggle.querySelector('.sr-only').textContent = label;
  };
  toggle.addEventListener('click', () => {
    const collapse = root.dataset.nav !== 'collapsed';
    if (collapse) root.dataset.nav = 'collapsed';
    else delete root.dataset.nav;
    store.set(collapse ? 'collapsed' : 'open');
    syncToggle();
  });
  syncToggle();

  // No saved choice: follow the window width (collapsed below 1100px)
  window.addEventListener('resize', () => {
    if (store.get() !== null) return;
    if (window.innerWidth < 1100) root.dataset.nav = 'collapsed';
    else delete root.dataset.nav;
    syncToggle();
  });

  // Phone: off-canvas rail
  const openButton = document.querySelector('[data-nav-open]');
  const scrim = document.querySelector('[data-nav-close]');
  const rail = document.getElementById('rail');
  const setMobileOpen = (open) => {
    if (open) root.setAttribute('data-nav-open-mobile', '');
    else root.removeAttribute('data-nav-open-mobile');
    scrim.hidden = !open;
    openButton.setAttribute('aria-expanded', String(open));
    if (open) rail.querySelector('a, button')?.focus();
  };
  openButton.addEventListener('click', () => setMobileOpen(true));
  scrim.addEventListener('click', () => setMobileOpen(false));
  phone.addEventListener('change', () => setMobileOpen(false));

  // User menu
  const userToggle = document.querySelector('[data-user-toggle]');
  const userPanel = document.getElementById('user-panel');
  const setUserOpen = (open) => {
    userPanel.hidden = !open;
    userToggle.setAttribute('aria-expanded', String(open));
  };
  userToggle.addEventListener('click', (event) => {
    event.stopPropagation();
    setUserOpen(userPanel.hidden);
  });
  document.addEventListener('click', (event) => {
    if (!userPanel.hidden && !userPanel.contains(event.target)) setUserOpen(false);
  });

  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    if (!userPanel.hidden) { setUserOpen(false); userToggle.focus(); }
    if (root.hasAttribute('data-nav-open-mobile')) { setMobileOpen(false); openButton.focus(); }
  });
})();
