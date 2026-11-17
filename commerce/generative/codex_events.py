"""Consume only documented agent-message items, never reasoning/tool output."""
import json
from .streaming import emit

class MessageEvents:
    def __init__(self):self.pending=b'';self.text={}
    def feed(self,chunk):
        self.pending+=chunk
        if len(self.pending)>1000000:raise ValueError('agent_model_response_too_large')
        while b'\n' in self.pending:
            raw,self.pending=self.pending.split(b'\n',1)
            try:event=json.loads(raw)
            except ValueError:raise ValueError('agent_model_invalid_response') from None
            item=event.get('item',{})
            if event.get('type') not in ('item.updated','item.completed') or item.get('type')!='agent_message':continue
            text=item.get('text');ident=item.get('id','answer')
            if not isinstance(text,str):continue
            before=self.text.get(ident,'')
            if text.startswith(before):emit(text[len(before):])
            self.text[ident]=text
