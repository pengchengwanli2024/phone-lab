"""Fixed-endpoint bounded JSON transports, without redirects or ambient credentials."""
import http.client
import ipaddress
import json
import socket
import os
from pathlib import Path
import subprocess
import sys
import ssl
import time
from urllib.parse import urlsplit,urlencode
from .validation import endpoint,encoded

class OutcomeUnknown(ValueError):pass

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self,host,port,address,**kwargs):self.address=address;super().__init__(host,port,**kwargs)
    def connect(self):self.sock=socket.create_connection((self.address,self.port),self.timeout)

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,port,address,**kwargs):self.address=address;super().__init__(host,port,context=ssl.create_default_context(),**kwargs)
    def connect(self):
        raw=socket.create_connection((self.address,self.port),self.timeout)
        self.sock=self._context.wrap_socket(raw,server_hostname=self.host)

def request(url,method,payload,headers=None,timeout=8,notification=False):
    endpoint(url);p=urlsplit(url);host=p.hostname;port=p.port or (443 if p.scheme=='https' else 80)
    addresses=socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)
    if not addresses:raise ValueError('extension_plugin_endpoint_unavailable')
    for record in addresses:
        address=ipaddress.ip_address(record[4][0])
        if not (address.is_global or address.is_loopback and host in ('localhost','127.0.0.1','::1')):raise ValueError('extension_plugin_private_network_denied')
    address=addresses[0][4][0]
    cls=PinnedHTTPS if p.scheme=='https' else PinnedHTTP
    conn=cls(host,port,address,timeout=min(timeout,8));raw=encoded(payload,64000).encode();path=p.path or '/'
    headers={'Content-Type':'application/json','Accept':'application/json',**(headers or {})}
    if method=='GET':path+='?'+urlencode({'input':raw.decode()});body=None
    else:body=raw
    try:
        conn.request(method,path,body,headers);response=conn.getresponse()
        if response.status<200 or response.status>=300:raise ValueError('extension_plugin_http_rejected')
        length=response.getheader('Content-Length')
        if length and (not length.isdigit() or int(length)>128000):raise ValueError('extension_plugin_response_too_large')
        started=time.monotonic();chunks=[];count=0
        while True:
            if time.monotonic()-started>timeout:raise ValueError('extension_plugin_timeout')
            if conn.sock:conn.sock.settimeout(max(.1,min(2,timeout-(time.monotonic()-started))))
            piece=response.read(8192);count+=len(piece)
            if count>128000:raise ValueError('extension_plugin_response_too_large')
            if not piece:break
            chunks.append(piece)
        if notification and not chunks:return {},dict(response.getheaders())
        try:value=json.loads(b''.join(chunks))
        except (ValueError,UnicodeError):raise ValueError('extension_plugin_invalid_json') from None
        return value,dict(response.getheaders())
    finally:conn.close()

def _invoke(spec,args,headers=None):
    try:
        if spec['transport']=='http':return request(spec['endpoint'],spec['method'],args,headers)[0]
        # The endpoint/tool name are pinned from the definition. No discovery,
        # executable server command, arbitrary tool override or session reuse.
        headers=dict(headers or {})
        initial,response_headers=request(spec['endpoint'],'POST',{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'commerce-extension','version':'1'}}},headers)
        if initial.get('id')!=1 or 'error' in initial or not isinstance(initial.get('result'),dict):raise ValueError('extension_mcp_initialize_failed')
        session=next((v for k,v in response_headers.items() if k.lower()=='mcp-session-id'),None)
        if session:
            if not isinstance(session,str) or len(session)>200 or any(ord(c)<33 or ord(c)>126 for c in session):raise ValueError('extension_mcp_invalid_session')
            headers['Mcp-Session-Id']=session
        request(spec['endpoint'],'POST',{'jsonrpc':'2.0','method':'notifications/initialized','params':{}},headers,notification=True)
        value,_=request(spec['endpoint'],'POST',{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':spec['tool'],'arguments':args}},headers)
        if value.get('id')!=2 or 'error' in value or not isinstance(value.get('result'),dict) or value['result'].get('isError'):raise ValueError('extension_mcp_tool_failed')
        result=value['result']
        if 'structuredContent' in result:return result['structuredContent']
        return {'content':result.get('content',[]),'source':'mcp_tool_receipt'}
    except Exception:
        if spec['effect']=='external_write':raise OutcomeUnknown('extension_external_outcome_unknown') from None
        raise ValueError('extension_plugin_read_failed') from None


def invoke(spec,args,headers=None,cancelled=lambda:False):
    """An owned fixed Python worker bounds DNS, socket and parser lifetime."""
    if cancelled():raise ValueError('extension_cancelled')
    packet=encoded({'spec':spec,'args':args,'headers':headers or {}},80000)
    allowed={'PATH','TMPDIR','LANG','LC_ALL','SSL_CERT_FILE','SSL_CERT_DIR'}
    env={k:v for k,v in os.environ.items() if k in allowed}
    process=subprocess.Popen([sys.executable,'-I',str(Path(__file__).with_name('transport_worker.py'))],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,env=env)
    try:
        end=time.monotonic()+25;first=True
        while True:
            if cancelled() or time.monotonic()>end:
                if spec['effect']=='external_write':raise OutcomeUnknown('extension_external_outcome_unknown')
                raise ValueError('extension_plugin_cancelled_or_timeout')
            try:output,_=process.communicate(packet if first else None,timeout=.1);break
            except subprocess.TimeoutExpired:first=False
        if len(output.encode())>256000:raise ValueError('extension_plugin_response_too_large')
        try:value=json.loads(output)
        except ValueError:raise ValueError('extension_plugin_invalid_receipt') from None
        if process.returncode or 'error' in value:
            if spec['effect']=='external_write':raise OutcomeUnknown('extension_external_outcome_unknown')
            raise ValueError('extension_plugin_read_failed')
        return value['result']
    finally:
        if process.poll() is None:
            process.terminate()
            try:process.wait(timeout=1)
            except subprocess.TimeoutExpired:process.kill();process.wait(timeout=1)
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()
