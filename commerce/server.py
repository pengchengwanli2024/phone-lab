from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
import socket
import threading
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
from http_delivery import encode_html
from service import Commerce
from phone_bridge import PhoneBridge
from phone_fleet import PhoneFleet
from phone_scrcpy import ScrcpyBridge
from protocols.a2a import agent_card, dispatch as a2a_dispatch
from platform_connections.setup import page as platform_setup_page
from workspace_page import page as product_workspace_page
from react_page import page as react_workspace_page
from model_providers.setup import page as model_setup_page
from capability_setup import page as capability_setup_page


def page():
    html=(ROOT/'web/index.html').read_text()
    return html.replace('/* INLINE_STYLE */',(ROOT/'web/style.css').read_text()).replace('/* INLINE_APP */',(ROOT/'web/app.js').read_text())


def setup_page():
    return (ROOT/'web/setup.html').read_text().replace('/* INLINE_STYLE */',(ROOT/'web/style.css').read_text()).replace('/* INLINE_KIT */',(ROOT/'ui/status.js').read_text()+'\n'+(ROOT/'ui/kit.js').read_text()).replace('/* INLINE_SETUP */',(ROOT/'web/setup.js').read_text())


class Handler(BaseHTTPRequestHandler):
    service=None
    secret=None
    streams=set()
    scrcpy_streams=set()
    fleet_streams={}
    streams_lock=threading.Lock()
    protocol_version='HTTP/1.1'
    def setup(self):
        super().setup();self.connection.settimeout(15)
    def log_message(self,*args):pass
    def answer(self,code,body,typ='application/json; charset=utf-8',headers=None):
        content=body.encode()if isinstance(body,str)else json.dumps(body,ensure_ascii=False).encode()
        if code==200 and typ.startswith('text/html'):
            content,delivery_headers=encode_html(content,self.headers.get('Accept-Encoding'))
            headers={**delivery_headers,**(headers or{})}
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
        if parsed.path in ('/setup','/open','/platform-setup','/model-setup','/capability-setup','/phones') and 'ticket' in parse_qs(parsed.query):
            ticket=parse_qs(parsed.query).get('ticket',[''])[0]
            if not self.service.live.consume_ticket(ticket):return self.answer(401,{'error':'setup_ticket_expired'})
            destination=parsed.path if parsed.path in ('/setup','/platform-setup','/model-setup','/capability-setup','/phones') else '/'
            provider=parse_qs(parsed.query).get('platform',[''])[0]
            if parsed.path=='/platform-setup' and provider in {p['id']for p in self.service.platforms.catalog()['providers']}:destination+='?platform='+provider
            return self.answer(303,'',headers={'Location':destination,'Set-Cookie':'commerce_session='+self.secret+'; HttpOnly; SameSite=Strict; Path=/'})
        if parsed.path=='/login':
            value=parse_qs(parsed.query).get('token',[''])[0]
            if not hmac.compare_digest(value,self.secret):return self.answer(401,{'error':'authentication_required'})
            return self.answer(303,'',headers={'Location':'/','Set-Cookie':'commerce_session='+self.secret+'; HttpOnly; SameSite=Strict; Path=/'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        if parsed.path=='/.well-known/agent-card.json':return self.answer(200,agent_card(f'http://127.0.0.1:{PORT}'))
        if parsed.path=='/v1/health':return self.answer(200,{'service':'commerce-backend','version':'0.1.0','status':'ready'})
        if parsed.path in ('/','/workspace','/phones'):return self.answer(200,react_workspace_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; media-src data: blob:; worker-src blob:; connect-src 'self'; frame-src 'self' about:; frame-ancestors 'self'"})
        if parsed.path=='/legacy':return self.answer(200,page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; media-src data: blob:; worker-src blob:; connect-src 'self'; frame-ancestors 'self'"})
        if parsed.path=='/product-workspace':return self.answer(200,product_workspace_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data: blob:; media-src data: blob:; connect-src 'self'; frame-ancestors 'self'"})
        if parsed.path=='/setup':return self.answer(200,setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/platform-setup':return self.answer(200,platform_setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/model-setup':return self.answer(200,model_setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/capability-setup':return self.answer(200,capability_setup_page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"})
        if parsed.path=='/v1/connections/status':return self.answer(200,{**self.service.live.status(samples=True),'ozon_accounts':self.service.ozon_accounts.listing()})
        if parsed.path=='/phone/status':return self.answer(200,self.phone.status())
        if parsed.path=='/phone/fleet/status':return self.answer(200,self.fleet.status())
        if parsed.path=='/phone/fleet/frame':return self.fleet_frame(parsed)
        if parsed.path=='/phone/fleet/stream':return self.fleet_stream(parsed)
        if parsed.path=='/phone/scrcpy/status':self.scrcpy.touch();return self.answer(200,self.scrcpy.status())
        if parsed.path=='/phone/scrcpy':return self.phone_scrcpy_stream()
        if parsed.path=='/phone/frame':return self.phone_frame(parsed)
        if parsed.path=='/phone/stream':return self.phone_stream(parsed)
        return self.answer(404,{'error':'not_found'})
    def phone_frame(self, parsed):
        mime, body = self.phone.frame()
        if body is None:
            return self.answer(503, {'error': 'phone_frame_unavailable'})
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def fleet_frame(self, parsed):
        ident = parse_qs(parsed.query).get('id', [''])[0]
        mime, body = self.fleet.snapshot(ident)
        if body is None:
            return self.answer(503, {'error': 'phone_frame_unavailable'})
        self.send_response(200)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def fleet_stream(self, parsed):
        ident = parse_qs(parsed.query).get('id', [''])[0]
        if not self.fleet.live(ident):
            return self.answer(503, {'error': 'phone_stream_unavailable'})
        with Handler.streams_lock:
            old = Handler.fleet_streams.pop(ident, None)
            if old is not None:
                try:
                    old.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    old.close()
                except OSError:
                    pass
            Handler.fleet_streams[ident] = self.connection
        self.connection.settimeout(12)
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            for mime, body in self.fleet.frames(ident):
                header = ('--frame\r\nContent-Type: ' + mime + '\r\nContent-Length: ' + str(len(body)) + '\r\n\r\n').encode()
                self.wfile.write(header)
                self.wfile.write(body)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError, ValueError):
            pass
        finally:
            with Handler.streams_lock:
                if Handler.fleet_streams.get(ident) is self.connection:
                    Handler.fleet_streams.pop(ident, None)

    def phone_stream(self, parsed):
        device = parse_qs(parsed.query).get('device', ['android'])[0]
        if device != 'android':
            return self.answer(400, {'error': 'phone_device_unknown'})
        if not self.phone.ready():
            return self.answer(503, {'error': 'phone_unavailable'})
        # Only the newest preview keeps a stream. Close older sockets so a
        # closed tab or a reload cannot exhaust the browser's per-host pool.
        with Handler.streams_lock:
            for old in list(Handler.streams):
                try:
                    old.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    old.close()
                except OSError:
                    pass
            Handler.streams.clear()
            Handler.streams.add(self.connection)
        self.connection.settimeout(10)
        self.send_response(200)
        self.send_header('Content-Type', 'multipart/x-mixed-replace; boundary=frame')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            for mime, body in self.phone.frames():
                header = ('--frame\r\nContent-Type: ' + mime + '\r\nContent-Length: ' + str(len(body)) + '\r\n\r\n').encode()
                self.wfile.write(header)
                self.wfile.write(body)
                self.wfile.write(b'\r\n')
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with Handler.streams_lock:
                Handler.streams.discard(self.connection)

    def phone_scrcpy_stream(self):
        if not self.scrcpy.available():
            return self.answer(503, {'error': 'scrcpy_unavailable'})
        with Handler.streams_lock:
            for old in list(Handler.scrcpy_streams):
                try:
                    old.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
                try:
                    old.close()
                except OSError:
                    pass
            Handler.scrcpy_streams.clear()
            Handler.scrcpy_streams.add(self.connection)
        self.connection.settimeout(12)
        self.send_response(200)
        self.send_header('Content-Type', 'application/octet-stream')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        try:
            for kind, pts, body in self.scrcpy.frames():
                header = bytes([kind]) + len(body).to_bytes(4, 'big') + int(pts & ((1 << 63) - 1)).to_bytes(8, 'big')
                self.wfile.write(header)
                self.wfile.write(body)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            with Handler.streams_lock:
                Handler.scrcpy_streams.discard(self.connection)

    def do_POST(self):
        if not self.trusted():return self.answer(403,{'error':'untrusted_origin'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        route=urlparse(self.path).path
        if route=='/v1/host-worker' and not hmac.compare_digest(self.headers.get('Authorization',''),'Bearer '+self.secret):
            return self.answer(401,{'error':'native_worker_bearer_required'})
        allowed={'/a2a','/v1/invoke','/v1/connections/save','/v1/connections/sync','/v1/connections/test-feishu','/v1/connections/ticket','/v1/platforms/configure','/v1/models/configure','/v1/models/test','/v1/models/enabled','/v1/models/accounts','/v1/models/login','/phone/control','/phone/input','/phone/settings','/phone/fleet/control','/phone/fleet/input'}
        allowed.update(('/v1/host-worker','/v1/media/providers/configure','/v1/media/plugins/configure','/v1/extensions/credentials'))
        allowed.add('/v1/connections/activate')
        if route not in allowed:return self.answer(404,{'error':'not_found'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.answer(415,{'error':'json_required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            # Shipping CSV tools validate a 500 KB UTF-8 document themselves.
            # Allow JSON escaping overhead only for their authenticated intake.
            limit=1572864 if route=='/v1/invoke' else 262144 if route=='/v1/media/providers/configure' else 131072
            if not 0<size<=limit:return self.answer(413,{'error':'request_too_large'})
            data=json.loads(self.rfile.read(size))
            if not isinstance(data,dict):return self.answer(400,{'error':'invalid_request'})
            if route=='/v1/invoke' and size>131072 and data.get('tool') not in ('commerce_shipping_rates_preview','commerce_shipping_rates_import','commerce_shipping_input_preview','commerce_shipping_plan_create','commerce_shipping_compare'):
                return self.answer(413,{'error':'request_too_large'})
            if route=='/a2a':return self.answer(200,a2a_dispatch(self.service,data))
            if route=='/v1/invoke':result=with_workspace_link(data['tool'],self.service.invoke(data['tool'],data.get('arguments',{}),data.get('client','local')),PORT)
            elif route=='/v1/host-worker':result=self.service.host_execution.broker(data.get('operation'),data.get('arguments'))
            elif route=='/v1/connections/save':result=self.service.ozon_accounts.configure(data)
            elif route=='/v1/connections/activate':result=self.service.ozon_accounts.activate(**data)
            elif route=='/v1/connections/sync':result=self.service.live.start_sync()
            elif route=='/v1/connections/test-feishu':result=self.service.live.test_feishu()
            elif route=='/v1/platforms/configure':result=self.service.platforms.configure(data)
            elif route=='/v1/models/configure':result=self.service.models.configure(data)
            elif route=='/v1/media/providers/configure':result=self.service.media_providers.configure(data)
            elif route=='/v1/media/plugins/configure':result=self.service.media_plugins.configure(data)
            elif route=='/v1/extensions/credentials':result=self.service.extensions.configure_credentials(data)
            elif route=='/v1/models/accounts':
                from model_accounts import status
                result=status(self.service.models)
            elif route=='/v1/models/login':
                from model_accounts import login
                result=login(self.service.models,**data)
            elif route=='/v1/models/test':result=self.service.models.test(**data)
            elif route=='/v1/models/enabled':result=self.service.models.set_enabled(**data)
            elif route=='/phone/control':result=self.phone.control(data)
            elif route=='/phone/input':result=self.phone.input(data)
            elif route=='/phone/settings':result=self.phone.settings(data)
            elif route=='/phone/fleet/control':result=self.fleet.control(data)
            elif route=='/phone/fleet/input':result=self.fleet.input(data)
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
    Handler.phone=PhoneBridge()
    Handler.fleet=PhoneFleet()
    Handler.scrcpy=ScrcpyBridge(Handler.phone)
    server=CommerceHTTPServer(('127.0.0.1',PORT),Handler)
    Handler.service.operations.start_timer()
    Handler.service.live.start_timer()
    Handler.service.articles.recover()
    Handler.service.article_batches.recover()
    Handler.service.collections.start(recover=True)
    Handler.service.autonomy.start(recover=True)
    Handler.service.agent_runtime.start(recover=True)
    (STATE/'runtime.json').write_text(json.dumps({'origin':f'http://127.0.0.1:{PORT}','pid':__import__('os').getpid(),'version':'0.1.0'}))
    def shutdown_signal(signum,frame):raise SystemExit(0)
    signal.signal(signal.SIGTERM,shutdown_signal)
    try:server.serve_forever()
    finally:
        Handler.service.ozon_search_terms.close()
        Handler.service.article_batches.stop()
        Handler.service.listing_schema.stop()
        Handler.service.catalog_sync.stop()
        Handler.service.listing_submissions.stop()
        Handler.service.listing_releases.stop()
        Handler.service.listing_actions.stop()
        Handler.service.platforms.stop()
        Handler.service.collections.stop()
        Handler.service.agent_runtime.stop()
        Handler.service.autonomy.stop()
        Handler.fleet.stop()
        Handler.phone.stop()
        Handler.scrcpy.stop()
        server.server_close()
