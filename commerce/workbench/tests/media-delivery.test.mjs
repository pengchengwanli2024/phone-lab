import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
const kit=readFileSync(new URL('../../ui/kit.js',import.meta.url),'utf8');
function fixture(){
 const window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})},document={documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}}};
 const c=vm.createContext({window,document,CustomEvent:globalThis.CustomEvent,crypto:globalThis.crypto});
 vm.runInContext(kit,c);vm.runInContext(readFileSync(new URL('../../web/media-delivery-ui.js',import.meta.url),'utf8'),c);
 return window.CommerceMediaDeliveryFlow();
}
const c={sha256:'commit',duration_ms:3750,width:720,height:1280,requirements:{source_policy:'allow_stills',audio_policy:'no_audio',allow_looping:false,sample_duration_ms:1500}};
const sample={id:'sample',spec:{delivery_commitment:c,delivery_role:'sample'},delivery:{role:'sample',full_request_id:'full',source_request_id:'base'},assets:[{}],result_sha256:'result',review:null};
test('sample acknowledgement binds to the displayed output and never survives an output change',()=>{
 const f=fixture();assert.equal(f.canApprove(sample),false);
 f.input({target:{dataset:{deliveryField:'ack'},checked:true}},sample);
 assert.equal(f.canApprove(sample),true);
 assert.equal(f.reviewArgs(sample).sample_review.commitment_sha256,'commit');
 assert.equal(f.canApprove({...sample,result_sha256:'changed'}),false);
 assert.match(f.view(sample,false),/已完整观看本次样片/);
});
test('full render stays blocked until server gate ready while legacy requests stay usable',()=>{
 const f=fixture();assert.equal(f.canExecute({delivery:{role:'full',gate:'sample_required'}}),false);
 assert.equal(f.canExecute({delivery:{role:'full',gate:'ready'}}),true);
 assert.equal(f.canExecute({}),true);
 assert.match(f.view({...sample,delivery:{...sample.delivery,role:'full',gate:'sample_rejected'}},false),/样片已退回/);
});
test('preparation is explicit and an uncertain response retains the same idempotency intent',async()=>{
 const f=fixture(),r={id:'base',request_sha256:'version',spec:{format:'showcase_video',duration_ms:3750},assets:[]};
 const calls=[];let fail=true;
 const api=async(name,args)=>{calls.push({name,args});if(fail)throw Error('unknown');return{sample:{id:'new-sample'}}};
 await assert.rejects(f.prepare(api,r,['a','b'],null));fail=false;await f.prepare(api,r,['a','b'],null);
 assert.equal(calls.length,2);assert.equal(calls[0].name,'commerce_media_delivery_prepare');
 assert.equal(calls[0].args.idempotency_key,calls[1].args.idempotency_key);
 assert.equal(calls[0].args.requirements.sample_duration_ms,1500);
 assert.match(f.view(r,false),/保存交付承诺并建立样片/);
});

test('existing production page uses pinned sample selections and disables unapproved full execution',async()=>{
 const listeners={},document={documentElement:{dataset:{},getAttribute(){return'light'},setAttribute(){}},addEventListener(name,fn){(listeners[name]||=[]).push(fn)}},window={dispatchEvent(){},matchMedia:()=>({matches:false,addEventListener(){}})};
 const context=vm.createContext({window,document,CustomEvent:globalThis.CustomEvent,crypto:globalThis.crypto,queueMicrotask,setTimeout,clearTimeout});
 for(const text of [kit,readFileSync(new URL('../../web/media-delivery-ui.js',import.meta.url),'utf8'),readFileSync(new URL('../../web/media-workflow-ui.js',import.meta.url),'utf8')])vm.runInContext(text,context);
 const spec={format:'showcase_video',duration_ms:3750,shots:[{start_ms:0,end_ms:3750,role:'demonstration',framing:'合成',action:'查看'}],objective:'合成验收',prompt:'合成提示',delivery_commitment:c};
 const full={id:'full',spec:{...spec,delivery_role:'full'},request_sha256:'full-sha',assets:[],delivery:{role:'full',gate:'sample_required',asset_ids:['pinned'],sample_request_id:'sample',source_request_id:'base'}};
 const sampleRequest={...sample,spec:{...spec,delivery_role:'sample'},request_sha256:'sample-sha',assets:[],delivery:{...sample.delivery,asset_ids:['sample-pinned']}};
 const project={id:'p',revision:'3',assets:[],brief:{}},calls=[];
 const flow=window.CommerceMediaFlow({api:async(name,args)=>{calls.push({name,args});return name==='commerce_media_overview'?{requests:[full,sampleRequest],policy:{interval_days:7,enabled:false}}:{job_id:null}},repaint(){},getProject:()=>project});
 await flow.openRequest('full');const html=flow.view(),button=html.match(/<button[^>]+data-media-action="execute"[^>]*>/)?.[0];assert.ok(button);assert.match(button,/disabled/);assert.doesNotMatch(html,/data-media-field="shot\./);
 await flow.openRequest('sample');const b={dataset:{mediaAction:'execute'},disabled:false,closest(){return b}};
 await listeners.click[0]({target:{closest(){return b}},preventDefault(){}});
 const execution=calls.find(x=>x.name==='commerce_media_request_execute');assert.deepEqual(Array.from(execution.args.asset_ids),['sample-pinned']);assert.equal(execution.args.request_id,'sample');
 assert.equal(calls.filter(x=>x.name==='commerce_media_request_execute').length,1);
});
