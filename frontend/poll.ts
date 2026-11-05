// Parts of a page that the server renders again while the page is in view (Messages: the open conversation,
// the list of conversations, the menu's unread badge; the water calculator's results as its form changes; the
// monitoring grid and its windows). There is no push yet: a timer, or a change of a form, asks for the fragment.
// Server-sent events or a WebSocket replace the timer later and ask for the same fragments. THE one
// implementation of polling: `watch(element)` is exported for the code that makes an element later (windows.ts).
//   data-poll="<url>"          the fragment's address
//   data-poll-every="<s>"      seconds between two requests, each wait a little shorter or longer by chance so
//                              screens never line up; none while the page is hidden, one at once when it is shown
//                              again; after a failure the wait doubles, up to a minute
//   data-poll-append           the fragment's rows go at the end (new messages) instead of replacing the content;
//                              the response's X-Poll-Next header is the address of the next request
//   data-poll-merge="<attr>"   the fragment's elements each carry <attr> (a key); the one of the page with the same
//                              key is replaced only when its markup differs, a new key is inserted where the
//                              fragment has it, a key the fragment lacks goes, focus stays on the element of the
//                              same id; a fragment with an element without the key replaces the whole content
//   data-poll-skip-same        an answer equal to the previous one changes nothing (a chart keeps its scroll)
//   data-poll-state="live|stale|gone"
//                              set by this script: live after an answer, stale after two failures in a row (the
//                              server cannot be reached), gone when the person may no longer read it (401, 403,
//                              404 or a redirect to sign-in); the page's CSS says so in its own words. A
//                              `poll:gone` event (detail.status) bubbles from the element when it is gone.
//   `poll:now` event           asks at once; detail.url (optional) is the address to ask from now on
//   `poll:merged` event        sent by a merged element after each merge: detail.replaced ({old, node}), inserted,
//                              removed (what frontend/announce.ts reads a state's rise from)
//   data-poll-url="<url>"      on a link inside a polled element: a click asks that element for <url> at once (the
//                              state the link stands for, e.g. a card drawn in detail) and the address bar follows
//                              the link's href (history.replaceState); without the script the link navigates
//   data-scroll-end            a list that opens scrolled to its end and follows new rows while it is there
//   data-submit-on-enter       a textarea whose form is sent with Enter; Shift+Enter starts a new line
//   data-live="<url>"          a GET form whose results the server draws again as it is filled in: on a change (a
//                              check box or a choice at once, typing after a pause) the fragment at <url> with the
//                              form's values is asked for, a request still on its way is dropped, every
//                              [data-live-part="<name>"] of the answer replaces the page's part of that name, the
//                              answer's [data-error-for="<field>"] lists go under their fields (the others lose
//                              theirs), and the address follows the form (history.replaceState), so a link opens
//                              the same view. The fields are never replaced: focus and caret stay where they are.
//                              A field with data-autosubmit sends the form instead (the page is drawn anew);
//                              without the script the form is sent by its <noscript> button.
//   data-live-delay="<ms>"     the pause after typing before asking (default 300)
// An element that leaves the page stops being asked for; a request takes at most 20 seconds.

// How close to the end (px) a list must be to follow new rows.
const NEAR_END = 48;
// Answers after which asking again is pointless.
const GONE = new Set([401, 403, 404]);
// How long (ms) a request may take, and the longest wait (ms) after failures.
const TIMEOUT = 20000;
const SLOWEST = 60000;
// A wait is its interval times 1 ± JITTER.
const JITTER = 0.1;
// Failures in a row after which the element says it is stale.
const STALE_AFTER = 2;

type PollState = 'live' | 'stale' | 'gone';

function atEnd(list: HTMLElement): boolean {
  return list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_END;
}

/** What a merge did: the children replaced (the old node and the new), inserted and removed. */
export interface Merged {
  replaced: { old: Element; node: Element }[];
  inserted: Element[];
  removed: Element[];
}

/** Replaces `container`'s keyed children by those of `html`: a child of the same key is kept when its markup is the
 *  same and replaced when it differs, a new key is inserted at its place in the answer, a child the answer lacks is removed (keyed or not).
 *  Null (nothing done) when an element of the answer has no key: the caller then replaces everything. */
function merge(container: HTMLElement, html: string, key: string): Merged | null {
  const template = document.createElement('template');
  template.innerHTML = html.trim();
  const incoming = Array.from(template.content.children) as HTMLElement[];
  if (incoming.some((node) => !node.hasAttribute(key))) return null;
  const done: Merged = { replaced: [], inserted: [], removed: [] };
  const focused = document.activeElement instanceof HTMLElement && container.contains(document.activeElement)
    ? document.activeElement.id : '';
  const current = new Map<string, HTMLElement>();
  for (const child of Array.from(container.children) as HTMLElement[]) {
    const id = child.getAttribute(key);
    if (id !== null) current.set(id, child);
  }
  const kept = new Set<Element>();
  incoming.forEach((node, index) => {
    const id = node.getAttribute(key) ?? '';
    const old = current.get(id);
    let target = node;
    if (old !== undefined) {
      if (old.outerHTML === node.outerHTML) target = old;
      else {
        old.replaceWith(node);
        done.replaced.push({ old, node });
      }
    } else {
      done.inserted.push(node);
    }
    kept.add(target);
    const here = container.children[index] ?? null;
    if (here !== target) container.insertBefore(target, here);
  });
  Array.from(container.children).forEach((child) => {
    if (!kept.has(child)) {
      child.remove();
      done.removed.push(child);
    }
  });
  if (focused && document.activeElement?.id !== focused) document.getElementById(focused)?.focus();
  return done;
}

