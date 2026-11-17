// Movable, non-modal windows over a page (the monitoring cards' Deffeyes chart), and the full-screen button of a wall.
//   <button data-window="<url>" data-window-title="<title>">   opens the fragment at <url> in a window; a window of
//                              that address is raised and focused instead of a second one being made
//   #monitor-windows           where the windows go: a sibling of the polled grid, so a refresh of the grid never
//                              touches them and they show in full screen. Its data attributes: data-every (seconds
//                              between two requests of a window, default 60), data-storage-key (where the places
//                              are remembered on this device), data-stale-text and data-gone-text (the words of the
//                              window's notice, which CSS prints from data-poll-state)
//   <template id="monitor-window-template">   the window's skeleton, rendered by the server in the person's
//                              language: [data-window-title] receives the title, [data-window-body] the fragment,
//                              [data-window-handle] drags, [data-window-close] closes
//   <a data-window-load href>  inside a window: loads that fragment in the same window
//   <button data-fullscreen>   toggles the browser's full screen for the whole page (aria-pressed follows it)
// A window is not modal (the page stays alive behind it): the title bar drags it (pointer events), the arrow keys
// move it by 16 px and Shift+arrows resize it, it comes to the front when touched or focused, Escape closes it and
// gives the focus back to the button that opened it. Its body is polled by poll.ts (`watch`, data-poll-skip-same),
// which stops when the window closes; a fragment the person may no longer read (403, 404) closes the window. Where
// each window was (as fractions of the screen) is kept per device in localStorage, in a try/catch: losing it
// only centres the window again. Below 640 px a window is a sheet at the bottom of the screen (CSS) and is not
// dragged. This code has no text of its own.
//
// THE DOCK (going into a tank, owner decision 7): the same window, docked beside the cards instead of floating.
//   <a data-dock="<unit>" data-dock-code="<code>" href="<the page with ?focus=<unit>>">   on a small card's code and on
//                              a chip of the band: opens that unit's Big card in the pane; the pane that is open is
//                              replaced (one tank at a time); the link of the unit that is open closes it
//   #monitor-dock              where the pane goes (templates/monitoring/monitor.html), with data-param (the name of
//                              the address's parameter, "focus"), data-pane-url and data-grid-url (the two fragments'
//                              addresses, without a query), data-every, data-title-text ("Focus: {unit}"), and the
//                              two notices' words. The server draws the pane itself for an address that has the
//                              focus (no script needed): this code adopts it.
//   <template id="monitor-dock-template">   the pane's skeleton: [data-dock-title], [data-dock-close] (a link: its
//                              href is the page without the focus), [data-window-body]
// Opening, replacing and closing never load the page: the address follows (history.replaceState, the page's own query
// with the parameter set or taken out, so a reload or a copied link shows the same), the pane's body is polled at the
// pane's fragment (poll.ts `watch`, merged by key) and the grid is asked again at once at ITS fragment with the same
// query, so the open card is marked and every later poll of the grid carries the focus. Escape, anywhere but in a
// field or a floating window, closes the pane; the focus goes back to the open card's link (by its id: the grid's
// cards are replaced by polls). A unit that is gone closes its pane (`poll:gone`). `dock:changed` tells the wall
// (frontend/wall.ts) to share the screen anew.
import { required } from './dom.js';
import { watch } from './poll.js';

const STEP = 16;
const MIN_WIDTH = 280;
const MIN_HEIGHT = 180;
const EVERY = '60';
const REMEMBERED = 40;
const PHONE = window.matchMedia('(max-width: 639px)');
const ARROWS: Record<string, [number, number]> = {
  ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1],
};

/** A window's place as fractions of the screen, so another screen size puts it somewhere sensible. */
interface Box { x: number; y: number; w: number; h: number; }
type Places = Record<string, Box>;

interface Opened {
  element: HTMLElement;
  opener: HTMLElement | null;
  stop: () => void;
}

/** A fragment's address as one spelling (path and query), so a button's relative address and a link's absolute one name the
 *  same window. */
function norm(url: string): string {
  const parsed = new URL(url, window.location.href);
  return parsed.pathname + parsed.search;
}

