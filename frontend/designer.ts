// The card designer (Setup › Reference data › Card templates, the Design tab; templates/monitoring/widgets/_designer.html).
// It edits the form's own layout textarea: the server's validator is the authority (monitoring/cards/validate.py) and the
// preview is the server's card for one real unit. Everything here is our own grid library (frontend/grid/): a palette
// (click or Enter adds), a canvas (select, drag to move, the corner handle to resize, the arrow keys to move, Shift and
// the arrow keys to resize, Delete to remove), an inspector (column, row, width, height, the water value and point, the
// widget's options from its descriptors), the reading order, undo and redo (a gesture is one entry), the problems the
// server finds, and the preview, refreshed a moment after each change (a newer request aborts the older). No word of its
// own: every label and sentence is a data attribute or the catalogue's, in the person's language.
import { label, required } from './dom.js';
import { canRedo, canUndo, commit, redo, start, undo, type History } from './grid/history.js';
import { applyKey } from './grid/keyboard.js';
import { add, catalogueOf, cellFromPoint, changes, move, parse, readingOrder, resize, serialize } from './grid/layout.js';
import type { Catalogue, Change, Item, Layout } from './grid/types.js';

interface Descriptor {
  name: string;
  label: string;
  type: string;
  defaultValue?: unknown;
  options?: { value: string; label: string }[];
}

interface WidgetData {
  type: string;
  label: string;
  bind: string;
  enabled: boolean;
  options: Descriptor[];
}

interface CatalogueData {
  columns: number;
  schema: number;
  widgets: WidgetData[];
  parameters: { value: string; label: string; short: string }[];
  points: { value: string; label: string }[];
}

interface Problem {
  severity: string;
  widget: string;
  code: string;
  message: string;
}

const PREVIEW_DELAY = 400;
const MIDDLE = 'middle';

function jsonScript<T>(id: string): T {
  return JSON.parse(required<HTMLElement>(document, `#${id}`).textContent ?? 'null') as T;
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, attrs: Record<string, string> = {},
                                                       text = ''): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  for (const [name, value] of Object.entries(attrs)) {
    node.setAttribute(name, value);
  }
  if (text) {
    node.textContent = text;
  }
  return node;
}

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in values ? String(values[key]) : whole));
}

function csrfToken(form: HTMLFormElement | null): string {
  const field = form?.querySelector<HTMLInputElement>('input[name="csrfmiddlewaretoken"]');
  return field?.value ?? '';
}

class Designer {
  private readonly root: HTMLElement;
  private readonly data: CatalogueData;
  private readonly cat: Catalogue;
  private readonly specs: Map<string, WidgetData>;
  private readonly textarea: HTMLTextAreaElement;
  private readonly canvas: HTMLElement;
  private readonly inspector: HTMLElement;
  private readonly order: HTMLElement;
  private readonly problems: HTMLElement;
  private readonly preview: HTMLElement;
  private readonly status: HTMLElement;
  private readonly initial: Layout;
  private history: History;
  private selected = '';
  private shown: Layout;                  // what the canvas draws: the history's present, or a gesture's preview
  private timer = 0;
  private request: AbortController | null = null;

  constructor(root: HTMLElement) {
    this.root = root;
    this.data = jsonScript<CatalogueData>('card-catalogue');
    this.cat = catalogueOf(this.data) as Catalogue;
    this.specs = new Map(this.data.widgets.map((widget) => [widget.type, widget]));
    this.textarea = required<HTMLTextAreaElement>(root, '[data-designer-layout]');
    this.canvas = required<HTMLElement>(root, '[data-designer-canvas]');
    this.inspector = required<HTMLElement>(root, '[data-designer-inspector]');
    this.order = required<HTMLElement>(root, '[data-designer-order]');
    this.problems = required<HTMLElement>(root, '[data-designer-problems]');
    this.preview = required<HTMLElement>(root, '[data-designer-preview]');
    this.status = required<HTMLElement>(root, '[data-designer-status]');
    let parsed: Layout = [];
    try {
      const result = parse(JSON.parse(this.textarea.value || 'null'), this.cat);
      parsed = result.ok ? result.items : [];
      if (!result.ok) {
        this.root.dataset.designerBroken = result.error;      // the text stays the truth: edited as text, refused on save
      }
    } catch {
      this.root.dataset.designerBroken = 'shape';
    }
    this.initial = parsed;
    this.history = start(parsed);
    this.shown = parsed;
    this.buildPalette();
    this.wire();
    this.render();
    this.schedulePreview();
  }