// The elements asked for, so one listener serves them all and a gone element is let go.
interface Watched { element: HTMLElement; refresh: () => Promise<void>; }
const watching = new Set<Watched>();
const stoppers = new WeakMap<HTMLElement, () => void>();
let listening = false;

function shown(): void {
  if (document.visibilityState !== 'visible') return;
  watching.forEach((each) => {
    if (each.element.isConnected) void each.refresh();
    else watching.delete(each);
  });
}

/** Starts asking for the fragment of `element` (data-poll, data-poll-every, and the attributes above); returns the
 *  function that stops it. An element asked for already is not asked for twice. */
export function watch(element: HTMLElement): () => void {
  const already = stoppers.get(element);
  if (already) return already;
  let url = element.dataset.poll ?? '';
  const seconds = Number(element.dataset.pollEvery);
  if (!url || !(seconds > 0)) return () => undefined;
  const append = element.hasAttribute('data-poll-append');
  const mergeBy = element.dataset.pollMerge ?? '';
  const skipSame = element.hasAttribute('data-poll-skip-same');
  const dropped = new WeakSet<AbortController>();
  let running: AbortController | null = null;
  let failures = 0;
  let timer = 0;
  let last = '';
  let stopped = false;

  const state = (value: PollState): void => { element.dataset.pollState = value; };
  const failed = (): void => {
    failures += 1;   // the next wait is longer
    if (failures >= STALE_AFTER) state('stale');
  };
  const schedule = (): void => {
    window.clearTimeout(timer);
    if (stopped) return;
    const interval = Math.min(seconds * 1000 * 2 ** failures, Math.max(SLOWEST, seconds * 1000));
    timer = window.setTimeout(() => { void refresh(); }, interval * (1 + JITTER * (Math.random() * 2 - 1)));
  };
  const stop = (): void => {
    stopped = true;
    window.clearTimeout(timer);
    running?.abort();
    watching.delete(entry);
    stoppers.delete(element);
  };
  const gone = (status: number): void => {
    stop();
    state('gone');
    element.dispatchEvent(new CustomEvent('poll:gone', { bubbles: true, detail: { status } }));
  };
  const apply = (html: string): void => {
    if (append) {
      const follow = atEnd(element);
      element.insertAdjacentHTML('beforeend', html);
      if (follow) element.scrollTop = element.scrollHeight;
    } else if (mergeBy) {
      const done = merge(element, html, mergeBy);
      if (done === null) element.innerHTML = html.trim();
      else element.dispatchEvent(new CustomEvent<Merged>('poll:merged', { bubbles: true, detail: done }));
    } else if (!(skipSame && html === last)) {
      element.innerHTML = html.trim();
    }
    last = html;
  };

  async function refresh(): Promise<void> {
    if (stopped) return;
    if (!element.isConnected) {
      stop();
      return;
    }
    if (running || document.visibilityState !== 'visible') return;
    const request = new AbortController();
    running = request;
    const timeout = window.setTimeout(() => request.abort(), TIMEOUT);
    try {
      const response = await fetch(url, { credentials: 'same-origin', signal: request.signal });
      if (response.redirected || GONE.has(response.status)) {
        gone(response.status);
        return;
      }
      if (!response.ok) {   // a server error: asked for again, after a longer wait
        failed();
        return;
      }
      url = response.headers.get('X-Poll-Next') ?? url;
      failures = 0;
      state('live');
      if (response.status === 204) return;
      const html = await response.text();
      if (!dropped.has(request)) apply(html);
    } catch {
      if (!dropped.has(request)) failed();   // offline, or too slow
    } finally {
      window.clearTimeout(timeout);
      if (running === request) running = null;
      schedule();
    }
  }

  const entry: Watched = { element, refresh };
  element.addEventListener('poll:now', (event) => {
    if (stopped) return;
    const next = (event as CustomEvent<{ url?: string } | null>).detail?.url;
    if (next) {
      url = next;
      last = '';
    }
    if (running) {
      dropped.add(running);
      running.abort();
      running = null;
    }
    void refresh();
  });
  watching.add(entry);
  stoppers.set(element, stop);
  if (!listening) {
    document.addEventListener('visibilitychange', shown);
    listening = true;
  }
  state('live');
  schedule();
  return stop;
}

