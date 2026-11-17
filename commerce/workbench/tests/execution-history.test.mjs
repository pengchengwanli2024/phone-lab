import test from 'node:test';
import assert from 'node:assert/strict';
import {build} from 'esbuild';
import vm from 'node:vm';

const bundle=await build({entryPoints:['src/execution-directory.tsx'],bundle:true,write:false,format:'cjs',platform:'node',external:['react','react/jsx-runtime'],plugins:[{name:'isolated-history-dependencies',setup(plugin){plugin.onResolve({filter:/^\.\/(api|ui)$/},args=>({path:args.path,external:true}));}}]});
const flush=async()=>{for(let i=0;i<3;i++)await new Promise(setImmediate);};
function fixture(){
  const slots=[],requests=[],effects=[],navigations=[],focusCalls=[],elements=new Map();let index=0,tree,active=true;
  const document={activeElement:null,body:null,documentElement:null,defaultView:{getComputedStyle:element=>({visibility:element.visibility||'visible'})}};
  function element(id){return {id,ownerDocument:document,isConnected:true,disabled:false,visibility:'visible',matches:()=>false,getClientRects(){return active&&this.isConnected?[{}]:[];},focus(options){document.activeElement=this;focusCalls.push({id:this.id,options});}};}
  document.body=element('body');document.documentElement=element('html');document.activeElement=document.body;
  const react={useState(initial){const key=index++;if(!(key in slots))slots[key]=initial;return [slots[key],value=>slots[key]=typeof value==='function'?value(slots[key]):value];},useRef(value){const key=index++;return slots[key]??=( {current:value} );},useEffect(run,deps){const key=index++,old=slots[key];if(!old||deps.some((d,i)=>d!==old.deps[i])){effects.push(()=>{old?.cleanup?.();slots[key]={deps,cleanup:run()};});}}};
  const jsx=(type,props,key)=>({type,props:props||{},key});
  const module={exports:{}};
  vm.runInNewContext(bundle.outputFiles[0].text,{module,exports:module.exports,Error,Date,window:{CommerceUI:{status:code=>({label:{completed:'已完成',succeeded:'已完成',unknown:'状态未知'}[code]||code})}},require(name){if(name==='react')return react;if(name==='react/jsx-runtime')return {jsx,jsxs:jsx,Fragment:'fragment'};if(name==='./ui')return {Button:'button',Panel:'panel',Empty:'empty',ErrorNotice:'error',Status:'status'};if(name==='./api')return {api:(tool,args)=>new Promise((resolve,reject)=>requests.push({tool,args,resolve,reject})),errorText:()=> '读取失败'};throw Error(name);}});
  function render(){index=0;tree=module.exports.ExecutionDirectory({active,navigate:(...args)=>navigations.push(args)});
    const mounted=new Set();
    for(const node of nodes())if(node.props?.id){
      const id=node.props.id,el=elements.get(id)||element(id);elements.set(id,el);mounted.add(id);el.isConnected=true;el.disabled=!!node.props.disabled;el.tabIndex=node.props.tabIndex??0;el.matches=selector=>selector===':disabled'&&el.disabled;
      // Model the native disabled-control blur observed in the Harness.
      if(el.disabled&&document.activeElement===el)document.activeElement=document.documentElement;
      if(node.props.ref)node.props.ref.current=el;
    }
    for(const [id,el] of elements)if(!mounted.has(id))el.isConnected=false;
    while(effects.length)effects.shift()();return tree;}
  function nodes(node){if(arguments.length===0)node=tree;if(node==null||typeof node!=='object')return [];if(Array.isArray(node))return node.flatMap(child=>nodes(child));return [node,...nodes(node.props?.children),...nodes(node.props?.action)];}
  function text(node){if(arguments.length===0)node=tree;if(node==null||typeof node==='boolean')return '';if(typeof node!=='object')return String(node);if(Array.isArray(node))return node.map(child=>text(child)).join('');return text(node.props?.children);}
  function button(label){return nodes().find(n=>n.type==='button'&&text(n)===label);}
  render();return {requests,navigations,render,nodes,text,button,document,elements,focusCalls,element,
    click(label){const node=button(label),el=elements.get(node.props.id);assert.equal(!!node.props.disabled,false);document.activeElement=el;node.props.onClick({currentTarget:el});render();},
    apply(){const el=elements.get('execution-history-apply');document.activeElement=el;nodes().find(node=>node.type==='form').props.onSubmit({preventDefault(){},nativeEvent:{submitter:el},currentTarget:{ownerDocument:document}});render();},
    setActive(value){active=value;render();},exports:module.exports};
}
const record=(origin,id,extras={})=>({key:origin+':'+id,id,origin,title:'合成 '+id,status:'completed',at:1800000000,version:null,...extras});
const page=(items,next_cursor=null)=>({items,next_cursor});
async function settle(f,value,request=f.requests.at(-1)){request.resolve(value);await flush();f.render();}

