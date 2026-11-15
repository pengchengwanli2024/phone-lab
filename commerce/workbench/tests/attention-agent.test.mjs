import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';

test('a standalone attention target opens its exact older role result without starting inference', async () => {
  const source = await readFile(new URL('../../web/agent-ui.js', import.meta.url), 'utf8');
  const run = { id: 'a'.repeat(32), question: 'older-unresolved-question', role: { id: 'conductor', name: '负责人' }, topic: 'runtime', parameters: {}, status: 'awaiting_input', result: { answer: '原回答', questions: ['请补充预算'], proposals: [], observations: [] }, trace: [], actions: [] };
  const plain = value => String(value ?? '');
  const ui = Object.fromEntries(['escape', 'badge', 'alert', 'empty', 'field', 'input', 'select', 'textarea'].map(name => [name, plain]));
  ui.button = ({ label }) => label;
  const window = { CommerceUI: ui };
  vm.runInNewContext(source, { window, document: { addEventListener() {}, querySelector() {} }, setInterval() {} });
  const controller = window.CommerceAgent({ api: async (tool, args) => {
    assert.equal(tool, 'commerce_agent_get'); assert.equal(args.run_id, run.id); return run;
  }, esc: plain, toast: assert.fail, repaint() {}, modal: assert.fail, closeModal() {}, isActive: () => true });
  assert.equal(typeof controller.openRun, 'function');
  await controller.openRun(run.id);
  assert.match(controller.view(), /older-unresolved-question/);
  assert.match(controller.view(), /请补充预算/);
});
