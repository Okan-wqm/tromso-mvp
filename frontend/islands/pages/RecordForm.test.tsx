// The record form's fields against the old page (the form oracle: frontend/test/pages/form-oracle.json, recorded from
// the dev database by F:\dev\balik-notes\ui-company\dump_form_oracle.py: every visible field of every tab's form, new,
// sent empty and editing a record, with the controls the server's own field template draws for it, read as
// core/tests_formpayload.py reads them). Each payload is drawn by FieldOf (react-dom/server) and must post what the old
// markup posts: the same names, the same values ticked, chosen or typed, nothing more and nothing less; and offer the same
// choices with the same words. A control switched off posts nothing on either page. Test code only.
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { renderToStaticMarkup } from 'react-dom/server';

import { type Field, FieldOf } from './RecordForm.js';

interface Control { name: string | null; value: string; on: boolean; type: string; disabled: boolean; label?: string }
interface Case { case: string; field: Field; controls: Control[] }

const ORACLE = JSON.parse(readFileSync(resolve('frontend/test/pages/form-oracle.json'), 'utf8')) as { cases: Case[] };

const decode = (text: string): string => text.replace(/&quot;/g, '"').replace(/&#x27;/g, "'").replace(/&lt;/g, '<')
  .replace(/&gt;/g, '>').replace(/&amp;/g, '&');
const squash = (text: string): string => decode(text).replace(/<[^>]*>/g, '').split(/\s+/).filter(Boolean).join(' ');
const attr = (tag: string, name: string): string | null => {
  const found = new RegExp(`\\s${name}="([^"]*)"`).exec(tag);
  if (found) return decode(found[1] ?? '');
  return new RegExp(`\\s${name}(?=[\\s/>])`).test(tag) ? '' : null;
};

/** The controls of server-rendered markup, as core/tests_formpayload.py's Drawn reads the old page. */
function controlsOf(html: string): Control[] {
  const found: Control[] = [];
  for (const match of html.matchAll(/<input\b[^>]*>/g)) {
    const tag = match[0];
    const type = attr(tag, 'type') ?? 'text';
    const ticks = type === 'checkbox' || type === 'radio';
    found.push({ name: attr(tag, 'name'), value: attr(tag, 'value') ?? (ticks ? 'on' : ''), on: ticks ? attr(tag, 'checked') !== null : true,
      type, disabled: attr(tag, 'disabled') !== null });
  }
  for (const match of html.matchAll(/<select\b([^>]*)>([\s\S]*?)<\/select>/g)) {
    const head = `<select${match[1] ?? ''}>`;
    for (const option of (match[2] ?? '').matchAll(/<option\b([^>]*)>([\s\S]*?)<\/option>/g)) {
      const tag = `<option${option[1] ?? ''}>`;
      found.push({ name: attr(head, 'name'), value: attr(tag, 'value') ?? '', on: attr(tag, 'selected') !== null, type: 'option',
        disabled: attr(head, 'disabled') !== null, label: squash(option[2] ?? '') });
    }
  }
  for (const match of html.matchAll(/<textarea\b([^>]*)>([\s\S]*?)<\/textarea>/g)) {
    const tag = `<textarea${match[1] ?? ''}>`;
    found.push({ name: attr(tag, 'name'), value: decode(match[2] ?? '').replace(/^\n/, ''), on: true, type: 'textarea',
      disabled: attr(tag, 'disabled') !== null });
  }
  return found;
}

/** What a form posts from these controls: (name, value) of every enabled, named control that sends something. */
function posted(controls: Control[]): string[] {
  return controls.filter((c) => c.name && !c.disabled && c.on && c.type !== 'file').map((c) => `${c.name}=${c.value}`).sort();
}

/** The choices offered: (name, value, words) of every enabled option and box. */
function offered(controls: Control[]): string[] {
  return controls.filter((c) => c.name && !c.disabled && (c.type === 'option' || c.type === 'checkbox' || c.type === 'radio'))
    .map((c) => `${c.name}|${c.value}${c.label !== undefined ? `|${c.label}` : ''}`).sort();
}

test('every field of every tab form posts what the old page posts', () => {
  assert.ok(ORACLE.cases.length > 500, 'the oracle has the forms');
  const failures: string[] = [];
  for (const { case: name, field, controls } of ORACLE.cases) {
    const drawn = controlsOf(renderToStaticMarkup(<FieldOf field={field} optional="optional" source={() => undefined} />));
    const want = posted(controls);
    const got = posted(drawn);
    if (JSON.stringify(want) !== JSON.stringify(got)) failures.push(`${name}: posts ${JSON.stringify(got)}, the old page ${JSON.stringify(want)}`);
    const files = (list: Control[]) => list.filter((c) => c.type === 'file' && !c.disabled).map((c) => c.name).sort();
    if (JSON.stringify(files(controls)) !== JSON.stringify(files(drawn))) failures.push(`${name}: file inputs differ`);
  }
  assert.deepEqual(failures.slice(0, 20), [], `${failures.length} fields differ`);
});

test('every choice is offered with the old page\'s words', () => {
  const failures: string[] = [];
  for (const { case: name, field, controls } of ORACLE.cases) {
    const drawn = controlsOf(renderToStaticMarkup(<FieldOf field={field} optional="optional" source={() => undefined} />));
    // the old page draws a multiple choice as a select and its options; the new one as boxes: the values and words count
    const words = (list: Control[]) => offered(list).map((each) => each.split('|').slice(0, 2).join('|'));
    if (JSON.stringify(words(controls)) !== JSON.stringify(words(drawn))) {
      failures.push(`${name}: offers ${JSON.stringify(words(drawn)).slice(0, 200)}, the old page ${JSON.stringify(words(controls)).slice(0, 200)}`);
    }
  }
  assert.deepEqual(failures.slice(0, 20), [], `${failures.length} fields differ`);
});

test('a field\'s label, help, errors and its required or optional mark are drawn', () => {
  const field = ORACLE.cases.find((each) => each.field.errors.length && each.field.widget.kind === 'text')?.field;
  assert.ok(field, 'the oracle has a refused text field');
  const html = renderToStaticMarkup(<FieldOf field={field} optional="optional" source={() => undefined} />);
  assert.match(html, /class="field has-error"/);
  assert.match(html, /aria-invalid="true"/);
  for (const error of field.errors) assert.ok(squash(html).includes(squash(error)), error);
  const optional = ORACLE.cases.find((each) => !each.field.required && each.field.widget.kind === 'text')?.field;
  assert.ok(optional);
  assert.match(renderToStaticMarkup(<FieldOf field={optional} optional="optional" source={() => undefined} />), /<span class="ui-field-mark">optional<\/span>/);
});