function openWindows(host: HTMLElement): void {
  const template = required<HTMLTemplateElement>(document, '#monitor-window-template');
  const storageKey = host.dataset.storageKey ?? 'monitoring:windows';
  const opened = new Map<string, Opened>();
  let top = 10;

  const recall = (): Places => {
    try {
      const parsed: unknown = JSON.parse(localStorage.getItem(storageKey) ?? '{}');
      return typeof parsed === 'object' && parsed !== null ? parsed as Places : {};
    } catch {
      return {};
    }
  };
  const remember = (key: string, element: HTMLElement): void => {
    if (PHONE.matches) return;
    try {
      const places = recall();
      delete places[key];   // the newest last, so the oldest go first
      places[key] = {
        x: element.offsetLeft / window.innerWidth, y: element.offsetTop / window.innerHeight,
        w: element.offsetWidth / window.innerWidth, h: element.offsetHeight / window.innerHeight,
      };
      const keys = Object.keys(places);
      keys.slice(0, Math.max(0, keys.length - REMEMBERED)).forEach((old) => { delete places[old]; });
      localStorage.setItem(storageKey, JSON.stringify(places));
    } catch {
      // storage blocked: the window is centred next time
    }
  };

  const keyOf = (element: HTMLElement): string => [...opened].find(([, each]) => each.element === element)?.[0] ?? '';

  /** Keeps a window inside the screen. */
  const fit = (element: HTMLElement): void => {
    if (PHONE.matches) return;
    const width = Math.min(element.offsetWidth, window.innerWidth);
    const height = Math.min(element.offsetHeight, window.innerHeight);
    element.style.left = `${Math.min(Math.max(0, element.offsetLeft), window.innerWidth - width)}px`;
    element.style.top = `${Math.min(Math.max(0, element.offsetTop), window.innerHeight - height)}px`;
  };

  const place = (element: HTMLElement, key: string): void => {
    if (PHONE.matches) return;
    const box = recall()[key];
    const width = box ? Math.max(MIN_WIDTH, box.w * window.innerWidth) : Math.min(560, window.innerWidth * 0.9);
    const height = box ? Math.max(MIN_HEIGHT, box.h * window.innerHeight) : Math.min(640, window.innerHeight * 0.85);
    element.style.width = `${width}px`;
    element.style.height = `${height}px`;
    const cascade = (opened.size % 6) * STEP * 2;
    element.style.left = `${box ? box.x * window.innerWidth : (window.innerWidth - width) / 2 + cascade}px`;
    element.style.top = `${box ? box.y * window.innerHeight : (window.innerHeight - height) / 3 + cascade}px`;
    fit(element);
  };

  const raise = (element: HTMLElement): void => {
    top += 1;
    element.style.zIndex = String(top);
  };

  const close = (element: HTMLElement): void => {
    const key = keyOf(element);
    const found = opened.get(key);
    if (!found) return;
    opened.delete(key);
    found.stop();
    element.remove();
    if (found.opener?.isConnected) found.opener.focus();
  };

  const load = (element: HTMLElement, url: string): void => {
    const key = keyOf(element);
    const found = opened.get(key);
    if (!found || key === url) return;
    if (opened.has(url)) {   // that fragment has a window already: bring it forward, close this one
      raise(opened.get(url)!.element);
      opened.get(url)!.element.focus();
      return;
    }
    opened.delete(key);
    opened.set(url, found);
    required<HTMLElement>(element, '[data-window-body]').dispatchEvent(new CustomEvent('poll:now', { detail: { url } }));
  };

  const drag = (element: HTMLElement, handle: HTMLElement): void => {
    handle.addEventListener('pointerdown', (event) => {
      if (event.button !== 0 || PHONE.matches || (event.target as Element).closest('button, a')) return;
      raise(element);
      handle.setPointerCapture(event.pointerId);
      const start = { x: event.clientX, y: event.clientY, left: element.offsetLeft, top: element.offsetTop };
      const move = (moved: PointerEvent): void => {
        element.style.left = `${start.left + moved.clientX - start.x}px`;
        element.style.top = `${start.top + moved.clientY - start.y}px`;
        fit(element);
      };
      const end = (): void => {
        handle.removeEventListener('pointermove', move);
        handle.removeEventListener('pointerup', end);
        handle.removeEventListener('pointercancel', end);
        remember(keyOf(element), element);
      };
      handle.addEventListener('pointermove', move);
      handle.addEventListener('pointerup', end);
      handle.addEventListener('pointercancel', end);
    });
  };

  const create = (button: HTMLElement, url: string): void => {
    const element = (template.content.firstElementChild as HTMLElement).cloneNode(true) as HTMLElement;
    const title = button.dataset.windowTitle ?? '';
    required<HTMLElement>(element, '[data-window-title]').textContent = title;
    element.setAttribute('aria-label', title);
    const body = required<HTMLElement>(element, '[data-window-body]');
    body.dataset.poll = url;
    body.dataset.pollEvery = host.dataset.every ?? EVERY;
    body.setAttribute('data-poll-skip-same', '');
    body.dataset.staleText = host.dataset.staleText ?? '';
    body.dataset.goneText = host.dataset.goneText ?? '';
    host.append(element);
    const stop = watch(body);
    opened.set(url, { element, opener: button, stop });
    place(element, url);
    raise(element);
    drag(element, required<HTMLElement>(element, '[data-window-handle]'));
    required<HTMLElement>(element, '[data-window-close]').addEventListener('click', () => { close(element); });
    element.addEventListener('pointerdown', () => { raise(element); });
    element.addEventListener('focusin', () => { raise(element); });
    element.addEventListener('poll:gone', () => { close(element); });
    element.addEventListener('click', (event) => {
      const link = (event.target as Element).closest<HTMLAnchorElement>('a[data-window-load]');
      if (!link) return;
      event.preventDefault();
      load(element, norm(link.href));
    });
    element.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        close(element);
        return;
      }
      const arrow = ARROWS[event.key];
      if (!arrow || (event.target as Element).closest('input, select, textarea') || PHONE.matches) return;
      event.preventDefault();
      if (event.shiftKey) {
        element.style.width = `${Math.max(MIN_WIDTH, element.offsetWidth + arrow[0] * STEP)}px`;
        element.style.height = `${Math.max(MIN_HEIGHT, element.offsetHeight + arrow[1] * STEP)}px`;
      } else {
        element.style.left = `${element.offsetLeft + arrow[0] * STEP}px`;
        element.style.top = `${element.offsetTop + arrow[1] * STEP}px`;
      }
      fit(element);
      remember(keyOf(element), element);
    });
    element.addEventListener('pointerup', () => { remember(keyOf(element), element); });   // after a native resize
    body.dispatchEvent(new CustomEvent('poll:now'));
    element.focus();
  };

  document.addEventListener('click', (event) => {
    const button = (event.target as Element).closest<HTMLElement>('[data-window]');
    if (!button || !host.isConnected) return;
    event.preventDefault();
    const url = norm(button.dataset.window ?? '');
    const found = opened.get(url);
    if (found) {
      raise(found.element);
      found.element.focus();
    } else if (url) {
      create(button, url);
    }
  });
  window.addEventListener('resize', () => { opened.forEach((each) => { fit(each.element); }); });
}

