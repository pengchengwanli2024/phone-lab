"""Owned subprocess and bounded HTTP transport; never exposes server diagnostics."""
from pathlib import Path
import json,os,subprocess,sys,time

class Cancelled(Exception):pass

def invoke_json(payload,cancelled,config,instructions,max_tokens=2200,output_schema=None):
    if cancelled():raise Cancelled()
    request={'base_url':config['base_url'],'model':config['model'],'api_key':config.get('api_key',''),'json_mode':config.get('json_mode',True),'instructions':instructions,'payload':payload,'max_tokens':max_tokens,'output_schema':output_schema}
    encoded=json.dumps(request,ensure_ascii=False)
    if len(encoded.encode())>150000:raise ValueError('agent_model_input_too_large')
    allowed={'PATH','HOME','TMPDIR','LANG','LC_ALL','HTTP_PROXY','HTTPS_PROXY','ALL_PROXY','NO_PROXY','SSL_CERT_FILE','SSL_CERT_DIR'}
    env={k:v for k,v in os.environ.items() if k in allowed}
    process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        first=True;end=time.monotonic()+90
        while True:
            if cancelled():raise Cancelled()
            if time.monotonic()>end:raise ValueError('agent_provider_outcome_unknown')
            try:output,_=process.communicate(input=encoded if first else None,timeout=.2);break
            except subprocess.TimeoutExpired:first=False
        if len(output)>50000:raise ValueError('agent_model_response_too_large')
        try:result=json.loads(output)
        except ValueError:raise ValueError('agent_model_invalid_json') from None
        if process.returncode:raise ValueError(result.get('error','agent_provider_failed_no_automatic_retry'))
        return result
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()

def invoke(payload,cancelled,config):
    from agent_runtime.model_worker import SYSTEM
    if config.get('engine') in ('llama_cpp','vllm') and config.get('json_mode',True):
        from agent_runtime.codex_provider import schema,decode
        spec=schema(payload.get('observations',[]))
        inspect,answer=spec['properties']['decision']['anyOf']
        inspect['properties']['calls'].update(minItems=1,maxItems=2)
        answer['properties']['answer'].update(minLength=1,maxLength=5000)
        answer['properties']['questions'].update(maxItems=3)
        answer['properties']['proposals'].update(maxItems=3)
        if not payload.get('observations'):answer['properties']['questions']['minItems']=1
        menu=payload.get('tools',[])
        if menu:
            variants=[]
            for call in menu:
                shape=json.loads(json.dumps(inspect['properties']['calls']['items']))
                shape['properties']['tool']={'type':'string','enum':[call['tool']]}
                # Fixed scope arguments are encoded literally; open search inputs
                # remain subject to the parent runner's existing read validator.
                arguments=call.get('arguments',{})
                if not any(word in json.dumps(arguments) for word in ('at most','one ID','one id')):
                    shape['properties']['arguments_json']={'type':'string','enum':[json.dumps(arguments,ensure_ascii=False,separators=(',',':'))]}
                variants.append(shape)
            inspect['properties']['calls']['items']={'anyOf':variants}
        else:spec['properties']['decision']['anyOf']=[answer]
        instructions=SYSTEM+'\nTransport format: wrap your decision inside {"decision":...}. For inspect calls, use arguments_json as a JSON-encoded string instead of arguments. Follow the supplied JSON schema exactly.'
        result=invoke_json(payload,cancelled,config,instructions,output_schema=spec)
        return {**result,'decision':decode(result['decision'])}
    return invoke_json(payload,cancelled,config,SYSTEM)
