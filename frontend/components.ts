// Shared page behaviour, driven by data attributes so every tab uses the same parts:
//   data-modal            a link that opens its page in the dialog (core.crud.render_page)
//   data-modal-close      closes the dialog (a plain link when the page is not in a dialog)
//   data-tabs/-tab/-panel inner tabs; without this script every panel simply shows
//   data-uppercase        upper-cases a text input while typing
//   data-autosubmit       a filter select that applies on change
//   data-depends-on       a select whose options, or a list whose rows, belong to another field's value (data-group)
//   data-refresh          a field that changes the form itself: the server renders the form again with what was entered
//   data-links            a list of links (core.links.LinkList): one ticked box is marked as the primary one
//   data-omit-empty       a GET form that leaves its empty fields out of the address it builds (the database viewer's filters)
//   data-formset          a list of rows with "add row" and, for [data-primary], one ticked box
//   data-requires="<id>"  a check box that needs another one (e.g. Edit needs Read in the role matrix)
//   data-print            a button, hidden without this script, that prints the page (the browser's Print does
//                         the same without it)
// The code has no UI text of its own: the templates render every text into a data attribute (e.g. the
// dialog's data-forbidden), translated by the server, and `label()` reads it.
// Everything is set up on the page and again on whatever the dialog loads.
import { label, required } from './dom.js';

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

  // A link to a field in a hidden panel (a form's list of wrong values) opens that panel first.
  root.addEventListener('click', (event) => {
    const link = event.target instanceof Element ? event.target.closest('a[href^="#"]') : null;
    if (!(link instanceof HTMLAnchorElement) || link.hash.length < 2) return;
    const target = document.getElementById(decodeURIComponent(link.hash.slice(1)));
    const panel = target?.closest<HTMLElement>('[data-panel]');
    if (!target || !panel || !panels.includes(panel)) return;
    event.preventDefault();
    select(panel.dataset.panel ?? '');
    target.focus();
  });
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

// ---- choices that belong to another field's value --------------------------------------------
// A production department belongs to a site: after the site is chosen only its departments are
// offered, and a choice that no longer fits is cleared. The options of a select, or the rows of a list
// of check boxes, carry data-group: the value, or the space-separated values, of the other field they
// belong to. The server checks the same rule; this only guides.
function initDependents(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('[data-depends-on]').forEach((dependent) => {
    const source = dependent.closest('form')?.elements.namedItem(dependent.dataset.dependsOn ?? '');
    if (!(source instanceof HTMLSelectElement || source instanceof HTMLInputElement)) return;
    const fits = (item: HTMLElement): boolean =>
      source.value !== '' && (item.dataset.group ?? '').split(' ').includes(source.value);

    const fitSelect = (select: HTMLSelectElement): void => {
      for (const option of select.options) {
        const shown = option.value === '' || fits(option);
        option.hidden = !shown;
        option.disabled = !shown;
      }
      if (select.selectedOptions[0]?.disabled) select.value = '';
    };
    const fitRows = (): void => {
      const rows = [...dependent.querySelectorAll<HTMLElement>('[data-group]')];
      for (const row of rows) {
        row.hidden = !fits(row);
        row.querySelectorAll<HTMLInputElement | HTMLSelectElement>('input, select').forEach((input) => {
          input.disabled = row.hidden;
          if (row.hidden && input instanceof HTMLInputElement) input.checked = false;
        });
      }
      const none = dependent.querySelector<HTMLElement>('[data-none]');
      if (none) none.hidden = rows.some((row) => !row.hidden);
    };
    const fit = (): void => {
      if (dependent instanceof HTMLSelectElement) fitSelect(dependent);
      else fitRows();
    };
    source.addEventListener('change', fit);
    fit();
  });
}

