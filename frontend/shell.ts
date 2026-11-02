// Console shell: collapsible rail (remembered), phone off-canvas menu, user menu.
import { required } from './dom.js';

const root = document.documentElement;
const nav = window.suderraNav;
const phone = window.matchMedia('(max-width: 767px)');

// Desktop: collapse / expand
const toggle = required<HTMLButtonElement>(document, '[data-nav-toggle]');
const toggleLabel = required<HTMLElement>(toggle, '.sr-only');

function syncToggle(): void {
  const collapsed = root.dataset.nav === 'collapsed';
  const label = collapsed ? 'Expand menu' : 'Collapse menu';
  toggle.setAttribute('aria-expanded', String(!collapsed));
  toggle.title = label;
  toggleLabel.textContent = label;
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

// Phone: off-canvas rail
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

// User menu
const userToggle = required<HTMLButtonElement>(document, '[data-user-toggle]');
const userPanel = required<HTMLElement>(document, '#user-panel');

function setUserOpen(open: boolean): void {
  userPanel.hidden = !open;
  userToggle.setAttribute('aria-expanded', String(open));
}

userToggle.addEventListener('click', (event) => {
  event.stopPropagation();
  setUserOpen(userPanel.hidden);
});
document.addEventListener('click', (event) => {
  if (!userPanel.hidden && !userPanel.contains(event.target as Node)) setUserOpen(false);
});

document.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (!userPanel.hidden) {
    setUserOpen(false);
    userToggle.focus();
  }
  if (root.hasAttribute('data-nav-open-mobile')) {
    setMobileOpen(false);
    openButton.focus();
  }
});