function sendOnEnter(area: HTMLTextAreaElement): void {
  area.addEventListener('keydown', (event) => {
    if (event.key !== 'Enter' || event.shiftKey || event.isComposing) return;
    event.preventDefault();
    if (area.value.trim()) area.form?.requestSubmit();
  });
}

// ---- live forms --------------------------------------------------------------------------------------------
const TYPING_PAUSE = 300;

/** The form's values as an address's query: what the form would send (empty fields and all). */
function queryOf(form: HTMLFormElement): string {
  const query = new URLSearchParams();
  for (const [name, value] of new FormData(form)) {
    if (typeof value === 'string') query.append(name, value);
  }
  return query.toString();
}

/** Each [data-live-part] of the answer replaces the page's part of the same name; focus inside one stays on
 *  the element of the same id. */
function swapParts(answer: DocumentFragment): void {
  answer.querySelectorAll<HTMLElement>('[data-live-part]').forEach((part) => {
    const current = document.querySelector(`[data-live-part="${CSS.escape(part.dataset.livePart ?? '')}"]`);
    if (!current) return;
    const focused = document.activeElement instanceof HTMLElement && current.contains(document.activeElement)
      ? document.activeElement.id : '';
    current.replaceWith(part);
    if (focused) document.getElementById(focused)?.focus();
  });
}

/** The answer's error lists go under their fields; a field without one loses its own. */
function showErrors(form: HTMLFormElement, answer: DocumentFragment): void {
  const lists = new Map<string, HTMLElement>();
  answer.querySelectorAll<HTMLElement>('[data-error-for]').forEach((list) => {
    lists.set(list.dataset.errorFor ?? '', list);
  });
  form.querySelectorAll<HTMLElement>('.field').forEach((box) => {
    const field = box.querySelector<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>(
      'input[name], select[name], textarea[name]');
    if (!field) return;
    const list = lists.get(field.name);
    box.classList.toggle('has-error', list !== undefined);
    box.querySelectorAll('input, select, textarea').forEach((input) => {
      if (list) input.setAttribute('aria-invalid', 'true');
      else input.removeAttribute('aria-invalid');
    });
    box.querySelectorAll('.errorlist').forEach((old) => old.remove());
    if (list) box.append(list);
  });
}

function live(form: HTMLFormElement): void {
  const url = form.dataset.live ?? '';
  if (!url) return;
  const pause = Number(form.dataset.liveDelay) || TYPING_PAUSE;
  const page = new URL(form.action, window.location.href);
  let timer = 0;
  let pending: AbortController | null = null;

  const refresh = async (): Promise<void> => {
    window.clearTimeout(timer);
    pending?.abort();
    const request = new AbortController();
    pending = request;
    const query = queryOf(form);
    form.setAttribute('aria-busy', 'true');
    try {
      const response = await fetch(`${url}?${query}`, { credentials: 'same-origin', signal: request.signal });
      if (response.redirected || GONE.has(response.status)) {
        window.location.assign(`${page.pathname}?${query}`);   // signed out or no longer allowed: the page says so
        return;
      }
      if (!response.ok) return;   // a passing server error: the next change asks again
      const template = document.createElement('template');
      template.innerHTML = await response.text();
      if (request.signal.aborted) return;
      swapParts(template.content);
      showErrors(form, template.content);
      window.history.replaceState(window.history.state, '', `${page.pathname}?${query}`);
    } catch {
      // dropped for a newer request, or offline for a moment: the next change asks again
    } finally {
      if (pending === request) {
        pending = null;
        form.removeAttribute('aria-busy');
      }
    }
  };

  const typed = (target: EventTarget | null): boolean =>
    (target instanceof HTMLInputElement && !['checkbox', 'radio'].includes(target.type)) ||
    target instanceof HTMLTextAreaElement;

  form.addEventListener('input', (event) => {
    if (!typed(event.target)) return;
    window.clearTimeout(timer);
    timer = window.setTimeout(() => { void refresh(); }, pause);
  });
  form.addEventListener('change', (event) => {
    const field = event.target;
    if (field instanceof Element && field.matches('[data-autosubmit]')) return;   // it sends the form itself
    void refresh();
  });
}

document.addEventListener('click', (event) => {
  const link = (event.target as Element).closest<HTMLAnchorElement>('a[data-poll-url]');
  const polled = link?.closest<HTMLElement>('[data-poll]');
  if (!link || !polled || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey) return;
  event.preventDefault();
  polled.dispatchEvent(new CustomEvent('poll:now', { detail: { url: link.dataset.pollUrl } }));
  window.history.replaceState(window.history.state, '', link.href);
});
document.querySelectorAll<HTMLElement>('[data-scroll-end]').forEach((list) => { list.scrollTop = list.scrollHeight; });
document.querySelectorAll<HTMLElement>('[data-poll]').forEach((element) => { watch(element); });
document.querySelectorAll<HTMLTextAreaElement>('textarea[data-submit-on-enter]').forEach(sendOnEnter);
document.querySelectorAll<HTMLFormElement>('form[data-live]').forEach(live);
