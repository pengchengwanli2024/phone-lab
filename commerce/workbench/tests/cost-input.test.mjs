import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
const bundle = await build({ entryPoints: ['src/cost-input.ts'], bundle: true, write: false, format: 'esm', platform: 'node' });
const { toInput, fromInput, validateInput, differences } = await import('data:text/javascript;base64,' + Buffer.from(bundle.outputFiles[0].text).toString('base64'));

test('cost inputs preserve unknown blanks and explicit zero separately', () => {
  assert.deepEqual(toInput({ currency: ' cny ', price: '100', purchase_cost: '', packaging: '0' }), { currency: 'CNY', price: 100, packaging: 0 });
  assert.deepEqual(validateInput({ purchase_cost: '', price: '' }), {});
});
test('percentage display round trips fraction protocol without precision noise', () => {
  const values = fromInput({ currency: 'CNY', commission_rate: .073, ad_rate: 0, return_rate: null });
  assert.equal(values.commission_rate, '7.3'); assert.equal(values.return_rate, '');
  assert.deepEqual(toInput(values), { currency: 'CNY', commission_rate: .073, ad_rate: 0 });
});
test('range and currency errors identify actual fields before invoking an action', () => {
  const errors = validateInput({ price: '0', commission_rate: '101', packaging: '-1', currency: '人民币', ad_rate: 'Infinity' });
  assert.deepEqual(Object.keys(errors), ['currency', 'price', 'packaging', 'commission_rate', 'ad_rate']);
  assert.throws(() => toInput({ commission_rate: '101' }), /invalid_commission_rate/);
  assert.deepEqual(toInput({ commission_rate: '100', price: '.01', packaging: '0' }), { price: .01, packaging: 0, commission_rate: 1 });
});
test('conflict comparison shows changed costs and distinguishes blank from zero', () => {
  assert.deepEqual(differences({ price: '120', packaging: '' }, { price: '100', packaging: '0' }), ['price', 'packaging']);
});
