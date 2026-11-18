import assert from 'node:assert/strict';
import test from 'node:test';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';

// The real build plugin, applied to a probe that exercises zod the way the app does.
const source=await readFile(new URL('../build.mjs',import.meta.url),'utf8');
const plugin=source.match(/builder\.onResolve\(\{ filter: \/\^\\\.\\\.\\\/locales[\s\S]*?resolveDir: path\.dirname\(args\.path\) \}\)\);/)?.[0];
assert.ok(plugin,'build.mjs keeps the zod English-only locale rule');
const path=await import('node:path');
const setup=new Function('builder','path',plugin);
const probe=`import {z} from 'zod';
const issue=z.object({price:z.number().min(1)}).safeParse({price:0}).error.issues[0];
export const message=issue.message, code=issue.code, english=typeof z.locales.en, other=typeof z.locales.ru;`;
const bundle=async plugins=>build({stdin:{contents:probe,resolveDir:process.cwd(),loader:'js'},bundle:true,format:'cjs',platform:'node',write:false,minify:true,plugins});
const run=text=>{const module={exports:{}};new Function('module','exports','require',text)(module,module.exports,()=>{throw Error('no require')});return module.exports;};

test('the shipped zod keeps English validation messages without the other locales',async()=>{
  const [full,trimmed]=await Promise.all([bundle([]),bundle([{name:'zod-english',setup:builder=>setup(builder,path)}])]);
  const before=run(full.outputFiles[0].text),after=run(trimmed.outputFiles[0].text);
  assert.equal(after.message,before.message);assert.equal(after.code,'too_small');assert.match(after.message,/>=1|1/);
  assert.equal(after.english,'function');assert.equal(after.other,'undefined');
  const saved=full.outputFiles[0].contents.length-trimmed.outputFiles[0].contents.length;
  assert.ok(saved>200*1024,'about 260 KiB of unused locales removed, got '+Math.round(saved/1024)+' KiB');
});
