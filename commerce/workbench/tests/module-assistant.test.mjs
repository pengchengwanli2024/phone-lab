import test from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import vm from 'node:vm';

const compiled=await build({entryPoints:['src/module-assistant.ts'],bundle:true,write:false,format:'cjs',platform:'node',external:['react']});
function fixture(){
  const states=[];let cursor=0;
  const module={exports:{}};
  const react={useState(initial){const index=cursor++;if(!(index in states))states[index]=initial;return [states[index],value=>states[index]=typeof value==='function'?value(states[index]):value]}};
  vm.runInNewContext(compiled.outputFiles[0].text,{module,exports:module.exports,require:()=>react});
  const render=(tab,pinned)=>{cursor=0;return module.exports.useModuleAssistant(tab,pinned)};
  render.exports=module.exports;return render;
}
test('assistants start collapsed and intelligence keeps a choice independent of other modules',()=>{
  const render=fixture();assert.equal(render('intelligence')[0],false);assert.equal(render('overview')[0],false);
  render('overview')[1](true);assert.equal(render('overview')[0],true);assert.equal(render('intelligence')[0],false);
  render('intelligence')[1](true);assert.equal(render('intelligence')[0],true);assert.equal(render('overview')[0],true);
  render('intelligence')[1](value=>!value);assert.equal(render('intelligence')[0],false);assert.equal(render('overview')[0],true);
  render('overview')[1](false);assert.equal(render('intelligence')[0],false);assert.equal(render('overview')[0],false);
  render('intelligence')[1](true);assert.equal(render('intelligence')[0],true);assert.equal(render('workspace')[0],false);
});

test('pinning opens ordinary pages by default, leaves the map surface alone and survives blocked storage',()=>{
  const render=fixture();
  assert.equal(render('overview',true)[0],true);assert.equal(render('intelligence',true)[0],false);
  render('intelligence',true)[2](false);assert.equal(render('workspace',true)[0],false);assert.equal(render('intelligence',true)[0],false);
  const {readAssistantPinned,writeAssistantPinned,ASSISTANT_PIN_KEY}=render.exports;
  assert.equal(ASSISTANT_PIN_KEY,'commerce-workspace-assistant-pinned');
  assert.equal(readAssistantPinned(()=>'true'),true);assert.equal(readAssistantPinned(()=>null),false);assert.equal(readAssistantPinned(()=>'1'),false);
  assert.equal(readAssistantPinned(()=>{throw Error('blocked')}),false);
  let saved='';assert.equal(writeAssistantPinned(true,value=>{saved=value}),true);assert.equal(saved,'true');
  assert.equal(writeAssistantPinned(false,()=>{throw Error('blocked')}),false);
});
