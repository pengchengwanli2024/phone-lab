// Installed Harness runtime, isolated profile and synthetic commerce state.
// Browser interaction belongs to CUA; this only starts the native host backend.
import {fork,execFileSync} from 'node:child_process';
import {readFile,writeFile,mkdir,symlink,mkdtemp} from 'node:fs/promises';
import {tmpdir} from 'node:os';
import path from 'node:path';
const root=path.resolve(import.meta.dirname,'..');
const config=JSON.parse(await readFile(process.argv[2],'utf8'));
const temp=await mkdtemp(path.join(tmpdir(),'product-workspace-host-'));
const profile=path.join(temp,'profile');
await mkdir(path.join(profile,'node_modules/@local'),{recursive:true});
const bundle=execFileSync(process.env.COMMERCE_PYTHON||'python3',['-c','import sys;sys.path.insert(0,sys.argv[1]);from harness_local_bundle import prepare;print(prepare(sys.argv[1],sys.argv[2],sys.executable))',root,path.join(temp,'bundle')],{encoding:'utf8'}).trim();
await symlink(bundle,path.join(profile,'node_modules/@local/dsh-commerce'));
await writeFile(path.join(profile,'package.json'),JSON.stringify({name:'product-workspace-isolated',private:true,dependencies:{'@local/dsh-commerce':'link:'+bundle},dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@local/dsh-commerce']}}}));
const resources='/Applications/DeepSeek Harness.app/Contents/Resources',runtime=resources+'/app.asar/dsh';
const host=fork(runtime+'/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js',[runtime,profile,resources+'/runtime/primary-runtime',resources+'/runtime/primary-runtime/dependencies/pnpm/bin/pnpm.mjs',resources+'/runtime/bin'],{execPath:'/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness',execArgv:['--expose-internals'],env:{...process.env,ELECTRON_RUN_AS_NODE:'1',DSH_CLIENT_VERSION:'0.2.2-rc.1',DSH_HOME:path.join(temp,'dsh-home'),COMMERCE_STATE:config.state,COMMERCE_PORT:String(config.port),COMMERCE_PYTHON:process.env.COMMERCE_PYTHON||'/opt/homebrew/bin/python3'},stdio:['ignore','pipe','pipe','ipc']});
const messages=[];
for(const stream of [host.stdout,host.stderr])stream.on('data',chunk=>{
 for(const line of String(chunk).split('\n'))if(/error|failed|cannot|missing/i.test(line)&&!/token|cookie|authorization|bearer|https?:/i.test(line))messages.push(line.slice(0,400));
});
host.on('message',async message=>{
 if(message.type==='ready'){
  await writeFile(path.join(config.state,'native-host.json'),JSON.stringify({url:message.url,pid:host.pid,temp}),{mode:0o600});
  console.log(JSON.stringify({native_origin:new URL(message.url).origin,open_via:`http://127.0.0.1:${config.port}/harness-open`,runtime:'0.2.2-rc.1',isolated:true}));
 }else if(message.type==='fatal')console.log(JSON.stringify({status:'failed',message:String(message.message).replace(/https?:\S+|token=\S+/g,'<redacted>')}));
});
host.on('exit',async code=>{await writeFile(path.join(config.out,'native-host-errors.json'),JSON.stringify({code,messages},null,2));process.exitCode=code||0});
process.on('SIGTERM',()=>host.kill('SIGTERM'));