function fullScreen(button: HTMLElement): void {
  button.addEventListener('click', () => {
    const request = document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
    request.catch(() => undefined);   // refused (a frame, a policy): the page stays as it is
  });
  document.addEventListener('fullscreenchange', () => {
    button.setAttribute('aria-pressed', String(document.fullscreenElement !== null));
  });
}

/** The pane of the unit gone into (see THE DOCK above). */
function openDock(pane: HTMLElement): void {
  const template = required<HTMLTemplateElement>(document, '#monitor-dock-template');
  const param = pane.dataset.param ?? 'focus';
  let stop: () => void = () => undefined;

  const changed = (): void => { document.dispatchEvent(new CustomEvent('dock:changed')); };
  const current = (): HTMLElement | null => pane.querySelector<HTMLElement>('.monitor-window');
  const unitOf = (): string => current()?.dataset.dockUnit ?? '';

  /** The page's own query with the focus on `unit` ('' : taken out). */
  const queryFor = (unit: string): string => {
    const query = new URLSearchParams(window.location.search);
    if (unit) query.set(param, unit);
    else query.delete(param);
    return query.toString();
  };
  const withQuery = (base: string, query: string): string => (query ? `${base}?${query}` : base);

  /** The address and the grid follow the pane: the page's address without a load, the grid's fragment at once. */
  const follow = (unit: string): void => {
    const query = queryFor(unit);
    window.history.replaceState(window.history.state, '', withQuery(window.location.pathname, query));
    const cards = document.querySelector<HTMLElement>('.monitor-grid[data-poll]');
    cards?.dispatchEvent(new CustomEvent('poll:now', { detail: { url: withQuery(pane.dataset.gridUrl ?? '', query) } }));
  };

  const wire = (section: HTMLElement): void => {
    const body = required<HTMLElement>(section, '[data-window-body]');
    stop = watch(body);                                    // (a pane the server drew is watched already: the same stop)
    section.addEventListener('poll:gone', () => { close(false); });
    section.addEventListener('poll:merged', changed);      // its card came, or changed its measure
  };

  const close = (refocus: boolean): void => {
    const section = current();
    if (!section) return;
    const unit = unitOf();
    stop();
    stop = () => undefined;
    section.remove();
    follow('');
    changed();
    if (refocus) document.getElementById(`open-${unit}`)?.focus({ preventScroll: true });
  };

  const open = (unit: string, code: string): void => {
    current()?.remove();
    stop();
    const section = (template.content.firstElementChild as HTMLElement).cloneNode(true) as HTMLElement;
    const title = (pane.dataset.titleText ?? '{unit}').replace('{unit}', code);
    section.dataset.dockUnit = unit;
    section.setAttribute('aria-label', title);
    required<HTMLElement>(section, '[data-dock-title]').textContent = title;
    const closer = required<HTMLAnchorElement>(section, '[data-dock-close]');
    closer.id = 'dock-close';
    closer.href = withQuery(window.location.pathname, queryFor(''));
    const body = required<HTMLElement>(section, '[data-window-body]');
    body.dataset.poll = withQuery(pane.dataset.paneUrl ?? '', queryFor(unit));
    body.dataset.pollEvery = pane.dataset.every ?? EVERY;
    body.dataset.pollMerge = 'data-key';
    body.dataset.staleText = pane.dataset.staleText ?? '';
    body.dataset.goneText = pane.dataset.goneText ?? '';
    pane.append(section);
    wire(section);
    follow(unit);
    changed();
    body.dispatchEvent(new CustomEvent('poll:now'));
    section.focus({ preventScroll: true });
  };

  const adopted = current();
  if (adopted) wire(adopted);

  document.addEventListener('click', (event) => {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('[data-dock-close]') && pane.contains(target)) {
      event.preventDefault();
      close(true);
      return;
    }
    const link = target?.closest<HTMLElement>('[data-dock]');
    if (!link || event.defaultPrevented) return;
    const mouse = event as MouseEvent;
    if (mouse.button !== 0 || mouse.ctrlKey || mouse.metaKey || mouse.shiftKey || mouse.altKey) return;   // a new tab is the link's own
    event.preventDefault();
    const unit = link.dataset.dock ?? '';
    if (unit && unit === unitOf() && link.id === `open-${unit}`) close(true);       // the open card's link closes it
    else if (unit && unit === unitOf()) current()?.focus({ preventScroll: true });   // a chip of the unit that is open
    else if (unit) open(unit, link.dataset.dockCode ?? link.textContent?.trim() ?? '');
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape' || event.defaultPrevented || !current()) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('input, select, textarea, [contenteditable], #monitor-windows .monitor-window, dialog')) return;
    event.preventDefault();
    close(true);
  });
}

const host = document.getElementById('monitor-windows');
if (host) openWindows(host);
const pane = document.getElementById('monitor-dock');
if (pane && document.getElementById('monitor-dock-template')) openDock(pane);
document.querySelectorAll<HTMLElement>('[data-fullscreen]').forEach(fullScreen);
