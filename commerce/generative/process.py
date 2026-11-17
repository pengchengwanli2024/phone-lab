"""Read bounded JSON-line output from an already owned model subprocess."""
import json
import os
import selectors
import time
from .streaming import emit,mode

def receive(process,encoded,cancelled,cancel_type,timeout=100):
    process.stdin.write(encoded);process.stdin.close();process.stdin=None
    selector=selectors.DefaultSelector();selector.register(process.stdout,selectors.EVENT_READ)
    pending=b'';total=0;result=None;deadline=time.monotonic()+timeout
    def accept(raw):
        nonlocal result
        try:value=json.loads(raw)
        except ValueError:raise ValueError('agent_model_invalid_json') from None
        if type(value)is not dict:raise ValueError('agent_model_invalid_json')
        if set(value)=={'delta'}:emit(value['delta'])
        elif set(value)=={'stream_mode'}:mode(value['stream_mode'])
        else:result=value
    try:
        while selector.get_map():
            if cancelled():raise cancel_type()
            if time.monotonic()>deadline:raise ValueError('agent_provider_outcome_unknown')
            for key,_ in selector.select(.1):
                chunk=os.read(key.fd,8192)
                if not chunk:selector.unregister(key.fileobj);break
                total+=len(chunk)
                if total>1000000:raise ValueError('agent_model_response_too_large')
                pending+=chunk
                while b'\n' in pending:
                    raw,pending=pending.split(b'\n',1)
                    if raw.strip():accept(raw)
        if pending.strip():accept(pending)
        process.wait(timeout=2)
        if result is None:raise ValueError('agent_provider_outcome_unknown')
        if process.returncode:raise ValueError(result.get('error','agent_provider_failed_no_automatic_retry'))
        return result
    finally:selector.close()
