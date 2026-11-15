// Run existing offline suites with fresh private states; never reuse a peer service.
import {spawn} from 'node:child_process';
import {mkdtemp,mkdir,copyFile,writeFile,rm} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import net from 'node:net';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
const root=path.dirname(path.dirname(fileURLToPath(import.meta.url))),base=await mkdtemp(path.join(tmpdir(),'workbench-suite-'));
const kind=process.argv[2];assert.ok(['skills','creative'].includes(kind));
const evidence=path.join(root,'../.commerce-state/verification/workbench-quality',kind);await mkdir(evidence,{recursive:true});
const state=path.join(base,'state');await mkdir(state);await writeFile(path.join(state,'auth.token'),'synthetic-isolated-suite');
const listener=net.createServer();await new Promise(r=>listener.listen(0,'127.0.0.1',r));const port=listener.address().port;await new Promise(r=>listener.close(r));
const env={...process.env,COMMERCE_STATE:state,COMMERCE_PORT:String(port),SKILLS_QA_STATE:state,SKILLS_QA_DIR:evidence,CREATIVE_QA_DIR:evidence};
let server;const delay=ms=>new Promise(r=>setTimeout(r,ms));
try{
 if(kind==='creative'){
  await mkdir(path.join(evidence,'state'),{recursive:true});await copyFile(path.join(state,'auth.token'),path.join(evidence,'state/auth.token'));
  for(const name of ['synthetic-reference.mp4','synthetic-product.png','synthetic-tone.wav'])await copyFile(path.join(root,'../.local/creative-acceptance',name),path.join(evidence,name));
 }
 server=spawn('python3',[path.join(root,'server.py')],{env,stdio:'ignore'});
 let ready=false;for(let i=0;i<100;i++){try{if((await fetch('http://127.0.0.1:'+port+'/v1/health',{headers:{Authorization:'Bearer synthetic-isolated-suite'}})).ok){ready=true;break}}catch{}await delay(100)}assert.ok(ready);
 const child=spawn(process.execPath,[path.join(root,'qa',kind==='skills'?'skills_ui.mjs':'creative_ui.mjs')],{env,stdio:'inherit'});
 const code=await new Promise((r,j)=>{child.on('error',j);child.on('close',r)});assert.equal(code,0);
}finally{server?.kill('SIGTERM');await delay(400);await rm(base,{recursive:true,force:true})}
