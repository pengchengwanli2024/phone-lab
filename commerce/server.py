from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import hashlib
import hmac
import json
import secrets
import fcntl
import signal
from runtime import ROOT,STATE,PORT,token
from response_links import with_workspace_link
from service import Commerce
from protocols.a2a import agent_card, dispatch as a2a_dispatch
from platform_connections.setup import page as platform_setup_page
from workspace_page import page as product_workspace_page
from react_page import page as react_workspace_page


def page():
    html=(ROOT/'web/index.html').read_text()
    return html.replace('/* INLINE_STYLE */',(ROOT/'web/style.css').read_text()).replace('/* INLINE_APP */',(ROOT/'web/app.js').read_text())


def setup_page():
    return (ROOT/'web/setup.html').read_text().replace('/* INLINE_STYLE */',(ROOT/'web/style.css').read_text()).replace('/* INLINE_KIT */',(ROOT/'ui/status.js').read_text()+'\n'+(ROOT/'ui/kit.js').read_text()).replace('/* INLINE_SETUP */',(ROOT/'web/setup.js').read_text())


class Handler(BaseHTTPRequestHandler):
    service=None
    secret=None
    protocol_version='HTTP/1.1'
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def log_message(self,*args):pass
    def answer(self,code,body,typ='application/json; charset=utf-8',headers=None):
        content=body.encode()if isinstance(body,str)else json.dumps(body,ensure_ascii=False).encode()
        if code>=400:self.close_connection=True
        self.send_response(code)
        for k,v in {'Content-Type':typ,'Content-Length':str(len(content)),'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',**({'Connection':'close'}if self.close_connection else{}),**(headers or{})}.items():self.send_header(k,v)
        self.end_headers();self.wfile.write(content)
    def trusted(self):
        host=self.headers.get('Host','')
        if host not in [f'127.0.0.1:{PORT}',f'localhost:{PORT}']:return False
        origin=self.headers.get('Origin')
        return not origin or origin in [f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}']
    def authenticated(self):
        header=self.headers.get('Authorization','')
        if header.startswith('Bearer ')and hmac.compare_digest(header[7:],self.secret):return True
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:return False
        return 'commerce_session'in cookie and hmac.compare_digest(cookie['commerce_session'].value,self.secret)
    def do_GET(self):
        if not self.trusted():return self.answer(403,{'error':'untrusted_origin'})
        parsed=urlparse(self.path)
        if parsed.path in ('/setup','/open','/platform-setup') and 'ticket' in parse_qs(parsed.query):
            ticket=parse_qs(parsed.query).get('ticket',[''])[0]
            if not self.service.live.consume_ticket(ticket):return self.answer(401,{'error':'setup_ticket_expired'})
            return self.answer(303,'',headers={'Location':parsed.path if parsed.path in ('/setup','/platform-setup') else '/','Set-Cookie':'commerce_session='+self.secret+'; HttpOnly; SameSite=Strict; Path=/'})
        if parsed.path=='/login':
            value=parse_qs(parsed.query).get('token',[''])[0]
            if not hmac.compare_digest(value,self.secret):return self.answer(401,{'error':'authentication_required'})
            return self.answer(303,'',headers={'Location':'/','Set-Cookie':'commerce_session='+self.secret+'; HttpOnly; SameSite=Strict; Path=/'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        if parsed.path=='/.well-known/agent-card.json':return self.answer(200,agent_card(f'http://127.0.0.1:{PORT}'))
        if parsed.path=='/v1/health':return self.answer(200,{'service':'commerce-backend','version':'0.1.0','status':'ready'})
        if parsed.path=='/':return self.answer(200,page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; media-src data: blob:; connect-src 'self'; frame-ancestors 'self'"})
        if parsed.path=='/workspace':return self.answer(200,react_workspace_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; media-src data: blob:; connect-src 'self'; frame-src 'self' about:; frame-ancestors 'self'"})
        if parsed.path=='/legacy':return self.answer(200,page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; media-src data: blob:; connect-src 'self'; frame-ancestors 'self'"})
        if parsed.path=='/product-workspace':return self.answer(200,product_workspace_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"})
        if parsed.path=='/setup':return self.answer(200,setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/platform-setup':return self.answer(200,platform_setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/v1/connections/status':return self.answer(200,self.service.live.status(samples=True))
        return self.answer(404,{'error':'not_found'})
    def do_POST(self):
        if not self.trusted():return self.answer(403,{'error':'untrusted_origin'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        route=urlparse(self.path).path
        allowed={'/a2a','/v1/invoke','/v1/connections/save','/v1/connections/sync','/v1/connections/test-feishu','/v1/connections/ticket','/v1/platforms/configure'}
        if route not in allowed:return self.answer(404,{'error':'not_found'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.answer(415,{'error':'json_required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=131072:return self.answer(413,{'error':'request_too_large'})
            data=json.loads(self.rfile.read(size))
            if route=='/a2a':return self.answer(200,a2a_dispatch(self.service,data))
            if route=='/v1/invoke':result=with_workspace_link(data['tool'],self.service.invoke(data['tool'],data.get('arguments',{}),data.get('client','local')),PORT)
            elif route=='/v1/connections/save':result=self.service.live.configure(data)
            elif route=='/v1/connections/sync':result=self.service.live.start_sync()
            elif route=='/v1/connections/test-feishu':result=self.service.live.test_feishu()
            elif route=='/v1/platforms/configure':result=self.service.platforms.configure(data)
            else:result={'ticket':self.service.live.new_setup_ticket()}
            return self.answer(200,result)
        except (ValueError,KeyError,TypeError) as e:return self.answer(400,{'error':str(e)if isinstance(e,ValueError)else'invalid_request'})
        except Exception:return self.answer(500,{'error':'internal_error'})


class CommerceHTTPServer(ThreadingHTTPServer):
    # One dashboard load issues seven requests. The stdlib default backlog is 5.
    request_queue_size=128
    daemon_threads=True


if __name__=='__main__':
    Handler.secret=token()
    state_lock=(STATE/'server.lock').open('a+')
    try:fcntl.flock(state_lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:raise SystemExit('commerce_state_already_served')
    Handler.service=Commerce(STATE)
    server=CommerceHTTPServer(('127.0.0.1',PORT),Handler)
    Handler.service.operations.start_timer()
    Handler.service.live.start_timer()
    Handler.service.articles.recover()
    Handler.service.collections.start(recover=True)
    Handler.service.autonomy.start(recover=True)
    Handler.service.agent_runtime.start(recover=True)
    (STATE/'runtime.json').write_text(json.dumps({'origin':f'http://127.0.0.1:{PORT}','pid':__import__('os').getpid(),'version':'0.1.0'}))
    def shutdown_signal(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown_signal)
    try:server.serve_forever()
    finally:
        Handler.service.platforms.stop()
        Handler.service.collections.stop()
        Handler.service.agent_runtime.stop()
        Handler.service.autonomy.stop()
        server.server_close()
