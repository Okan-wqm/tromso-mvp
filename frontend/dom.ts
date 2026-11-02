/** A UI text the template rendered into a data attribute: the server translates every text, this code
 *  has none of its own. A missing one is a template bug, so fail loudly. */
export function label(element: HTMLElement, key: string): string {
  const text = element.dataset[key];
  if (text === undefined) throw new Error(`Missing data attribute "${key}" on <${element.localName}>`);
  return text;
}

/** The element matching `selector` inside `scope`; a missing element is a template bug, so fail loudly. */
export function required<T extends Element>(scope: ParentNode, selector: string): T {
  const element = scope.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
}
