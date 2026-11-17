"""Incremental JSON answer decoding; never forwards raw reasoning or tool args."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
from .catalog import select

_sink=ContextVar('commerce_ui_delta_sink',default=None)

def enabled():return _sink.get() is not None

def emit(delta):
    sink=_sink.get()
    if sink is not None:sink(delta)

def mode(value):
    sink=_sink.get();preview=getattr(sink,'__self__',None)
    if isinstance(preview,Preview) and value in ('provider_deltas','provider_final_only','provider_events','host_final_only'):
        preview.sink({'type':'reset','mode':value})

@contextmanager
def capture(sink):
    token=_sink.set(sink)
    try:yield
    finally:_sink.reset(token)

def partial_string(text,start):
    """Decode complete Unicode characters only, including paired JSON surrogates."""
    out=[];i=start
    while i<len(text):
        char=text[i]
        if char=='"':return ''.join(out),i+1,True
        if char=='\\':
            if i+1>=len(text):break
            if text[i+1]=='u':
                end=i+6
                if len(text)<end:break
                try:code=int(text[i+2:end],16)
                except ValueError:break
                if 0xD800<=code<=0xDBFF:
                    end=i+12
                    if len(text)<end or text[i+6:i+8]!='\\u':break
                try:char=json.loads('"'+text[i:end]+'"')
                except ValueError:break
                if any(0xD800<=ord(c)<=0xDFFF for c in char):break
                out.append(char);i=end;continue
            try:char=json.loads('"'+text[i:i+2]+'"')
            except ValueError:break
            i+=2;out.append(char);continue
        if ord(char)<32:break
        out.append(char);i+=1
    return ''.join(out),i,False

def fields(text):
    """Only root decision members, never nested strings named answer/ui."""
    decoder=json.JSONDecoder();i=0;result={}
    text=text.lstrip()
    if not text.startswith('{'):return result
    i=1
    while i<len(text):
        while i<len(text) and text[i] in ' \r\n\t,':i+=1
        if i>=len(text) or text[i]!='"':break
        try:key,end=decoder.raw_decode(text,i)
        except ValueError:break
        i=end
        while i<len(text) and text[i].isspace():i+=1
        if i>=len(text) or text[i]!=':':break
        i+=1
        while i<len(text) and text[i].isspace():i+=1
        if key=='decision' and i<len(text) and text[i]=='{':return fields(text[i:])
        if i>=len(text):break
        if key=='answer' and text[i]=='"':
            value,end,complete=partial_string(text,i+1);result[key]=value
            if not complete:break
            i=end;continue
        if key=='ui' and text[i]=='[':
            j=i+1;entries=[]
            while j<len(text):
                while j<len(text) and text[j] in ' \r\n\t,':j+=1
                try:value,end=decoder.raw_decode(text,j)
                except ValueError:break
                entries.append(value);j=end
            result['ui']=entries
        try:value,end=decoder.raw_decode(text,i)
        except ValueError:break
        result[key]=value;i=end
    return result

class Preview:
    def __init__(self,sink,observations,run_id='preview'):
        self.sink=sink;self.observations=observations;self.run_id=run_id;self.raw='';self.answer='';self.components=[]

    def feed(self,delta):
        if not isinstance(delta,str) or len(self.raw)+len(delta)>40000:return
        self.raw+=delta;value=fields(self.raw)
        if value.get('phase')!='answer':return
        answer=value.get('answer','')[:5000]
        # Every event is a genuine received increment, never synthetic typing.
        if len(answer)>len(self.answer) and answer.startswith(self.answer):
            self.sink({'type':'answer_delta','delta':answer[len(self.answer):]});self.answer=answer
        for entry in value.get('ui',[])[len(self.components):12]:
            try:select(self.components+[entry],self.observations)
            except ValueError:break
            from .catalog import present
            self.components.append(entry)
            card=present({'id':self.run_id,'result':{'ui':[entry],'observations':self.observations}})['components'][0]
            self.sink({'type':'component','selection':entry,'component':card})