  // ---- what is drawn ------------------------------------------------------------------------------------------
  private labelOf(item: Item): string {
    const spec = this.specs.get(item.type);
    const bind = item.bind as { parameter?: string } | undefined;
    const parameter = bind?.parameter ? this.data.parameters.find((each) => each.value === bind.parameter) : undefined;
    return parameter ? `${spec?.label ?? item.type} · ${parameter.short}` : (spec?.label ?? item.type);
  }

  private buildPalette(): void {
    const palette = required<HTMLElement>(this.root, '[data-designer-palette]');
    palette.setAttribute('aria-label', label(this.root, 'labelPalette'));
    for (const widget of this.data.widgets.filter((each) => each.enabled)) {
      const button = element('button', { type: 'button', class: 'button button-ghost', 'data-type': widget.type },
                             widget.label);
      button.addEventListener('click', () => this.addWidget(widget.type));
      palette.append(button);
    }
  }

  private render(): void {
    this.canvas.setAttribute('role', 'group');
    this.canvas.setAttribute('aria-label', label(this.root, 'labelCanvas'));
    this.canvas.style.setProperty('--cols', String(this.cat.columns));
    if (!this.canvas.querySelector('.designer-frame')) {
      this.canvas.append(element('div', { class: 'designer-frame', 'aria-hidden': 'true' }, label(this.root, 'labelFrame')));
    }
    const keep = new Set(this.shown.map((item) => item.id));
    for (const node of Array.from(this.canvas.querySelectorAll<HTMLElement>('.designer-item'))) {
      if (!keep.has(node.dataset.id ?? '')) {
        node.remove();
      }
    }
    const focused = document.activeElement;
    let place = this.canvas.querySelector('.designer-frame')?.nextElementSibling ?? null;
    for (const item of readingOrder(this.shown)) {
      let node = this.canvas.querySelector<HTMLButtonElement>(`.designer-item[data-id="${item.id}"]`);
      if (node === null) {
        node = this.makeItem(item.id);
      }
      node.style.cssText = `--x:${item.x};--y:${item.y};--w:${item.w};--h:${item.h}`;
      node.querySelector('.designer-item-label')!.textContent = this.labelOf(item);
      node.setAttribute('aria-pressed', String(item.id === this.selected));
      if (place !== node) {
        this.canvas.insertBefore(node, place);                     // DOM order follows reading order
      }
      place = node.nextElementSibling;
    }
    if (focused instanceof HTMLElement && focused !== document.activeElement && this.canvas.contains(focused)) {
      focused.focus();                                             // a moved node keeps the focus it had
    }
    this.renderOrder();
    this.renderInspector();
    required<HTMLButtonElement>(this.root, '[data-designer-undo]').disabled = !canUndo(this.history);
    required<HTMLButtonElement>(this.root, '[data-designer-redo]').disabled = !canRedo(this.history);
  }

  private makeItem(id: string): HTMLButtonElement {
    const node = element('button', { type: 'button', class: 'designer-item', id: `designer-${id}`, 'data-id': id });
    node.append(element('span', { class: 'designer-item-label' }),
                element('span', { class: 'designer-handle', 'aria-hidden': 'true', 'data-handle': '' }));
    node.addEventListener('click', () => this.select(id));
    node.addEventListener('keydown', (event) => this.onKey(event, id));
    node.addEventListener('pointerdown', (event) => this.onPointerDown(event, id));
    return node;
  }

