import assert from 'node:assert/strict';
import { readFile, access } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
assert.equal(process.env.VERIFY_NODE_GUARD_ACTIVE, '1', 'Node fixture network guard required');
assert.ok(Number(process.versions.node.split('.')[0]) >= 20, 'Node 20 or newer required');
if (process.argv[2] === 'browser') {
  assert.ok(process.env.PLAYWRIGHT_MODULE, 'Existing Playwright required; set PLAYWRIGHT_MODULE to its index.mjs');
  const playwright = await import(process.env.PLAYWRIGHT_MODULE);
  assert.ok(playwright.chromium, 'Playwright chromium API required');
  assert.ok(process.env.CHROME_PATH, 'Existing Chrome/Chromium required; set CHROME_PATH');
  await access(process.env.CHROME_PATH);
  console.log(JSON.stringify({playwright: true, browser_executable: true}));
} else {
  const packages = {};
  for (const folder of ['commerce/workbench', 'commerce/workbench/map']) {
    const pkg = JSON.parse(await readFile(path.join(root, folder, 'package.json')));
    for (const [name, version] of Object.entries({...pkg.dependencies, ...pkg.devDependencies})) {
      const installed = JSON.parse(await readFile(path.join(root, folder, 'node_modules', name, 'package.json')));
      assert.equal(installed.version, version, name + ': install pinned dependencies before verification');
      packages[folder + ':' + name] = installed.version;
    }
  }
  console.log(JSON.stringify({node: process.versions.node, packages}));
}
