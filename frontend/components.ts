// Shared page behaviour, driven by data attributes so every tab uses the same parts:
//   data-modal            a link that opens its page in the dialog (core.crud.render_page)
//   data-modal-close      closes the dialog (a plain link when the page is not in a dialog)
//   data-tabs/-tab/-panel inner tabs; without this script every panel simply shows
//   data-uppercase        upper-cases a text input while typing
//   data-autosubmit       a filter select that applies on change
//   data-formset          a list of rows with "add row" and, for [data-primary], one ticked box
//   data-requires="<id>"  a check box that needs another one (e.g. Edit needs Read in the role matrix)
// Everything is set up on the page and again on whatever the dialog loads.
import { required } from './dom.js';

// ---- inner tabs ----------------------------------------------------------------------------
function initTabs(root: ParentNode & Element | Document): void {
  const tablist = root.querySelector<HTMLElement>('[data-tabs]');
  if (!tablist) return;
  const tabs = [...tablist.querySelectorAll<HTMLButtonElement>('[data-tab]')];
  const panels = [...root.querySelectorAll<HTMLElement>('[data-panel]')];
  if (tabs.length === 0) return;

  const select = (key: string, focus = false): void => {
    for (const tab of tabs) {
      const on = tab.dataset.tab === key;
      tab.setAttribute('aria-selected', String(on));
      tab.tabIndex = on ? 0 : -1;
      if (on && focus) tab.focus();
    }
    for (const panel of panels) panel.hidden = panel.dataset.panel !== key;
  };

  tablist.hidden = false;
  (root instanceof Document ? root.body : root).classList.add('js-tabs');
  tabs.forEach((tab, i) => {
    tab.addEventListener('click', () => select(tab.dataset.tab ?? ''));
    tab.addEventListener('keydown', (event) => {
      const step = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0;
      if (step) select(tabs[(i + step + tabs.length) % tabs.length].dataset.tab ?? '', true);
    });
  });
  const firstError = panels.find((panel) => panel.hasAttribute('data-has-errors'));
  select(tablist.dataset.open || firstError?.dataset.panel || tabs[0].dataset.tab || '');
}

// ---- upper-case inputs ---------------------------------------------------------------------
function initUppercase(root: ParentNode): void {
  root.querySelectorAll<HTMLInputElement>('[data-uppercase]').forEach((input) => {
    input.addEventListener('input', () => {
      const { selectionStart, selectionEnd } = input;
      input.value = input.value.toUpperCase();
      input.setSelectionRange(selectionStart, selectionEnd);
    });
  });
}

// ---- row lists (Django formsets) -----------------------------------------------------------
function initFormsets(root: ParentNode): void {
  root.querySelectorAll<HTMLFormElement>('[data-formset]').forEach((formset) => {
    const rows = required<HTMLElement>(formset, '[data-rows]');
    const template = required<HTMLTemplateElement>(formset, '[data-row-template]');
    const total = required<HTMLInputElement>(formset, 'input[name$="-TOTAL_FORMS"]');
    const empty = formset.querySelector<HTMLElement>('[data-empty]');

    const wire = (row: Element): void => {
      const remove = row.querySelector<HTMLInputElement>('input[name$="-DELETE"]');
      if (!remove) return;
      const sync = (): void => { row.classList.toggle('is-removed', remove.checked); };
      remove.addEventListener('change', sync);
      sync();
    };
    rows.querySelectorAll('[data-row]').forEach(wire);

    // Only one primary row: ticking one clears the others.
    formset.addEventListener('change', (event) => {
      const box = event.target;
      if (!(box instanceof HTMLInputElement) || !box.matches('[data-primary]') || !box.checked) return;
      formset.querySelectorAll<HTMLInputElement>('[data-primary]').forEach((other) => {
        if (other !== box) other.checked = false;
      });
    });

    required<HTMLButtonElement>(formset, '[data-add-row]').addEventListener('click', () => {
      const index = Number(total.value);
      rows.insertAdjacentHTML('beforeend', template.innerHTML.replace(/__prefix__/g, String(index)));
      total.value = String(index + 1);
      if (empty) empty.hidden = true;
      const row = rows.lastElementChild;
      if (!row) return;
      wire(row);
      row.querySelector<HTMLElement>('input:not([type="hidden"])')?.focus();
    });
  });
}

