"""Explicit signed-in Codex CLI inference, isolated from project tools/configuration."""
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import tempfile
import time
from .model_worker import STRUCTURED_SYSTEM

KNOWN_BINARIES=(Path('/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex'),
                Path('/Applications/Codex.app/Contents/Resources/codex'))
# Finish and retain the transport outcome before the default 90s chain fuse.
TIMEOUT_SECONDS=85


class Cancelled(Exception):pass


def attempt_diagnostic(path,started,reason,returncode):
    stage='process_started';rank=0
    stages={'thread.started':(1,'session_started'),'turn.started':(2,'model_started'),
            'item.completed':(3,'message_received'),'turn.completed':(4,'turn_completed')}
    with path.open('rb')as source:raw=source.read(1000000)
    for line in raw.splitlines():
        try:event=json.loads(line)
        except (ValueError,UnicodeError):continue
        if not isinstance(event,dict):continue
        item=event.get('item')
        if event.get('type')=='item.completed'and(not isinstance(item,dict)or item.get('type')!='agent_message'):continue
        current=stages.get(event.get('type'))
        if current and current[0]>rank:rank,stage=current
    # No response text, stderr, prompts, paths, session IDs or credentials.
    return {'provider':'codex_cli','stage':stage,'reason':reason,
            'elapsed_seconds':round(time.monotonic()-started,3),
            'returncode':returncode,'automatic_retry':False}


def failure_diagnostic(error):
    seen=set()
    while error is not None and id(error)not in seen:
        seen.add(id(error));value=getattr(error,'provider_diagnostic',None)
        if (isinstance(value,dict)and value.get('provider')=='codex_cli'and
            value.get('stage')in('process_started','session_started','model_started','message_received','turn_completed')and
            value.get('reason')in('invalid_response','cli_exit','deadline','cancelled')and
            type(value.get('elapsed_seconds'))in(int,float)and math.isfinite(value['elapsed_seconds'])and value['elapsed_seconds']>=0 and
            (value.get('returncode')is None or type(value['returncode'])is int)):
            return {key:value.get(key)for key in('provider','stage','reason','elapsed_seconds','returncode')}|{'automatic_retry':False}
        error=error.__cause__ or error.__context__
    return None