test('history uses the new paged tool and every original source keeps its exact detail destination',async()=>{
  const f=fixture();assert.equal(f.requests.length,1);assert.equal(f.requests[0].tool,'commerce_execution_history');
  assert.equal(f.requests[0].args.limit,30);assert.equal('cursor' in f.requests[0].args,false);
  await settle(f,page([record('agent','same'),record('skills','same',{status:'succeeded',version:1}),record('assistant-team','same',{at:null,status:null,title:null})]));
  for(const button of f.nodes().filter(n=>n.type==='button'&&f.text(n)==='查看原记录'))button.props.onClick();
  assert.deepEqual(f.navigations,[['agent','same'],['skills','same'],['assistant-team','same']]);
  assert.match(f.text(),/completed/);assert.match(f.text(),/succeeded/);assert.match(f.text(),/时间未记录/);assert.match(f.text(),/状态未记录/);assert.match(f.text(),/标题未记录/);
  assert.ok(f.nodes().some(n=>n.type==='tr'&&n.key==='skills:same'));
});

test('next and previous pages pass the original opaque cursor and preserve current records during reads',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'opaque-original-cursor'));
  f.button('下一页记录').props.onClick();f.render();
  assert.equal(f.requests.at(-1).args.cursor,'opaque-original-cursor');assert.match(f.text(),/合成 first/);
  await settle(f,page([record('skills','second')]));assert.match(f.text(),/第 2 页/);
  f.button('上一页记录').props.onClick();
  assert.equal('cursor' in f.requests.at(-1).args,false);
  await settle(f,page([record('agent','first')],'opaque-original-cursor'));assert.match(f.text(),/第 1 页/);
});

test('failed page reads retain items, pagination and pending filter input instead of looking empty',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
  f.button('下一页记录').props.onClick();await settle(f,page([record('skills','second')],'cursor-three'));
  f.nodes().find(n=>n.type==='input'&&n.props.type==='search').props.onChange({target:{value:'待应用的合成关键词'}});f.render();
  f.button('下一页记录').props.onClick();f.requests.at(-1).reject(Error('execution_history_source_unavailable'));await flush();f.render();
  assert.match(f.text(),/暂未完整读到/);assert.match(f.text(),/合成 second/);assert.match(f.text(),/第 2 页/);
  assert.doesNotMatch(f.text(),/当前筛选没有执行记录/);
  assert.equal(f.nodes().find(n=>n.type==='input'&&n.props.type==='search').props.value,'待应用的合成关键词');
  f.button('下一页记录').props.onClick();assert.equal(f.requests.at(-1).args.cursor,'cursor-three');
  assert.equal(f.requests.at(-1).args.query,'','draft filters must not change a cursor-bound request');
});

test('explicitly applying source, keyword and raw status filters restarts at page one and keeps failed input',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
  f.button('下一页记录').props.onClick();await settle(f,page([record('agent','second')]));
  f.nodes().find(n=>n.type==='input'&&n.props.type==='search').props.onChange({target:{value:'合成原问题'}});
  f.nodes().find(n=>n.type==='select').props.onChange({target:{value:'assistant-team'}});
  f.nodes().find(n=>n.type==='input'&&n.props.list).props.onChange({target:{value:'awaiting_input'}});f.render();
  f.nodes().find(n=>n.type==='form').props.onSubmit({preventDefault(){}});
  const request=f.requests.at(-1);assert.deepEqual(JSON.parse(JSON.stringify(request.args)),{query:'合成原问题',origin:'assistant-team',status:'awaiting_input',limit:30});
  request.reject(Error('execution_history_invalid_query'));await flush();f.render();
  assert.match(f.text(),/筛选格式不正确/);assert.match(f.text(),/第 2 页/);assert.match(f.text(),/合成 second/);
  assert.equal(f.nodes().find(n=>n.type==='input'&&n.props.list).props.value,'awaiting_input');
  f.nodes().find(n=>n.type==='form').props.onSubmit({preventDefault(){}});await settle(f,page([]));
  assert.match(f.text(),/第 1 页/);assert.match(f.text(),/当前筛选没有执行记录/);
});

