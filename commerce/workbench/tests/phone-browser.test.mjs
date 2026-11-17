import test from 'node:test';
import assert from 'node:assert/strict';
import { requiresPhoneBrowser } from '../src/phone-browser.ts';

test('ordinary browser phone pages retain their existing HTTP control path', () => {
  for (const protocol of ['http:', 'https:']) assert.equal(requiresPhoneBrowser(protocol), false);
});
test('opaque and native host pages use explicit local browser handoff', () => {
  for (const protocol of ['about:', 'dsh-app:', 'file:']) assert.equal(requiresPhoneBrowser(protocol), true);
});
