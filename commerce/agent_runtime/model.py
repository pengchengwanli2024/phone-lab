"""Explicit private Codex or existing Hermes route in owned bounded processes."""
import json
from pathlib import Path
import subprocess
import time
from translation import model_command


class Cancelled(Exception):pass


def invoke(payload, cancelled, route=None):
    if route and route.get('provider')=='compatible':
        from model_providers import inference
        try:return inference.invoke(payload,cancelled,route)
        except inference.Cancelled:raise Cancelled() from None
    if route and route.get('provider')=='codex':
        from . import codex_provider
        try:return codex_provider.invoke(payload,cancelled,route)
        except codex_provider.Cancelled:raise Cancelled() from None
    try:command,env=model_command()
    except ValueError as error:
        if str(error) in ('translation_hermes_unavailable','translation_profile_unavailable','translation_runtime_unavailable'):
            raise ValueError('agent_model_setup_required') from None
        raise
    command[-1]=str(Path(__file__).with_name('model_worker.py'))
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             text=True,env=env,cwd=Path(__file__).parent)
    try:
        first=True;end=time.monotonic()+100
        while True:
            if cancelled():raise Cancelled()
            if time.monotonic()>end:raise ValueError('agent_provider_outcome_unknown')
            try:
                output,_=process.communicate(input=json.dumps(payload,ensure_ascii=False) if first else None,timeout=.25)
                break
            except subprocess.TimeoutExpired:first=False
        if process.returncode:raise ValueError('agent_provider_failed_no_automatic_retry')
        if len(output)>40000:raise ValueError('agent_model_response_too_large')
        try:return json.loads(output)
        except ValueError:raise ValueError('agent_model_invalid_json') from None
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):
            if stream:stream.close()