// ---- fields that change the form itself ----------------------------------------------------------
// data-refresh="<marker>": the field decides which other fields the form has (an equipment type, its
// specifications). After a change the form is posted with the marker, and the server renders it again
// with everything entered so far, saving nothing: into the dialog, or as the page. The values go in the
// request body, never in the address. The marker's value is the field's name, so the form comes back open
// on that field's tab.
function initRefresh(root: ParentNode): void {
  root.querySelectorAll<HTMLInputElement | HTMLSelectElement>('[data-refresh]').forEach((field) => {
    field.addEventListener('change', () => {
      const form = field.form;
      const marker = field.dataset.refresh;
      if (!form || !marker) return;
      if (modal?.holds(form)) {
        const data = new FormData(form);
        data.set(marker, field.name);
        void modal.load(form.action, { method: 'POST', body: data }).then(() => modal?.focus(field.name));
        return;
      }
      const input = document.createElement('input');
      input.type = 'hidden';
      input.name = marker;
      input.value = field.name;
      form.append(input);
      form.submit();
    });
  });
}

// ---- link lists (core.links.LinkList) ----------------------------------------------------------
// One radio button marks the primary link among the ticked boxes: the first box ticked gets it, and
// unticking the marked one passes it on; marking an unticked row ticks its box. The server applies the
// same rule; this only keeps the form honest while editing.
function initLinkLists(root: ParentNode): void {
  root.querySelectorAll<HTMLElement>('[data-links]').forEach((list) => {
    const rows = [...list.querySelectorAll<HTMLElement>('[data-link]')];
    const box = (row: HTMLElement): HTMLInputElement | null => row.querySelector('input[type="checkbox"]');
    const mark = (row: HTMLElement): HTMLInputElement | null => row.querySelector('input[type="radio"]');
    list.addEventListener('change', (event) => {
      const input = event.target;
      if (!(input instanceof HTMLInputElement)) return;
      const row = input.closest<HTMLElement>('[data-link]');
      if (!row) return;
      if (input.type === 'radio' && input.checked) {
        const ticked = box(row);
        if (ticked) ticked.checked = true;
      }
      for (const other of rows) {
        const radio = mark(other);
        if (radio && !box(other)?.checked) radio.checked = false;
      }
      const ticked = rows.filter((other) => box(other)?.checked);
      if (!ticked.some((other) => mark(other)?.checked)) {
        const first = ticked[0] ? mark(ticked[0]) : null;
        if (first) first.checked = true;
      }
    });
  });
}

// ---- printing ------------------------------------------------------------------------------------------
function initPrint(root: ParentNode): void {
  root.querySelectorAll<HTMLButtonElement>('button[data-print]').forEach((button) => {
    button.hidden = false;
    button.addEventListener('click', () => window.print());
  });
}

// ---- GET forms with many optional fields -----------------------------------------------------------
function initOmitEmpty(root: ParentNode): void {
  root.querySelectorAll<HTMLFormElement>('form[data-omit-empty]').forEach((form) => {
    form.addEventListener('formdata', (event) => {
      for (const [name, value] of [...event.formData]) {
        if (value === '') event.formData.delete(name);
      }
    });
  });
}

function init(root: Element | Document): void {
  initTabs(root);
  initUppercase(root);
  initFormsets(root);
  initRequires(root);
  initAutosubmit(root);
  initDependents(root);
  initRefresh(root);   // after initDependents: a choice that no longer fits is cleared before the form is sent
  initLinkLists(root);
  initOmitEmpty(root);
  initPrint(root);
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
      const message = document.createElement('p');
      message.className = 'form-error';
      message.textContent = label(this.dialog, 'forbidden');   // translated by the server
      const body = document.createElement('div');
      body.className = 'modal-body';
      body.append(message);
      this.content.replaceChildren(body);
    } else {
      this.content.innerHTML = await response.text();
    }
    init(this.content);
    if (!this.dialog.open) this.dialog.showModal();
    this.content
      .querySelector<HTMLElement>('.has-error input, .has-error select, input:not([type="hidden"]), select, textarea, button')
      ?.focus();
  }

  holds(element: Element): boolean {
    return this.dialog.open && this.content.contains(element);
  }

  focus(name: string): void {
    this.content.querySelector<HTMLElement>(`[name="${CSS.escape(name)}"]`)?.focus();
  }
}

const dialog = document.querySelector<HTMLDialogElement>('dialog#modal');
const modal = dialog ? new Modal(dialog) : null;
init(document);
