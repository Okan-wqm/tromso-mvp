// Parts of a page that the server renders again while the page is in view (Messages: the open conversation,
// the list of conversations, the menu's unread badge; the water calculator's results as its form changes).
// There is no push yet: a timer, or a change of a form, asks for the fragment. Server-sent events or a
// WebSocket replace the timer later and ask for the same fragments.
//   data-poll="<url>"          the fragment's address
//   data-poll-every="<s>"      seconds between two requests; none while the page is hidden, one at once when it
//                              is shown again
//   data-poll-append           the fragment's rows go at the end (new messages) instead of replacing the content;
//                              the response's X-Poll-Next header is the address of the next request
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
// A fragment the person may no longer read (signed out, removed from the conversation) stops its timer; a live
// form then opens its own page, which says why.

// How close to the end (px) a list must be to follow new rows.
const NEAR_END = 48;
// Answers after which asking again is pointless.
const GONE = new Set([401, 403, 404]);

function atEnd(list: HTMLElement): boolean {
  return list.scrollHeight - list.scrollTop - list.clientHeight < NEAR_END;
}

function poll(element: HTMLElement): void {
  let url = element.dataset.poll ?? '';
  const seconds = Number(element.dataset.pollEvery);
  if (!url || !(seconds > 0)) return;
  const append = element.hasAttribute('data-poll-append');
  let busy = false;
  let timer = 0;

  const refresh = async (): Promise<void> => {
    if (busy || document.visibilityState !== 'visible') return;
    busy = true;
    try {
      const response = await fetch(url, { credentials: 'same-origin' });
      if (response.redirected || GONE.has(response.status)) {
        window.clearInterval(timer);
        return;
      }
      if (!response.ok) return;   // a passing server error: the next tick asks again
      url = response.headers.get('X-Poll-Next') ?? url;
      if (response.status === 204) return;
      const html = await response.text();
      if (append) {
        const follow = atEnd(element);
        element.insertAdjacentHTML('beforeend', html);
        if (follow) element.scrollTop = element.scrollHeight;
      } else {
        element.innerHTML = html.trim();
      }
    } catch {
      // offline for a moment: the next tick asks again
    } finally {
      busy = false;
    }
  };

  timer = window.setInterval(() => { void refresh(); }, seconds * 1000);
  document.addEventListener('visibilitychange', () => { void refresh(); });
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

document.querySelectorAll<HTMLElement>('[data-scroll-end]').forEach((list) => { list.scrollTop = list.scrollHeight; });
document.querySelectorAll<HTMLElement>('[data-poll]').forEach(poll);
document.querySelectorAll<HTMLTextAreaElement>('textarea[data-submit-on-enter]').forEach(sendOnEnter);
document.querySelectorAll<HTMLFormElement>('form[data-live]').forEach(live);
