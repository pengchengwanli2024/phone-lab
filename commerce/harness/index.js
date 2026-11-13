import {readFile} from 'node:fs/promises';
import {fileURLToPath} from 'node:url';
import {execFile} from 'node:child_process';
import {promisify} from 'node:util';
import path from 'node:path';
import {startHostWorker} from './host-worker.js';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const state=process.env.COMMERCE_STATE||path.join(path.dirname(root),'.commerce-state');
const origin=`http://127.0.0.1:${process.env.COMMERCE_PORT||38731}`;
export const name='commerce-workspace';
export const inject=['connection'];

export async function apply(ctx){
  await promisify(execFile)(process.env.COMMERCE_PYTHON||'/usr/bin/python3',[path.join(root,'runtime.py')],{timeout:15000});
  // The workspace remains usable on hosts without the native Agent services.
  // No model runs until a human request freezes an explicit execution plan.
  ctx.inject(['agentDefaultModel','agents','sessionController','tools','sessionPersistence'],native=>{
    const stop=startHostWorker(native,{state,origin});
    native.on('dispose',stop);
  });
  ctx.connection.fetch.register({path:'/api/commerce/page',methods:['GET'],requestBody:'buffered',fetch:async()=>{
    const [html,css,js]=await Promise.all(['index.html','style.css','app.js'].map(file=>readFile(path.join(root,'web',file),'utf8')));
    return new Response(html.replace('/* INLINE_STYLE */',()=>css).replace('/* INLINE_APP */',()=>js),{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
  }});
  ctx.connection.fetch.register({path:'/api/commerce/product-workspace',methods:['GET'],requestBody:'buffered',fetch:async()=>{
    const [html,css,js]=await Promise.all(['product-workspace.html','product-workspace.bundle.css','product-workspace.bundle.js'].map(file=>readFile(path.join(root,'web',file),'utf8')));
    return new Response(html.replace('/* INLINE_STYLE */',()=>css).replace('/* INLINE_APP */',()=>js),{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
  }});
  ctx.connection.fetch.register({path:'/api/commerce/workspace',methods:['GET'],requestBody:'buffered',fetch:async()=>{
    const {stdout}=await promisify(execFile)(process.env.COMMERCE_PYTHON||'/usr/bin/python3',['-c','from react_page import page; print(page(),end="")'],{cwd:root,maxBuffer:8*1024*1024,timeout:15000});
    return new Response(stdout,{headers:{'content-type':'text/html; charset=utf-8','cache-control':'no-store'}});
  }});
  ctx.connection.fetch.register({path:'/api/commerce/invoke',methods:['POST'],requestBody:'buffered',fetch:async request=>{
    try{
      const body=await request.text();if(body.length>131072)return Response.json({error:'request_too_large'},{status:413});
      const data=JSON.parse(body);const token=(await readFile(path.join(state,'auth.token'),'utf8')).trim();
      const response=await fetch(origin+'/v1/invoke',{method:'POST',headers:{'content-type':'application/json','authorization':'Bearer '+token},body:JSON.stringify({tool:data.tool,arguments:data.arguments||{},client:'harness'}),signal:AbortSignal.timeout(15000)});
      return new Response(await response.text(),{status:response.status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});
    }catch{return Response.json({error:'commerce_service_unavailable'},{status:503})}
  }});
}
