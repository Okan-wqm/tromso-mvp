// Site form: inner tabs, upper-case site code, contact rows (add, remove, one primary).
(() => {
  // Inner tabs. Without this script every section is simply shown one after another.
  const tablist = document.querySelector('[data-tabs]');
  if (tablist) {
    const tabs = [...tablist.querySelectorAll('[data-tab]')];
    const panels = [...document.querySelectorAll('[data-panel]')];
    const select = (key, focus) => {
      tabs.forEach((tab) => {
        const on = tab.dataset.tab === key;
        tab.setAttribute('aria-selected', String(on));
        tab.tabIndex = on ? 0 : -1;
        if (on && focus) tab.focus();
      });
      panels.forEach((panel) => { panel.hidden = panel.dataset.panel !== key; });
    };
    tablist.hidden = false;
    document.body.classList.add('js-tabs');
    tabs.forEach((tab, i) => {
      tab.addEventListener('click', () => select(tab.dataset.tab));
      tab.addEventListener('keydown', (event) => {
        const step = { ArrowRight: 1, ArrowLeft: -1 }[event.key];
        if (!step) return;
        select(tabs[(i + step + tabs.length) % tabs.length].dataset.tab, true);
      });
    });
    const firstError = panels.find((panel) => panel.hasAttribute('data-has-errors'));
    select(tablist.dataset.open || (firstError && firstError.dataset.panel) || tabs[0].dataset.tab);
  }

  // Site codes are stored upper-case; show it while typing.
  document.querySelectorAll('[data-uppercase]').forEach((input) => {
    input.addEventListener('input', () => {
      const { selectionStart, selectionEnd } = input;
      input.value = input.value.toUpperCase();
      input.setSelectionRange(selectionStart, selectionEnd);
    });
  });

  // Contact rows
  const formset = document.querySelector('[data-formset]');
  if (!formset) return;
  const rows = formset.querySelector('[data-rows]');
  const template = formset.querySelector('[data-row-template]');
  const total = formset.querySelector('input[name$="-TOTAL_FORMS"]');
  const empty = formset.querySelector('[data-empty]');

  const wire = (row) => {
    const remove = row.querySelector('input[name$="-DELETE"]');
    if (remove) {
      remove.addEventListener('change', () => row.classList.toggle('is-removed', remove.checked));
      row.classList.toggle('is-removed', remove.checked);
    }
  };
  rows.querySelectorAll('[data-row]').forEach(wire);

  // Only one primary contact: ticking one clears the others.
  formset.addEventListener('change', (event) => {
    if (!event.target.matches('[data-primary]') || !event.target.checked) return;
    formset.querySelectorAll('[data-primary]').forEach((box) => {
      if (box !== event.target) box.checked = false;
    });
  });

  formset.querySelector('[data-add-row]').addEventListener('click', () => {
    const index = Number(total.value);
    const html = template.innerHTML.replace(/__prefix__/g, String(index));
    rows.insertAdjacentHTML('beforeend', html);
    total.value = String(index + 1);
    empty.hidden = true;
    const row = rows.lastElementChild;
    wire(row);
    row.querySelector('input[type="text"]').focus();
  });
})();
