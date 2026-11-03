// Parts of a page that the server renders again while the page is in view (Messages: the open conversation,
// the list of conversations, the menu's unread badge). There is no push yet: a timer asks for the fragment.
// Server-sent events or a WebSocket replace the timer later and ask for the same fragments.
//   data-poll="<url>"          the fragment's address
//   data-poll-every="<s>"      seconds between two requests; none while the page is hidden, one at once when it
//                              is shown again
//   data-poll-append           the fragment's rows go at the end (new messages) instead of replacing the content;
//                              the response's X-Poll-Next header is the address of the next request
//   data-scroll-end            a list that opens scrolled to its end and follows new rows while it is there
//   data-submit-on-enter       a textarea whose form is sent with Enter; Shift+Enter starts a new line
// A fragment the person may no longer read (signed out, removed from the conversation) stops its timer.

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

document.querySelectorAll<HTMLElement>('[data-scroll-end]').forEach((list) => { list.scrollTop = list.scrollHeight; });
document.querySelectorAll<HTMLElement>('[data-poll]').forEach(poll);
document.querySelectorAll<HTMLTextAreaElement>('textarea[data-submit-on-enter]').forEach(sendOnEnter);
