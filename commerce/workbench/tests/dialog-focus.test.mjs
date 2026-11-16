import test from 'node:test';
import assert from 'node:assert/strict';
import { trapDialogFocus } from '../src/dialog-focus.ts';

function fixture(active, { shift = false, key = 'Tab', controls = ['first', 'middle', 'last'] } = {}) {
  const focused = [], nodes = controls.map(name => ({ name, tabIndex: 0, getClientRects: () => [{}], focus: () => focused.push(name) }));
  const dialog = { ownerDocument: { activeElement: nodes.find(node => node.name === active) }, querySelectorAll: () => nodes, focus: () => focused.push('dialog') };
  let prevented = false;
  const event = { key, shiftKey: shift, currentTarget: dialog, preventDefault: () => { prevented = true; } };
  return { event, focused, prevented: () => prevented };
}
test('reverse Tab at first control stays in an embedded dialog', () => {
  const f = fixture('first', { shift: true }); trapDialogFocus(f.event);
  assert.equal(f.prevented(), true); assert.deepEqual(f.focused, ['last']);
});
test('Tab at last control stays in an embedded dialog', () => {
  const f = fixture('last'); trapDialogFocus(f.event);
  assert.equal(f.prevented(), true); assert.deepEqual(f.focused, ['first']);
});
test('middle controls and non-Tab keys retain native behavior', () => {
  for (const f of [fixture('middle'), fixture('first', { key: 'Escape' })]) {
    trapDialogFocus(f.event); assert.equal(f.prevented(), false); assert.deepEqual(f.focused, []);
  }
});
test('a native details summary between dialog controls retains normal Tab order', () => {
  const first = { tabIndex: 0, getClientRects: () => [{}] }, summary = { tabIndex: 0, getClientRects: () => [{}] }, last = { tabIndex: 0, getClientRects: () => [{}] };
  for (const shiftKey of [false, true]) {
    let prevented = false;
    const dialog = { ownerDocument: { activeElement: summary }, querySelectorAll: selector => selector.includes('summary') ? [first, summary, last] : [first, last] };
    trapDialogFocus({ key: 'Tab', shiftKey, currentTarget: dialog, preventDefault: () => { prevented = true; } });
    assert.equal(prevented, false);
  }
});
test('a dialog without enabled controls retains focus itself', () => {
  const f = fixture(null, { controls: [] }); trapDialogFocus(f.event);
  assert.equal(f.prevented(), true); assert.deepEqual(f.focused, ['dialog']);
});