def route(state):
    path=Path(state)/'agent-model.json'
    if not path.exists():return {'provider':'hermes'}
    try:
        if path.stat().st_size>1024:raise ValueError()
        value=json.loads(path.read_text())
        if not isinstance(value,dict) or set(value)-{'provider','model'}:raise ValueError()
        if value.get('provider') not in ('codex','hermes'):raise ValueError()
        if value['provider']=='codex' and (not isinstance(value.get('model'),str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,99}',value['model'])):raise ValueError()
        if value['provider']=='hermes' and set(value)!={'provider'}:raise ValueError()
        return value
    except (OSError,ValueError,TypeError):raise ValueError('agent_model_route_invalid') from None


def schema(observations=(),generative=False):
    def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
    string={'type':'string'}
    strings={'type':'array','items':string}
    references=list(dict.fromkeys(item['id'] for item in observations))
    evidence={'type':'array','items':{'type':'string','enum':references},'minItems':1} if references else {'type':'array','items':string,'maxItems':0}
    call=obj({'tool':string,'arguments_json':string})
    proposal=obj({'operation':{'type':'string','enum':['report','unit_economics','restock_plan','intel_review','organization_handoff','exposure_review']},
                  'reason':string,'evidence_ref':string})
    spec=obj({'decision':{'anyOf':[
        obj({'phase':{'type':'string','enum':['inspect']},'calls':{'type':'array','items':call}}),
        obj({'phase':{'type':'string','enum':['answer']},'answer':string,'questions':strings,'evidence_refs':evidence,'proposals':{'type':'array','items':proposal}})
    ]}})
    if generative:
        from generative.catalog import selection_schema
        answer=spec['properties']['decision']['anyOf'][1]
        answer['properties']['ui']=selection_schema();answer['required'].append('ui')
    return spec


def command(work, config):
    executable=shutil.which('codex') or next((str(p) for p in KNOWN_BINARIES if p.is_file() and os.access(p,os.X_OK)),None)
    if not executable:raise ValueError('agent_model_setup_required')
    # Do not inherit a user's MCP servers, plugins, instructions, hooks or project.
    # Authentication remains managed by the installed CLI, never extracted here.
    flags={'model':config['model'],'model_reasoning_effort':'low','web_search':'disabled',
           'model_instructions_file':str(work/'instructions.txt'),'project_doc_max_bytes':0,
           'skills.include_instructions':False,'skills.bundled.enabled':False,
           'features.skip_host_skill_discovery':True,'suppress_unstable_features_warning':True,
           'features.shell_tool':False,'features.view_image':False,'features.plugins':False,
           'features.apps':False,'features.multi_agent':False,'features.browser_use':False,
           'features.computer_use':False,'features.image_generation':False,'features.memories':False,
           'features.js_repl':False,'features.code_mode':False,'features.hooks':False,
           'features.tool_suggest':False,'features.goals':False,'features.responses_websockets':False,
           'features.responses_websockets_v2':False,'tools.update_plan.enabled':False,
           'tools.experimental_request_user_input.enabled':False}
    cmd=[executable,'exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
         '--sandbox','read-only','--cd',str(work),'--json','--output-schema',str(work/'schema.json'),
         '--output-last-message',str(work/'answer.json')]
    for key,value in flags.items():cmd+=['-c',key+'='+json.dumps(value)]
    return cmd


def decode(value):
    if not isinstance(value,dict) or set(value)!={'decision'}:raise ValueError('agent_model_invalid_response')
    decision=value['decision']
    if not isinstance(decision,dict):raise ValueError('agent_model_invalid_response')
    if decision.get('phase')=='inspect':
        if set(decision)!={'phase','calls'} or not isinstance(decision['calls'],list) or not 1<=len(decision['calls'])<=2:raise ValueError('agent_model_invalid_response')
        calls=[]
        for call in decision['calls']:
            if not isinstance(call,dict) or set(call)!={'tool','arguments_json'} or not isinstance(call['tool'],str) or not isinstance(call['arguments_json'],str):raise ValueError('agent_model_invalid_response')
            try:args=json.loads(call['arguments_json'])
            except ValueError:raise ValueError('agent_model_invalid_json') from None
            if not isinstance(args,dict):raise ValueError('agent_model_invalid_response')
            calls.append({'tool':call['tool'],'arguments':args})
        return {'phase':'inspect','calls':calls}
    if decision.get('phase')!='answer' or set(decision)-{'ui'}!={'phase','answer','questions','evidence_refs','proposals'}:raise ValueError('agent_model_invalid_response')
    # Full semantic limits, evidence and operation allowlists remain in AgentRuntime.
    return decision


def check_events(output):
    completed=False
    for line in output.splitlines():
        try:event=json.loads(line)
        except ValueError:raise ValueError('agent_model_invalid_response') from None
        if event.get('type')=='turn.completed':completed=True
        item=event.get('item',{})
        if item.get('type') not in (None,'agent_message','reasoning','error'):
            raise ValueError('agent_provider_unexpected_tool')
    if not completed:raise ValueError('agent_provider_outcome_unknown')


def native_receipt(output, model):
    """Bind a settled, tool-free native turn to the identity emitted by the CLI."""
    check_events(output)
    events=[json.loads(line) for line in output.splitlines()]
    identities={event.get('thread_id') for event in events if event.get('type')=='thread.started'}
    if len(identities)!=1 or not all(isinstance(value,str) and 0<len(value)<=200 for value in identities):
        raise ValueError('agent_model_invalid_response')
    return {'session_id':identities.pop(),'provider':'codex','model':model,
            'finish_reason':'completed','tools_used':[]}


def stop(process):
    # The leader exiting does not imply its owned group has stopped.
    try:os.killpg(process.pid,signal.SIGTERM)
    except ProcessLookupError:pass
    try:process.wait(timeout=2)
    except subprocess.TimeoutExpired:pass
    try:os.killpg(process.pid,signal.SIGKILL)
    except ProcessLookupError:pass
    process.wait(timeout=2)


def invoke_json(payload, cancelled, config, output_schema, instructions, *, input_limit=100000, response_limit=40000, with_receipt=False, images=()):
    if cancelled():raise Cancelled()
    # An empty temporary working directory prevents ancestor project discovery.
    # All temporary outputs are owned and removed; no CLI auth is copied.
    with tempfile.TemporaryDirectory(prefix='commerce-model-') as folder:
        work=Path(folder)
        (work/'schema.json').write_text(json.dumps(output_schema))
        (work/'instructions.txt').write_text(instructions+'\nDo not call any built-in Codex tools. Use only the supplied input and return the required JSON.\n')
        attachments=[]
        if not isinstance(images,(list,tuple)) or len(images)>4:raise ValueError('agent_model_image_limit')
        for index,source in enumerate(images):
            source=Path(source)
            if source.is_symlink() or not source.is_file() or source.stat().st_size>8*1024*1024:raise ValueError('agent_model_invalid_image')
            raw=source.read_bytes()
            suffix='.png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if raw.startswith(b'\xff\xd8\xff') else None
            if not suffix:raise ValueError('agent_model_invalid_image')
            target=work/('reference-'+str(index)+suffix);target.write_bytes(raw);target.chmod(0o600);attachments+=['--image',str(target)]
        encoded=json.dumps(payload,ensure_ascii=False).encode()
        if len(encoded)>input_limit:raise ValueError('agent_model_input_too_large')
        # Do not forward commerce, device, platform or unrelated API credentials.
        allowed={'PATH','HOME','USER','LOGNAME','TMPDIR','LANG','LC_ALL','CODEX_HOME',
                 'HTTPS_PROXY','HTTP_PROXY','ALL_PROXY','NO_PROXY','https_proxy','http_proxy','all_proxy','no_proxy',
                 'SSL_CERT_FILE','SSL_CERT_DIR'}
        env={key:value for key,value in os.environ.items() if key in allowed}
        with (work/'request.json').open('wb+') as input_file,(work/'events.jsonl').open('wb+') as output,(work/'stderr.log').open('wb+') as errors:
            input_file.write(encoded);input_file.seek(0)
            process=subprocess.Popen(command(work,config)+attachments,stdin=input_file,stdout=output,stderr=errors,
                                     env=env,cwd=work,start_new_session=True)
            from generative.streaming import enabled,mode
            from generative.codex_events import MessageEvents
            event_stream=MessageEvents();read_at=0
            if enabled():mode('provider_events')
            def receive_events():
                nonlocal read_at
                if not enabled():return
                with (work/'events.jsonl').open('rb') as reader:
                    reader.seek(read_at);chunk=reader.read(1000001);read_at+=len(chunk)
                event_stream.feed(chunk)
            try:
                started=time.monotonic();end=started+TIMEOUT_SECONDS;reason='invalid_response'
                while process.poll() is None:
                    receive_events()
                    if cancelled():reason='cancelled';raise Cancelled()
                    if time.monotonic()>end:reason='deadline';raise ValueError('agent_provider_outcome_unknown')
                    if output.tell()>1000000 or errors.tell()>1000000:raise ValueError('agent_model_response_too_large')
                    time.sleep(.1)
                if cancelled():reason='cancelled';raise Cancelled()
                receive_events()
                if process.returncode:
                    reason='cli_exit'
                    diagnostic=attempt_diagnostic(work/'events.jsonl',started,reason,process.returncode)
                    raise ValueError('agent_provider_outcome_unknown'if diagnostic['stage']in('model_started','message_received')else'agent_provider_failed_no_automatic_retry')
                output.seek(0);events=output.read(1000001).decode('utf-8');check_events(events)
                response=work/'answer.json'
                if not response.is_file():raise ValueError('agent_model_invalid_response')
                if response.stat().st_size>response_limit:raise ValueError('agent_model_response_too_large')
                try:value=json.loads(response.read_text())
                except ValueError:raise ValueError('agent_model_invalid_json') from None
                return {'data':value,'receipt':native_receipt(events,config['model'])} if with_receipt else value
            except BaseException as error:
                error.provider_diagnostic=attempt_diagnostic(work/'events.jsonl',started,reason,process.poll())
                raise
            finally:stop(process)


def invoke(payload, cancelled, config):
    value=invoke_json(payload,cancelled,config,schema(payload.get('observations',[]),generative=bool(payload.get('ui_catalog'))),STRUCTURED_SYSTEM)
    return {'decision':decode(value),'provider':'codex_cli','model':config['model']}
