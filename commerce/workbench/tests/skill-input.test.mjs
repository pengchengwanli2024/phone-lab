import { test } from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import { readFile } from 'node:fs/promises';
const window={matchMedia:()=>({matches:false,addEventListener(){}}),dispatchEvent(){}};
const context=vm.createContext({window,document:{documentElement:{dataset:{}}},CustomEvent:class{}});
vm.runInContext(await readFile('../ui/kit.js','utf8'),context);
vm.runInContext(await readFile('../ui/skill-input.js','utf8'),context);
const editor=window.CommerceSkillInput(window.CommerceUI);
test('task fields and fact edits preserve unknown mode inputs and original evidence identities',()=>{
 const raw=JSON.stringify({goal:'原目标',scope:{marketplace:'US',currency:'USD',period:{start:'2026-01',end:'2026-02',custom:true},warehouse:'synthetic'},facts:[{id:'F1',text:'合成事实',source_ref:'synthetic',label:'synthetic',extra:['keep']}],mode_input:{provider:{nested:42}}});
 const changed=JSON.parse(editor.write(editor.write(raw,'goal','新目标'),'facts.0.text','修改后的合成事实'));
 assert.equal(changed.goal,'新目标');assert.equal(changed.facts[0].id,'F1');assert.deepEqual(changed.facts[0].extra,['keep']);
 assert.deepEqual(changed.mode_input,{provider:{nested:42}});assert.equal(changed.scope.period.custom,true);
 const added=JSON.parse(editor.add(JSON.stringify(changed)));assert.equal(added.facts[1].id,'F2');assert.equal(added.facts[1].label,'unknown');
 const removed=JSON.parse(editor.remove(JSON.stringify(added),0));assert.equal(removed.facts[0].id,'F2');
});
test('invalid JSON and unsupported field paths cannot silently replace input',()=>{
 for(const raw of ['{','[]','null','{"scope":{"period":4}}']){assert.equal(editor.read(raw),null);assert.throws(()=>editor.write(raw,'goal','replacement'))}
 const raw='{"goal":"keep"}';assert.throws(()=>editor.write(raw,'__proto__.polluted','yes'));assert.equal(JSON.parse(raw).goal,'keep');assert.equal({}.polluted,undefined);
});
test('form output escapes source text and retains an explicit unknown evidence classification',()=>{
 const html=editor.view('{"goal":"<script>bad</script>","facts":[{"id":"F1","text":"<img src=x onerror=bad>"}]}');
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<img src=x'));assert.ok(html.includes('未知 / 待核对'));
});
