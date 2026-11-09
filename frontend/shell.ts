// Console shell: collapsible rail (remembered); below 1024px the rail is a sheet opened from the bottom bar's More
// (static/css/app.css); the popup menus.
import { bindCollapses } from './collapse.js';
import { label, required } from './dom.js';

const root = document.documentElement;
const nav = window.suderraNav;
const phone = window.matchMedia('(max-width: 1023px)');

// Desktop: collapse / expand
const toggle = required<HTMLButtonElement>(document, '[data-nav-toggle]');
const toggleLabel = required<HTMLElement>(toggle, '.sr-only');

function syncToggle(): void {
  const collapsed = root.dataset.nav === 'collapsed';
  const text = label(toggle, collapsed ? 'labelExpand' : 'labelCollapse');
  toggle.setAttribute('aria-expanded', String(!collapsed));
  toggle.title = text;
  toggleLabel.textContent = text;
}

toggle.addEventListener('click', () => {
  nav.save(root.dataset.nav === 'collapsed' ? 'open' : 'collapsed');
  nav.apply();
  syncToggle();
});
syncToggle();

// With no saved choice the rail follows the window width.
window.addEventListener('resize', () => {
  if (nav.saved() !== null) return;
  nav.apply();
  syncToggle();
});

// Below 1024px: the rail as a sheet over a scrim
const openButton = required<HTMLButtonElement>(document, '[data-nav-open]');
const scrim = required<HTMLElement>(document, '[data-nav-close]');
const rail = required<HTMLElement>(document, '#rail');

function setMobileOpen(open: boolean): void {
  root.toggleAttribute('data-nav-open-mobile', open);
  scrim.hidden = !open;
  openButton.setAttribute('aria-expanded', String(open));
  if (open) rail.querySelector<HTMLElement>('a, button')?.focus();
}

openButton.addEventListener('click', () => setMobileOpen(true));
scrim.addEventListener('click', () => setMobileOpen(false));
phone.addEventListener('change', () => setMobileOpen(false));

// Popup menus (the panel switcher, the user menu): [data-menu] holds a [data-menu-toggle] button and a
// [data-menu-panel]. One is open at a time; a click outside or Esc closes it.
interface PopupMenu {
  toggle: HTMLButtonElement;
  panel: HTMLElement;
}

const menus: PopupMenu[] = [...document.querySelectorAll<HTMLElement>('[data-menu]')].map((menu) => ({
  toggle: required<HTMLButtonElement>(menu, '[data-menu-toggle]'),
  panel: required<HTMLElement>(menu, '[data-menu-panel]'),
}));

function setMenuOpen(menu: PopupMenu, open: boolean): void {
  menu.panel.hidden = !open;
  menu.toggle.setAttribute('aria-expanded', String(open));
}

function closeMenus(except?: PopupMenu): PopupMenu | undefined {
  let closed: PopupMenu | undefined;
  for (const menu of menus) {
    if (menu !== except && !menu.panel.hidden) {
      setMenuOpen(menu, false);
      closed = menu;
    }
  }
  return closed;
}

for (const menu of menus) {
  menu.toggle.addEventListener('click', (event) => {
    event.stopPropagation();
    closeMenus(menu);
    setMenuOpen(menu, menu.panel.hidden);
  });
}
document.addEventListener('click', (event) => {
  for (const menu of menus) {
    if (!menu.panel.hidden && !menu.panel.contains(event.target as Node)) setMenuOpen(menu, false);
  }
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  closeMenus()?.toggle.focus();
  if (root.hasAttribute('data-nav-open-mobile')) {
    setMobileOpen(false);
    openButton.focus();
  }
});

// The rail's folded parts (Setup): as the person left them.
bindCollapses(document);