  private renderOrder(): void {
    const list = element('ol');
    for (const item of readingOrder(this.history.present)) {
      const entry = element('li');
      const link = element('a', { href: `#designer-${item.id}` }, this.labelOf(item));
      link.addEventListener('click', (event) => {
        event.preventDefault();
        this.select(item.id);
      });
      entry.append(link);
      list.append(entry);
    }
    this.order.replaceChildren(element('h4', {}, label(this.root, 'labelOrder')), list);
  }

  private renderInspector(): void {
    const item = this.history.present.find((each) => each.id === this.selected);
    if (item === undefined) {
      this.inspector.replaceChildren(element('p', { class: 'muted' }, label(this.root, 'labelNone')));
      return;
    }
    const spec = this.specs.get(item.type);
    const body: HTMLElement[] = [element('h4', {}, this.labelOf(item))];
    const sizes = this.cat.specs[item.type];
    for (const [key, name, min, max] of [['x', 'labelX', 1, this.cat.columns], ['y', 'labelY', 1, 999],
                                        ['w', 'labelW', sizes?.min_w ?? 1, sizes?.max_w ?? this.cat.columns],
                                        ['h', 'labelH', sizes?.min_h ?? 1, sizes?.max_h ?? 99]] as const) {
      const value = key === 'x' || key === 'y' ? item[key] + 1 : item[key];   // a person counts from 1
      const input = element('input', { type: 'number', min: String(min), max: String(max), value: String(value),
                                       'data-field': key });
      input.addEventListener('change', () => this.placeFromInspector(item.id, key, Number(input.value)));
      const wrap = element('label', {}, label(this.root, name));
      wrap.append(input);
      body.push(wrap);
    }
    if (spec?.bind === 'parameter') {
      const bind = (item.bind ?? {}) as { parameter?: string; point?: string };
      body.push(this.select_('labelBinding', this.data.parameters.map((each) => ({ value: each.value, label: each.label })),
                             bind.parameter ?? '', (value) => this.setBind(item.id, { ...bind, parameter: value })));
      const points = this.data.points.map((each) => ({ value: each.value, label: each.label }));
      body.push(this.select_('labelPoint', points, bind.point ?? MIDDLE, (value) => {
        const next: Record<string, string> = { ...bind, point: value };
        if (value === MIDDLE) {
          delete next.point;
        }
        this.setBind(item.id, next);
      }));
    }
    const opts = (item.opts ?? {}) as Record<string, unknown>;
    for (const descriptor of spec?.options ?? []) {
      if (descriptor.type === 'boolean') {
        const box = element('input', { type: 'checkbox' });
        box.checked = opts[descriptor.name] === true;
        box.addEventListener('change', () => this.setOption(item.id, descriptor.name, box.checked ? true : undefined));
        const wrap = element('label', { class: 'designer-check' });
        wrap.append(box, document.createTextNode(` ${descriptor.label}`));
        body.push(wrap);
      } else {
        const current = String(opts[descriptor.name] ?? descriptor.defaultValue ?? '');
        body.push(this.select_(null, descriptor.options ?? [], current, (value) =>
          this.setOption(item.id, descriptor.name, value === descriptor.defaultValue ? undefined : value), descriptor.label));
      }
    }
    const remove = element('button', { type: 'button', class: 'button button-ghost' }, label(this.root, 'labelRemove'));
    remove.addEventListener('click', () => this.apply(applyKey(this.history.present, item.id, 'Delete', false, this.cat)));
    body.push(remove);
    this.inspector.replaceChildren(...body);
  }

  private select_(name: string | null, options: { value: string; label: string }[], current: string,
                  changed: (value: string) => void, text = ''): HTMLElement {
    const wrap = element('label', {}, name ? label(this.root, name) : text);
    const select = element('select');
    for (const option of options) {
      const node = element('option', { value: option.value }, option.label);
      node.selected = option.value === current;
      select.append(node);
    }
    select.addEventListener('change', () => changed(select.value));
    wrap.append(select);
    return wrap;
  }

