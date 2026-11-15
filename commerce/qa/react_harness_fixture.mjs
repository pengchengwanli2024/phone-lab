// Launch only an isolated installed Harness SDK host; interact via the UI tool.
import { fork } from 'node:child_process';
import { mkdir, writeFile, symlink } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
const commerce = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const state = process.env.COMMERCE_STATE, port = process.env.COMMERCE_PORT;
if (!state || !port || !process.env.COMMERCE_PYTHON) throw Error('Isolated state, port and Python required');
const profile = path.join(state,'harness-profile');
await mkdir(path.join(profile,'node_modules/@local'),{recursive:true});
try { await symlink(path.join(commerce,'harness'),path.join(profile,'node_modules/@local/dsh-commerce')); } catch(error) { if(error.code!=='EEXIST') throw error; }
await writeFile(path.join(profile,'package.json'),JSON.stringify({name:'commerce-react-acceptance',private:true,dependencies:{'@local/dsh-commerce':'link:'+path.join(commerce,'harness')},dsh:{profile:{bundles:['@deepseek-ai/dsh-base','@deepseek-ai/dsh-web-app','@local/dsh-commerce']}}}));
const resources = '/Applications/DeepSeek Harness.app/Contents/Resources', runtime = resources+'/app.asar/dsh';
const host = fork(runtime+'/node_modules/@deepseek-ai/dsh-desktop-host/lib/index.js',[runtime,profile,resources+'/runtime/primary-runtime',resources+'/runtime/primary-runtime/dependencies/pnpm/bin/pnpm.mjs',resources+'/runtime/bin'],{execPath:'/Applications/DeepSeek Harness.app/Contents/MacOS/DeepSeek Harness',execArgv:['--expose-internals'],env:{...process.env,ELECTRON_RUN_AS_NODE:'1',DSH_CLIENT_VERSION:'0.2.2-rc.1',DSH_HOME:path.join(state,'harness-home')},stdio:['ignore','ignore','pipe','ipc']});
host.stderr.on('data',()=>{});
host.on('message',async message=>{
  if(message.type==='ready') {
    await writeFile(path.join(state,'native-host.json'),JSON.stringify({url:message.url,pid:host.pid}));
    console.log('Isolated installed Harness host ready; open the synthetic fixture /harness-open');
  } else if(message.type==='fatal') { console.error('Isolated Harness host failed to start'); process.exitCode=1; host.kill(); }
});
host.on('exit',code=>{process.exitCode=code||0;});
process.on('SIGTERM',()=>host.kill('SIGTERM'));