test('initial read errors are distinct from empty and late hidden-page results cannot replace a newer read',async()=>{
  const f=fixture();f.requests[0].reject(Error('execution_history_invalid_cursor'));await flush();f.render();
  assert.match(f.text(),/分页依据已失效/);assert.doesNotMatch(f.text(),/当前筛选没有执行记录/);
  f.button('刷新记录').props.onClick();const older=f.requests.at(-1);f.setActive(false);f.setActive(true);const fresh=f.requests.at(-1);
  await settle(f,page([record('agent','fresh')]),fresh);await settle(f,page([record('agent','stale')]),older);
  assert.match(f.text(),/合成 fresh/);assert.doesNotMatch(f.text(),/合成 stale/);
});

test('pagination restores focus only after the enabled DOM commits and uses the stable page status at the final page',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
  f.click('下一页记录');assert.equal(f.document.activeElement,f.document.documentElement);
  assert.equal(f.button('下一页记录').props.disabled,true);assert.equal(f.focusCalls.length,0);
  f.requests.at(-1).resolve(page([record('agent','second')],'cursor-three'));await flush();
  assert.equal(f.focusCalls.length,0,'focus must wait for the commit which enables the trigger');
  f.render();assert.equal(f.document.activeElement,f.elements.get('execution-history-next'));
  assert.equal(f.focusCalls.at(-1).options.preventScroll,true);
  f.click('下一页记录');await settle(f,page([record('agent','last')]));
  assert.equal(f.button('下一页记录').props.disabled,true);
  assert.equal(f.document.activeElement,f.elements.get('execution-history-page'));
  assert.equal(f.elements.get('execution-history-page').tabIndex,-1);
});

test('returning to page one focuses the stable pagination status when the original control remains disabled',async()=>{
  for(const label of ['回到首页','上一页记录']){
    const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
    f.click('下一页记录');await settle(f,page([record('agent','second')],'cursor-three'));
    f.click(label);assert.equal(f.document.activeElement,f.document.documentElement);
    await settle(f,page([record('agent','first')],'cursor-two'));
    assert.equal(f.button(label).props.disabled,true);
    assert.equal(f.document.activeElement,f.elements.get('execution-history-page'));
    assert.match(f.text(),/第 1 页/);
  }
});

test('refresh and failed filter submission return to their triggers but never take focus from another control',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
  f.click('刷新记录');await settle(f,page([record('agent','refreshed')],'cursor-two'));
  assert.equal(f.document.activeElement,f.elements.get('execution-history-refresh'));
  f.apply();f.requests.at(-1).reject(Error('execution_history_invalid_query'));await flush();f.render();
  assert.equal(f.document.activeElement,f.elements.get('execution-history-apply'));
  assert.match(f.text(),/筛选格式不正确/);assert.match(f.text(),/合成 refreshed/);
  f.click('刷新记录');const outside=f.element('user-selected-filter');f.document.activeElement=outside;
  const calls=f.focusCalls.length;await settle(f,page([record('agent','latest')],'cursor-two'));
  assert.equal(f.document.activeElement,outside);assert.equal(f.focusCalls.length,calls);
});

test('initial, hidden and superseded reads never restore a previous request trigger',async()=>{
  const f=fixture();await settle(f,page([record('agent','first')],'cursor-two'));
  assert.equal(f.focusCalls.length,0,'initial reads have no user trigger');
  f.click('刷新记录');const old=f.requests.at(-1);f.setActive(false);f.setActive(true);const fresh=f.requests.at(-1);
  f.document.activeElement=f.document.body;
  await settle(f,page([record('agent','stale')]),old);assert.equal(f.focusCalls.length,0);
  await settle(f,page([record('agent','fresh')]),fresh);assert.equal(f.focusCalls.length,0);
  assert.equal(f.document.activeElement,f.document.body);assert.match(f.text(),/合成 fresh/);
});
