// Marks the test build (.build/test) as ES modules, so `node --test` loads the compiled TypeScript as the browser does.
import { mkdirSync, writeFileSync } from 'node:fs';

mkdirSync('.build/test', { recursive: true });
writeFileSync('.build/test/package.json', '{"type": "module"}\n');
