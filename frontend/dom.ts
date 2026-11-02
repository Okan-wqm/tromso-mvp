/** The element matching `selector` inside `scope`; a missing element is a template bug, so fail loudly. */
export function required<T extends Element>(scope: ParentNode, selector: string): T {
  const element = scope.querySelector<T>(selector);
  if (!element) throw new Error(`Missing element: ${selector}`);
  return element;
}
