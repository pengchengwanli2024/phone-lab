import test from 'node:test';
import assert from 'node:assert/strict';
import { trapDialogFocus, restoreDialogFocus } from '../src/dialog-focus.ts';

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
test('closing a dialog returns to a composer control replaced by a repaint', () => {
  let focused = false;
  const replacement = { getClientRects:()=>[{}], focus:()=>{focused=true;} };
  restoreDialogFocus({isConnected:false,id:'copilot-editor-expand',ownerDocument:{getElementById:()=>replacement}});
  assert.equal(focused,true);
});
test('a hidden or removed dialog opener does not steal focus elsewhere', () => {
  let focused = false;
  restoreDialogFocus({isConnected:false,id:'removed',ownerDocument:{getElementById:()=>null},focus:()=>{focused=true;}});
  assert.equal(focused,false);
});
test('completing an editor returns to its main input after dialog teardown', () => {
  const focused=[];
  const input={getClientRects:()=>[{}],focus:()=>focused.push('input')};
  const opener={isConnected:true,id:'more',ownerDocument:{getElementById:id=>id==='copilot-message'?input:null},getClientRects:()=>[{}],focus:()=>focused.push('more')};
  restoreDialogFocus(opener,'copilot-message');
  assert.deepEqual(focused,['input']);
  focused.length=0;
  restoreDialogFocus(opener);
  assert.deepEqual(focused,['more']);
});
test('an unavailable completion target falls back to the visible opener',()=>{
  let focused=false;
  const opener={isConnected:true,ownerDocument:{getElementById:()=>null},getClientRects:()=>[{}],focus:()=>{focused=true;}};
  restoreDialogFocus(opener,'missing-input');
  assert.equal(focused,true);
});
test('folded details descendants with layout boxes cannot become the last dialog control',()=>{
  for(const shiftKey of [false,true]){
    const focused=[];
    const first={tabIndex:0,getClientRects:()=>[{}],checkVisibility:()=>true,focus:()=>focused.push('first')};
    const summary={tabIndex:0,getClientRects:()=>[{}],checkVisibility:()=>true,focus:()=>focused.push('summary')};
    const hidden={tabIndex:0,getClientRects:()=>[{}],checkVisibility:()=>false,focus:()=>focused.push('hidden')};
    const dialog={ownerDocument:{activeElement:shiftKey?first:summary},querySelectorAll:()=>[first,summary,hidden]};
    let prevented=false;
    trapDialogFocus({key:'Tab',shiftKey,currentTarget:dialog,preventDefault:()=>{prevented=true}});
    assert.equal(prevented,true);assert.deepEqual(focused,[shiftKey?'summary':'first']);
  }
});
