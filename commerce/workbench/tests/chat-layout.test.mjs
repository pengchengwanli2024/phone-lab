import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';

const window = { matchMedia: () => ({ matches: false, addEventListener() {} }), dispatchEvent() {} };
vm.runInNewContext(await readFile('../ui/kit.js', 'utf8'), { window, document: { documentElement: { dataset: {} } }, CustomEvent: class {} });
const ui = window.CommerceUI;

test('a fresh desktop workspace reserves more space for the business task', () => {
  const layout = ui.chatLayout(1216);
  assert.equal(layout.width, 360);
  assert.ok(1216 - layout.width - 34 >= 800);
});

test('an existing user width is retained and only constrained by the available business space', () => {
  assert.equal(ui.chatLayout(1216, '480').width, 480);
  const resized = ui.chatLayout(1216, 960);
  assert.equal(resized.width, resized.max);
  assert.ok(1216 - resized.width >= 514);
  assert.equal(ui.chatLayout(1900, 820).width, 820);
});

test('unavailable or corrupt saved widths use a finite responsive default', () => {
  for (const invalid of [undefined, null, '', 'broken', -100, Infinity, NaN]) {
    assert.equal(ui.chatLayout(1216, invalid).width, 360);
  }
  for (const area of [0, NaN, 390, 768, 1024, 1216, 2000]) {
    const layout = ui.chatLayout(area);
    assert.ok(Number.isFinite(layout.width));
    assert.ok(layout.width >= layout.min && layout.width <= layout.max);
  }
});