  // ---- changes -------------------------------------------------------------------------------------------------
  private select(id: string): void {
    this.selected = id;
    this.render();
    this.canvas.querySelector<HTMLElement>(`#designer-${id}`)?.focus();
  }

  private record(next: Layout): void {
    const before = this.history.present;
    this.history = commit(this.history, next);
    this.shown = this.history.present;
    this.textarea.value = JSON.stringify(serialize(this.history.present, this.cat.schema));
    this.announce(changes(before, this.history.present), before);
    this.render();
    this.schedulePreview();
  }

  private apply(result: { items: Layout; selected: string } | null): void {
    if (result === null) {
      return;
    }
    this.selected = result.selected;
    this.record(result.items);
    this.canvas.querySelector<HTMLElement>(`#designer-${this.selected}`)?.focus();
  }

  private addWidget(type: string): void {
    const added = add(this.history.present, type, this.cat);
    if (added.id) {
      this.selected = added.id;
      this.record(added.items);
      this.canvas.querySelector<HTMLElement>(`#designer-${added.id}`)?.focus();
    }
  }

  private placeFromInspector(id: string, key: 'x' | 'y' | 'w' | 'h', value: number): void {
    const item = this.history.present.find((each) => each.id === id);
    if (item === undefined || !Number.isFinite(value)) {
      return;
    }
    const next = key === 'x' || key === 'y'
      ? move(this.history.present, id, key === 'x' ? value - 1 : item.x, key === 'y' ? value - 1 : item.y, this.cat)
      : resize(this.history.present, id, key === 'w' ? value : item.w, key === 'h' ? value : item.h, this.cat);
    this.record(next);
  }

  private setBind(id: string, bind: Record<string, string | undefined>): void {
    this.record(this.history.present.map((item) => (item.id === id ? { ...item, bind } : item)));
  }

  private setOption(id: string, name: string, value: unknown): void {
    this.record(this.history.present.map((item) => {
      if (item.id !== id) {
        return item;
      }
      const opts = { ...((item.opts ?? {}) as Record<string, unknown>) };
      if (value === undefined) {
        delete opts[name];
      } else {
        opts[name] = value;
      }
      const { opts: _old, ...rest } = item;
      return Object.keys(opts).length ? { ...rest, opts } : rest;
    }));
  }

  // Each change said with its widget's name: a removed widget is found in the layout before the change (F-149).
  private announce(found: Change[], before: Layout): void {
    const sentences = found.map((change) => {
      const item = this.history.present.find((each) => each.id === change.id)
        ?? before.find((each) => each.id === change.id) ?? change;
      const text = this.root.dataset[`announce${change.kind[0].toUpperCase()}${change.kind.slice(1)}`] ?? '';
      return fill(text, { label: this.labelOf(item as Item), x: change.x + 1, y: change.y + 1, w: change.w,
                          h: change.h });
    });
    if (sentences.length) {
      this.status.textContent = sentences.join(' ');
    }
  }

  // ---- input ---------------------------------------------------------------------------------------------------
  private wire(): void {
    required<HTMLButtonElement>(this.root, '[data-designer-undo]').addEventListener('click', () => this.step(undo));
    required<HTMLButtonElement>(this.root, '[data-designer-redo]').addEventListener('click', () => this.step(redo));
    required<HTMLButtonElement>(this.root, '[data-designer-revert]').addEventListener('click', () => this.record(this.initial));
    required<HTMLInputElement>(this.root, '[data-designer-lines]').addEventListener('change', (event) => {
      this.canvas.classList.toggle('no-lines', !(event.target as HTMLInputElement).checked);
    });
    for (const selector of ['[data-designer-unit]', '[data-designer-state]']) {
      required<HTMLSelectElement>(this.root, selector).addEventListener('change', () => this.schedulePreview());
    }
    // (the measure is on the form's General tab: a change there is a change of the card)
    for (const name of ['measure_w', 'measure_h']) {
      this.root.closest('form')?.querySelector<HTMLInputElement>(`input[name="${name}"]`)
        ?.addEventListener('input', () => this.schedulePreview());
    }
    required<HTMLSelectElement>(this.root, '[data-designer-width]').addEventListener('change', (event) => {
      this.preview.style.setProperty('--card-min', (event.target as HTMLSelectElement).value);
    });
    this.root.addEventListener('keydown', (event) => {
      if ((event.ctrlKey || event.metaKey) && (event.key === 'z' || event.key === 'y')) {
        event.preventDefault();
        this.step(event.key === 'z' && !event.shiftKey ? undo : redo);
      }
    });
    this.textarea.addEventListener('change', () => {
      try {
        const parsed = parse(JSON.parse(this.textarea.value), this.cat);
        if (parsed.ok) {
          delete this.root.dataset.designerBroken;
          this.record(parsed.items);
        }
      } catch {
        this.root.dataset.designerBroken = 'shape';
      }
    });
  }

