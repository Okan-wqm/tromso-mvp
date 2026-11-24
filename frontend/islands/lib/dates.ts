// The shared date box in an island (frontend/date-input.ts, the one implementation): a text input marked
// data-date-input="day|moment" is tidied to dd.mm.yyyy [HH:MM] when it is left, as on every server-rendered page. An
// island's root is drawn after components.ts has looked for date boxes, so the island hands its own form over on mount.
import { useEffect, useRef } from 'react';

import { initDateInputs } from '../../date-input.js';

export function useDateInputs<T extends HTMLElement>() {
  const root = useRef<T>(null);
  useEffect(() => {
    if (root.current) initDateInputs(root.current);
  }, []);
  return root;
}
