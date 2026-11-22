// The style sheets a page of the product loads, in the order its template links them (templates/app_base.html,
// farm/water_calculator_report.html, ...): the browser tests build their pages from this list, not from a copy of it, so a
// test never measures an order the product does not ship. `pageStyles` stands where the template's block page_styles is
// (a page's own sheets, before tw.css). Test code only.
import { readFileSync } from 'node:fs';
import { join, resolve } from 'node:path';

const TEMPLATES = resolve('templates');

/** The names (static/css/<name>.css) a template links, in order. */
export function sheetsOf(template: string, pageStyles: string[] = []): string[] {
  const text = readFileSync(join(TEMPLATES, template), 'utf8');
  const names: string[] = [];
  for (const match of text.matchAll(/css\/([\w-]+)\.css|\{%\s*block page_styles\s*%\}/g)) {
    if (match[1] !== undefined) names.push(match[1]);
    else names.push(...pageStyles);
  }
  return names;
}

/** `<link>` tags for the sheets of a template, served under /css/. */
export function linksOf(template: string, pageStyles: string[] = []): string {
  return sheetsOf(template, pageStyles).map((name) => `<link rel="stylesheet" href="/css/${name}.css">`).join('');
}

/** The markup a test copies from a template must still be in it, so the copy cannot drift from what the page prints. */
export function mirrors(template: string, ...tags: string[]): string[] {
  const text = readFileSync(join(TEMPLATES, template), 'utf8');
  return tags.filter((tag) => !text.includes(tag));
}
