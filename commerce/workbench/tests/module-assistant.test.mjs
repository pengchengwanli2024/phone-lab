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
  return tab=>{cursor=0;return module.exports.useModuleAssistant(tab)};
}
test('intelligence opens at full width and its assistant toggle preserves the other module choice',()=>{
  const render=fixture();assert.equal(render('intelligence')[0],false);assert.equal(render('overview')[0],true);
  render('intelligence')[1](true);assert.equal(render('intelligence')[0],true);
  render('overview')[1](false);assert.equal(render('intelligence')[0],true);assert.equal(render('overview')[0],false);
  render('intelligence')[1](value=>!value);assert.equal(render('intelligence')[0],false);
});