  private step(move_: (history: History) => History): void {
    const before = this.history.present;
    this.history = move_(this.history);
    this.shown = this.history.present;
    this.textarea.value = JSON.stringify(serialize(this.history.present, this.cat.schema));
    this.announce(changes(before, this.history.present), before);
    this.render();
    this.schedulePreview();
  }

  private onKey(event: KeyboardEvent, id: string): void {
    const result = applyKey(this.history.present, id, event.key, event.shiftKey, this.cat);   // the widget with the focus
    if (result !== null) {
      event.preventDefault();
      this.apply(result);
    }
  }

  private rowPixels(): number {
    const probe = parseFloat(getComputedStyle(this.canvas).getPropertyValue('--row-px'));
    return Number.isFinite(probe) && probe > 0 ? probe : 28;
  }

  private onPointerDown(event: PointerEvent, id: string): void {
    if (event.button !== 0) {
      return;
    }
    const item = this.history.present.find((each) => each.id === id);
    if (item === undefined) {
      return;
    }
    const resizing = (event.target as HTMLElement).hasAttribute('data-handle');
    const node = event.currentTarget as HTMLElement;
    node.setPointerCapture(event.pointerId);
    this.select(id);
    const rect = this.canvas.getBoundingClientRect();
    const style = getComputedStyle(this.canvas);
    const box = { left: rect.left + parseFloat(style.paddingLeft), top: rect.top + parseFloat(style.paddingTop),
                  width: rect.width - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight) };   // below the frame
    const grab = cellFromPoint(event.clientX, event.clientY, box, this.cat.columns, this.rowPixels());
    const moved = (where: PointerEvent): Layout => {
      const cell = cellFromPoint(where.clientX, where.clientY, box, this.cat.columns, this.rowPixels());
      return resizing
        ? resize(this.history.present, id, cell.x - item.x + 1, cell.y - item.y + 1, this.cat)
        : move(this.history.present, id, item.x + cell.x - grab.x, item.y + cell.y - grab.y, this.cat);
    };
    const onMove = (where: PointerEvent): void => {
      this.shown = moved(where);                              // a preview of the gesture, not an entry
      this.render();
    };
    const onUp = (where: PointerEvent): void => {
      node.removeEventListener('pointermove', onMove);
      node.removeEventListener('pointerup', onUp);
      node.removeEventListener('pointercancel', onCancel);
      this.record(moved(where));                              // the whole gesture is one entry
    };
    const onCancel = (): void => {
      node.removeEventListener('pointermove', onMove);
      node.removeEventListener('pointerup', onUp);
      this.shown = this.history.present;
      this.render();
    };
    node.addEventListener('pointermove', onMove);
    node.addEventListener('pointerup', onUp);
    node.addEventListener('pointercancel', onCancel);
  }

  // ---- the server's answer -------------------------------------------------------------------------------------
  /** The form's measure as [width, height], null when either field is empty or no whole number (a card that flows:
   *  the form's own check says what is wrong with a half-filled one on save). */
  private measure(form: HTMLFormElement | null): [number, number] | null {
    const read = (name: string): number => {
      const input = form?.querySelector<HTMLInputElement>(`input[name="${name}"]`);
      const raw = input?.value.trim() ?? '';
      if (!input || !/^\d+$/.test(raw)) return Number.NaN;
      // (outside the field's own range, e.g. while a number is being typed: no measure yet)
      const value = Number(raw);
      return (input.min && value < Number(input.min)) || (input.max && value > Number(input.max)) ? Number.NaN : value;
    };
    const width = read('measure_w');
    const height = read('measure_h');
    return Number.isNaN(width) || Number.isNaN(height) ? null : [width, height];
  }

  private schedulePreview(): void {
    window.clearTimeout(this.timer);
    this.timer = window.setTimeout(() => void this.refresh(), PREVIEW_DELAY);
  }

  private async refresh(): Promise<void> {
    this.request?.abort();
    const request = new AbortController();
    this.request = request;
    const form = this.root.closest('form');
    const name = form?.querySelector<HTMLInputElement>('input[name="name"]')?.value ?? '';
    // A FITTED template (the form's two measure fields both filled with whole numbers): the server draws the card
    // fitted at that measure and its validator answers for it; the pane then shows it at the measure's proportion.
    const measure = this.measure(form);
    this.preview.classList.toggle('is-fitted', measure !== null);
    const body = JSON.stringify({ layout: serialize(this.history.present, this.cat.schema), name, measure,
                                  unit: required<HTMLSelectElement>(this.root, '[data-designer-unit]').value,
                                  state: required<HTMLSelectElement>(this.root, '[data-designer-state]').value });
    try {
      const response = await fetch(this.root.dataset.previewUrl ?? '', {
        method: 'POST', body, signal: request.signal, credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken(form) },
      });
      if (!response.ok) {
        this.previewFailed();
        return;
      }
      const answer = await response.json() as { html: string; problems: Problem[] };
      this.showProblems(answer.problems);
      const focused = document.activeElement;
      this.preview.innerHTML = answer.html;                   // only the preview pane: the canvas and its focus stay
      if (focused instanceof HTMLElement && focused !== document.activeElement && document.contains(focused)) {
        focused.focus();
      }
      this.status.dataset.preview = label(this.root, 'announcePreview');
    } catch (error) {
      if (!(error instanceof DOMException && error.name === 'AbortError')) {
        this.previewFailed();                                  // offline, or an answer that is not the preview
      }
    }
  }

  // A preview the server refused or could not give (F-122): said in the pane, in the page's words, never thrown; the
  // layout and its problems are not touched, and the next change asks again.
  private previewFailed(): void {
    this.preview.replaceChildren(element('p', { role: 'alert', class: 'designer-preview-failed' },
                                         label(this.root, 'labelPreviewFailed')));
  }

  private showProblems(problems: Problem[]): void {
    const groups: [string, Problem[]][] = [['labelErrors', problems.filter((each) => each.severity === 'error')],
                                           ['labelWarnings', problems.filter((each) => each.severity !== 'error')]];
    const nodes: HTMLElement[] = [];
    for (const [name, found] of groups) {
      if (!found.length) {
        continue;
      }
      const list = element('ul');
      for (const problem of found) {
        const entry = element('li', { 'data-code': problem.code });
        if (problem.widget) {
          const link = element('a', { href: `#designer-${problem.widget}` }, problem.message);
          link.addEventListener('click', (event) => {
            event.preventDefault();
            this.select(problem.widget);
          });
          entry.append(link);
        } else {
          entry.textContent = problem.message;
        }
        list.append(entry);
      }
      nodes.push(element('h4', {}, label(this.root, name)), list);
    }
    this.problems.replaceChildren(...nodes);
    for (const node of Array.from(this.canvas.querySelectorAll<HTMLElement>('.designer-item'))) {
      const bad = problems.some((problem) => problem.severity === 'error' && problem.widget === node.dataset.id);
      node.toggleAttribute('aria-invalid', bad);
    }
  }
}

for (const root of Array.from(document.querySelectorAll<HTMLElement>('[data-designer]'))) {
  new Designer(root);
}

export {};