// ---- check boxes that need another one ----------------------------------------------------
// Ticking a [data-requires] box ticks the box it names; unticking that box unticks it again.
// The server applies the same rule, so this only keeps the form honest while editing.
function initRequires(root: ParentNode): void {
  root.querySelectorAll<HTMLInputElement>('input[data-requires]').forEach((box) => {
    const needed = required<HTMLInputElement>(root, `#${CSS.escape(box.dataset.requires ?? '')}`);
    box.addEventListener('change', () => { if (box.checked) needed.checked = true; });
    needed.addEventListener('change', () => { if (!needed.checked) box.checked = false; });
  });
}

// ---- filters that apply as soon as they change ----------------------------------------------
function initAutosubmit(root: ParentNode): void {
  root.querySelectorAll<HTMLSelectElement>('select[data-autosubmit]').forEach((select) => {
    select.addEventListener('change', () => select.form?.requestSubmit());
  });
}

function init(root: Element | Document): void {
  initTabs(root);
  initUppercase(root);
  initFormsets(root);
  initRequires(root);
  initAutosubmit(root);
}

// ---- dialog --------------------------------------------------------------------------------
class Modal {
  private readonly content: HTMLElement;
  private changed = false;   // something was saved while open: reload the page on close

  constructor(private readonly dialog: HTMLDialogElement) {
    this.content = required<HTMLElement>(dialog, '[data-modal-content]');

    document.addEventListener('click', (event) => {
      const target = event.target as Element;
      const opener = target.closest<HTMLAnchorElement>('a[data-modal]');
      if (opener && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey) {
        event.preventDefault();
        void this.load(opener.href);
        return;
      }
      if (target.closest('[data-modal-close]') && this.dialog.contains(target)) {
        event.preventDefault();
        this.dialog.close();
      }
    });
    this.content.addEventListener('submit', (event) => {
      const form = event.target as HTMLFormElement;
      if (form.method.toLowerCase() !== 'post') return;
      event.preventDefault();
      void this.load(form.action, { method: 'POST', body: new FormData(form) });
    });
    dialog.addEventListener('click', (event) => {
      if (event.target === dialog) dialog.close();   // a click on the backdrop
    });
    dialog.addEventListener('close', () => {
      this.content.replaceChildren();
      if (this.changed) window.location.reload();
      this.changed = false;
    });
  }

  async load(url: string, options: RequestInit = {}): Promise<void> {
    const response = await fetch(url, { ...options, credentials: 'same-origin', headers: { 'X-Modal': '1' } });
    if (response.redirected && new URL(response.url).pathname.startsWith('/accounts/login')) {
      window.location.assign(response.url);   // signed out meanwhile
      return;
    }
    const redirectTo = response.headers.get('X-Modal-Redirect');
    if (redirectTo) {
      window.location.assign(redirectTo);
      return;
    }
    const next = response.headers.get('X-Modal-Load');
    if (next) {
      this.changed = true;
      await this.load(next);
      return;
    }
    if (response.status === 403) {
      this.content.innerHTML = '<div class="modal-body"><p class="form-error">You do not have permission to do this.</p></div>';
    } else {
      this.content.innerHTML = await response.text();
    }
    init(this.content);
    if (!this.dialog.open) this.dialog.showModal();
    this.content
      .querySelector<HTMLElement>('.has-error input, .has-error select, input:not([type="hidden"]), select, textarea, button')
      ?.focus();
  }
}

const dialog = document.querySelector<HTMLDialogElement>('dialog#modal');
if (dialog) new Modal(dialog);
init(document);
