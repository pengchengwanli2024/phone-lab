"""No tools or project imports. One explicitly configured compatible HTTP request."""
import ipaddress,json,socket,sys,urllib.request,urllib.error
from urllib.parse import urlsplit

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def main():
    data=json.load(sys.stdin);url=data['base_url']+'/chat/completions';host=urlsplit(url).hostname
    handlers=[NoRedirect()]
    try:local=host=='localhost' or ipaddress.ip_address(host).is_private
    except ValueError:local=False
    if local:handlers.append(urllib.request.ProxyHandler({}))
    body={'model':data['model'],'stream':False,'max_tokens':data['max_tokens'],'temperature':0,'tools':[],
          'messages':[{'role':'system','content':data['instructions']},{'role':'user','content':json.dumps(data['payload'],ensure_ascii=False)}]}
    if data.get('output_schema'):body['response_format']={'type':'json_schema','json_schema':{'name':'commerce_decision','strict':True,'schema':data['output_schema']}}
    elif data['json_mode']:body['response_format']={'type':'json_object'}
    headers={'Content-Type':'application/json'}
    if data['api_key']:headers['Authorization']='Bearer '+data['api_key']
    request=urllib.request.Request(url,data=json.dumps(body,ensure_ascii=False).encode(),headers=headers)
    try:
        with urllib.request.build_opener(*handlers).open(request,timeout=65) as response:raw=response.read(262145)
    except (TimeoutError,socket.timeout):raise ValueError('agent_provider_outcome_unknown') from None
    except urllib.error.HTTPError as error:
        error.close();raise ValueError('agent_provider_request_rejected') from None
    except urllib.error.URLError as error:
        raise ValueError('agent_provider_outcome_unknown' if isinstance(error.reason,(TimeoutError,socket.timeout)) else 'agent_provider_unavailable') from None
    if len(raw)>262144:raise ValueError('agent_model_response_too_large')
    try:
        value=json.loads(raw);choice=value['choices'][0];message=choice['message']
        if choice.get('finish_reason') in ('length','content_filter'):raise ValueError()
        if message.get('tool_calls') or message.get('function_call'):raise ValueError('agent_provider_unexpected_tool')
        text=message['content']
        if not isinstance(text,str) or len(text)>40000:raise ValueError()
        text=text.strip()
        if text.startswith('```') and text.endswith('```'):text=text.split('\n',1)[1].rsplit('```',1)[0].strip()
        decision=json.loads(text)
        if not isinstance(decision,dict):raise ValueError()
    except (KeyError,IndexError,TypeError,ValueError) as error:
        if str(error)=='agent_provider_unexpected_tool':raise
        raise ValueError('agent_model_invalid_json') from None
    print(json.dumps({'decision':decision,'provider':'openai_compatible','model':data['model'],'reported_model':str(value.get('model',''))[:160]},ensure_ascii=False))

if __name__=='__main__':
    try:main()
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and str(error).startswith('agent_') else 'agent_provider_unavailable'
        print(json.dumps({'error':code}));sys.exit(1)
