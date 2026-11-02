// Loaded as a classic script in <head> so the rail has its final width before the first paint.
// It also owns the rule for the rail state; shell.ts uses it through window.suderraNav.
(() => {
  const KEY = 'suderra.nav';
  const AUTO_COLLAPSE_BELOW = 1100;
  const root = document.documentElement;

  const nav: NavState = {
    saved() {
      try { return localStorage.getItem(KEY); } catch { return null; }
    },
    save(choice) {
      try { localStorage.setItem(KEY, choice); } catch { /* storage blocked: keep it for this page only */ }
    },
    apply() {
      const saved = nav.saved();
      const collapsed = saved === 'collapsed' || (saved === null && window.innerWidth < AUTO_COLLAPSE_BELOW);
      if (collapsed) root.dataset.nav = 'collapsed';
      else delete root.dataset.nav;
    },
  };

  window.suderraNav = nav;
  nav.apply();
})();
