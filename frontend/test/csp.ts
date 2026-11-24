// The product's Content-Security-Policy for the browser tests, read from the one place it is written (config/settings.py,
// SECURE_CSP), so a test never serves a hand-copied policy that drifts from the server's. `nonce` stands in for the
// response's nonce (Django's CSP.NONCE); without one the policy allows no inline script at all. Test code only.
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const WORDS: Record<string, string> = { 'CSP.SELF': "'self'", 'CSP.NONE': "'none'", 'CSP.UNSAFE_INLINE': "'unsafe-inline'" };

/** [directive, [source, …]] of SECURE_CSP as config/settings.py writes it. */
export function directives(settings = readFileSync(resolve('config/settings.py'), 'utf8')): [string, string[]][] {
  const block = /^SECURE_CSP = \{([\s\S]*?)^\}/m.exec(settings)?.[1];
  if (!block) throw new Error('config/settings.py has no SECURE_CSP block');
  return [...block.matchAll(/'([a-z-]+)':\s*\[([^\]]*)\]/g)].map(([, name, list]) => [name as string, (list as string)
    .split(',').map((item) => item.trim()).filter(Boolean)
    .map((item) => (item.startsWith("'") ? item.slice(1, -1) : item))]);
}

/** The header value: Django's words turned into the browser's, CSP.NONCE into `'nonce-<nonce>'` (or dropped). */
export function policy(nonce = ''): string {
  return directives().map(([name, sources]) => `${name} ${sources.flatMap((source) => {
    if (source === 'CSP.NONCE') return nonce ? [`'nonce-${nonce}'`] : [];
    return [WORDS[source] ?? source];
  }).join(' ')}`).join('; ');
}
