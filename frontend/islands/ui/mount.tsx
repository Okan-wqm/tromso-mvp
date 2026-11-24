// Mounts an island (README, Frontend: islands): every <div data-island="<name>"> the template tag `{% island %}` wrote
// (core/templatetags/assets.py) becomes a React root drawing `Component` with the props the server put beside it as a
// JSON data block (never run, never evaluated: JSON.parse). The server reads, judges and words everything; an island
// draws finished values and sends forms back to Django, which validates them.
import { StrictMode, type ComponentType } from 'react';
import { createRoot } from 'react-dom/client';
import { I18nProvider } from 'react-aria-components';

// React Aria's press handling adds one <style> to the page the first time a pressable mounts, unless an element with this
// id is already there. That inline style would break `style-src 'self'`: its one rule ships in static/css/ds.css
// ([data-react-aria-pressable]), and this marker tells React Aria it is in place.
export const PRESSABLE_STYLE_ID = 'react-aria-pressable-style';

export function readProps<P>(root: HTMLElement): P {
  const block = root.dataset.props ? document.getElementById(root.dataset.props) : null;
  if (!block || block.getAttribute('type') !== 'application/json') {
    throw new Error(`island ${root.dataset.island ?? '?'}: its props block ${root.dataset.props ?? '(none)'} is missing`);
  }
  return JSON.parse(block.textContent || '{}') as P;
}

export function mount<P extends object>(name: string, Component: ComponentType<P>, doc: Document = document): number {
  if (!doc.getElementById(PRESSABLE_STYLE_ID)) {
    const marker = doc.createElement('meta');
    marker.id = PRESSABLE_STYLE_ID;
    doc.head.append(marker);
  }
  let mounted = 0;
  for (const root of doc.querySelectorAll<HTMLElement>(`[data-island="${name}"]`)) {
    if (root.dataset.mounted) continue;
    const props = readProps<P>(root);
    root.dataset.mounted = 'true';
    createRoot(root).render(
      <StrictMode>
        <I18nProvider locale={doc.documentElement.lang || 'en'}>
          <Component {...props} />
        </I18nProvider>
      </StrictMode>,
    );
    mounted += 1;
  }
  return mounted;
}
