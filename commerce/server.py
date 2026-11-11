from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse,parse_qs
import hashlib
import hmac
import json
import fcntl
import secrets
from runtime import ROOT,STATE,PORT,token
from service import Commerce


def page():
    html=(ROOT/'web/index.html').read_text()
    return html.replace('/* INLINE_STYLE */',(ROOT/'web/style.css').read_text()).replace('/* INLINE_APP */',(ROOT/'web/app.js').read_text())


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
        if parsed.path=='/login':
            value=parse_qs(parsed.query).get('token',[''])[0]
            if not hmac.compare_digest(value,self.secret):return self.answer(401,{'error':'authentication_required'})
            return self.answer(303,'',headers={'Location':'/','Set-Cookie':'commerce_session='+self.secret+'; HttpOnly; SameSite=Strict; Path=/'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        if parsed.path=='/':return self.answer(200,page(),'text/html; charset=utf-8',{'Content-Security-Policy':"default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'self'"})
        return self.answer(404,{'error':'not_found'})
    def do_POST(self):
        if not self.trusted():return self.answer(403,{'error':'untrusted_origin'})
        if not self.authenticated():return self.answer(401,{'error':'authentication_required'})
        if urlparse(self.path).path!='/v1/invoke':return self.answer(404,{'error':'not_found'})
        if self.headers.get('Content-Type','').split(';')[0]!='application/json':return self.answer(415,{'error':'json_required'})
        try:
            size=int(self.headers.get('Content-Length','0'))
            if not 0<size<=131072:return self.answer(413,{'error':'request_too_large'})
            data=json.loads(self.rfile.read(size));result=self.service.invoke(data['tool'],data.get('arguments',{}),data.get('client','local'))
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
    Handler.service.articles.recover()
    Handler.service.collections.start(recover=True)
    server=CommerceHTTPServer(('127.0.0.1',PORT),Handler)
    (STATE/'runtime.json').write_text(json.dumps({'origin':f'http://127.0.0.1:{PORT}','pid':__import__('os').getpid(),'version':'0.1.0'}))
    try:server.serve_forever()
    finally:
        Handler.service.collections.stop()
        server.server_close()
