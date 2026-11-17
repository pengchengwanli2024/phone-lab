"""Public page reads with pinned DNS/TLS; no cookies or browser execution."""
import http.client
import ipaddress
import json
import socket
import ssl
import time
from collections import deque
from urllib.parse import urlsplit, urljoin
from public_media_dns import resolve_public_ipv4


def json_excerpt(data):
    body=json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False)
    if len(body)<=3200:return body,False
    # Breadth first keeps top-level coordinates and summary fields ahead of long
    # nested product histories. Paths and values are data, never executable code.
    rows=['JSON 数据摘录（较深层或过长内容已限量；路径采用 JSON Pointer）：']
    queue=deque([('',data)]);visited=0;length=len(rows[0])
    while queue and visited<400:
        pointer,value=queue.popleft();visited+=1
        if isinstance(value,(dict,list)):
            entries=value.items()if isinstance(value,dict)else enumerate(value)
            for key,child in entries:
                if len(queue)+visited>=400:break
                escaped=str(key).replace('~','~0').replace('/','~1')
                queue.append((pointer+'/'+escaped,child))
            continue
        if isinstance(value,str)and len(value)>640:continue
        row=json.dumps(pointer,ensure_ascii=False)+': '+json.dumps(value,ensure_ascii=False,allow_nan=False)
        if len(row)>700 or length+len(row)+1>3200:continue
        rows.append(row);length+=len(row)+1
    return '\n'.join(rows),True


class PublicConnection(http.client.HTTPSConnection):
    def __init__(self,host,address):
        super().__init__(host,443,timeout=8,context=ssl.create_default_context());self.address=address
    def connect(self):
        sock=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception:sock.close();raise


def addresses(host):
    try:values=list(dict.fromkeys(r[4][0]for r in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
    except OSError:raise ValueError('web_dns_unavailable')from None
    if values and all(ipaddress.ip_address(a).is_global for a in values):return values
    # Recover proxy fake-DNS using the existing verified public resolver. The
    # synthetic addresses are never contacted and mixed/private answers fail.
    fake=ipaddress.ip_network('198.18.0.0/15')
    if values and all(ipaddress.ip_address(a)in fake for a in values):
        return resolve_public_ipv4(host,PublicConnection,'web')
    raise ValueError('web_private_address_rejected')


def fetch_page(url,cancelled,url_validator=None):
    from public_web import public_url, parse_page, check_cancelled
    current=public_url(url);deadline=time.monotonic()+20
    for _ in range(4):
        check_cancelled(cancelled)
        if time.monotonic()>deadline:raise ValueError('web_page_timeout')
        # Scope is checked before DNS/connection on every redirect, not after IO.
        if url_validator is not None:url_validator(current)
        p=urlsplit(current)
        if p.scheme!='https':raise ValueError('web_https_required')
        connection=PublicConnection(p.hostname,addresses(p.hostname)[0])
        try:
            connection.request('GET',(p.path or '/')+('?' + p.query if p.query else ''),headers={
                'Accept':'text/html,application/xhtml+xml,text/plain,application/json,application/geo+json','User-Agent':'phone-lab-public-research/1.0'})
            response=connection.getresponse()
            if response.status in (301,302,303,307,308):
                current=public_url(urljoin(current,response.getheader('Location')or''));continue
            if response.status!=200:raise ValueError('web_http_'+str(response.status))
            size=response.getheader('Content-Length')
            if size and(not size.isdigit()or int(size)>2_000_000):raise ValueError('web_page_too_large')
            content_type=response.getheader('Content-Type')or''
            media_type=content_type.split(';',1)[0].strip().lower()
            is_json=media_type=='application/json'or(media_type.startswith('application/')and media_type.endswith('+json'))
            if not is_json and media_type not in ('text/html','application/xhtml+xml','text/plain'):
                raise ValueError('web_page_format_unsupported')
            chunks=[];total=0
            while True:
                check_cancelled(cancelled)
                if time.monotonic()>deadline:raise ValueError('web_page_timeout')
                chunk=response.read1(min(65536,2_000_001-total))
                if not chunk:break
                total+=len(chunk)
                if total>2_000_000:raise ValueError('web_page_too_large')
                chunks.append(chunk)
            raw=b''.join(chunks);encoding=response.headers.get_content_charset()or'utf-8'
            try:html=raw.decode(encoding,errors='replace')
            except LookupError:raise ValueError('web_page_encoding_unsupported')from None
            if is_json:
                try:
                    def reject_constant(value):raise ValueError('non_finite_json')
                    data=json.loads(html,parse_constant=reject_constant)
                    if not isinstance(data,(dict,list)):raise ValueError('json_document_required')
                    body,truncated=json_excerpt(data)
                except (ValueError,RecursionError):raise ValueError('web_page_invalid_json')from None
                from public_data_facts import official_facts
                facts=official_facts(current,data)
                return {'url':current,'title':p.hostname+' · JSON 数据','text':body,
                        **({'structured_facts':facts}if facts is not None else{}),
                        'published_at':None,'content_status':'json_data','text_truncated':truncated}
            return parse_page(html,current)
        except (OSError,ssl.SSLError,http.client.HTTPException):raise ValueError('web_page_unavailable')from None
        finally:connection.close()
    raise ValueError('web_redirect_limit')
