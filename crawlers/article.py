"""Bounded publisher-body extraction through two independent HTTP clients."""
import argparse
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import Request, HTTPRedirectHandler, build_opener, HTTPSHandler
import ssl

from setup import STATE, environment

PUBLISHERS = {
    'fed': ('www.federalreserve.gov', '/newsevents/', ['#article', '#content']),
    'ecb': ('www.ecb.europa.eu', '/press/', ['main', '#main-wrapper']),
    'eia': ('www.eia.gov', '/todayinenergy/', ['#content', 'main']),
    'wto': ('www.wto.org', '/english/', ['#news', '#main-content', '#main']),
    'hmrc': ('www.gov.uk', '/government/', ['.gem-c-govspeak', 'main']),
    'transport': ('www.gov.uk', '/government/', ['.gem-c-govspeak', 'main']),
}
MAX_BYTES = 2_000_000
MAX_TEXT = 30000


def allowed(source, url, resolve=True):
    if source not in PUBLISHERS:raise ValueError('article_source_not_supported')
    host, prefix, _ = PUBLISHERS[source]
    p=urlsplit(url)
    if p.scheme!='https' or p.netloc!=host or not p.path.startswith(prefix) or p.username or p.password or p.fragment:
        raise ValueError('article_url_rejected')
    # Existing loopback HTTP proxy resolves remote names itself. Keep TLS hostname
    # verification and the fixed host/path redirect guard; never invent local DNS.
    proxy=urlsplit(environment().get('HTTPS_PROXY') or environment().get('https_proxy') or '')
    proxy_dns=proxy.scheme in ('http','https') and proxy.hostname in ('127.0.0.1','localhost','::1')
    if resolve and not proxy_dns:
        for entry in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM):
            if not ipaddress.ip_address(entry[4][0]).is_global:raise ValueError('article_address_rejected')
    return url


class PublisherRedirect(HTTPRedirectHandler):
    def __init__(self, source):self.source=source
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        allowed(self.source,newurl)
        return super().redirect_request(req,fp,code,msg,headers,newurl)


def body(source, payload):
    from parsel import Selector
    selector=Selector(text=payload.decode('utf-8'))
    for css in PUBLISHERS[source][2]:
        nodes=selector.css(css)
        if not nodes:continue
        parts=[]
        for node in nodes:
            for element in node.root.xpath('.//script|.//style|.//nav|.//footer|.//header|.//form|.//aside'):
                parent=element.getparent()
                if parent is not None:parent.remove(element)
            paragraphs=node.xpath('.//h1|.//h2|.//h3|.//p|.//li')
            parts.extend(' '.join(' '.join(p.xpath('.//text()').getall()).split()) for p in paragraphs)
        text='\n'.join(part for part in parts if part)
        if len(text)>MAX_TEXT:raise ValueError('article_text_too_large')
        if len(text)>=100:return text, css
    raise ValueError('article_body_unavailable')


def capture(source,url):
    allowed(source,url)
    from rate_limit import wait_for,outcome
    import time
    deadline=time.monotonic()+40
    wait_for(url,deadline)
    import truststore
    context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    opener=build_opener(HTTPSHandler(context=context),PublisherRedirect(source))
    with opener.open(Request(url,headers={'User-Agent':'phone-lab-public-article/0.1'}),timeout=12) as response:
        if response.status!=200:raise ValueError('article_http_failed')
        first=response.read(MAX_BYTES+1)
    if len(first)>MAX_BYTES:raise ValueError('article_payload_too_large')
    (STATE/'cache').mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='article-',dir=STATE/'cache') as folder:
        target=Path(folder)/'body.html'
        wait_for(url,deadline)
        # No follow-redirect switch: curl cannot redirect into a private service.
        done=subprocess.run(['curl','--silent','--fail','--proto','=https','--max-time','15',
                             '--max-filesize',str(MAX_BYTES),'--output',str(target),'--write-out','%{http_code}',url],
                            env=environment(),capture_output=True,timeout=18)
        if done.returncode or done.stdout!=b'200':
            outcome(url,done.stdout in (b'429',b'503'))
            raise ValueError('article_native_http_failed')
        second=target.read_bytes()
    if len(second)>MAX_BYTES:raise ValueError('article_payload_too_large')
    texts=[body(source,payload) for payload in [first,second]]
    if texts[0][0]!=texts[1][0]:raise ValueError('article_route_conflict')
    stamp=datetime.now(timezone.utc).isoformat()
    return {'text':texts[0][0],'content_sha256':hashlib.sha256(texts[0][0].encode()).hexdigest(),
            'source_url':url,'captured_at':stamp,'routes':['urllib','native-curl'],
            'evidence':[{'route':route,'source_url':url,'captured_at':stamp,'locator':locator,
                         'payload_sha256':hashlib.sha256(payload).hexdigest()}
                        for route,payload,(_,locator) in zip(['urllib','native-curl'],[first,second],texts)],
            'coverage':'selected_publisher_body_no_attachments','publisher_claims_independently_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',required=True);parser.add_argument('--url',required=True)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    try:
        result=capture(args.source,args.url);args.output.write_text(json.dumps(result,ensure_ascii=False));args.output.chmod(0o600)
        print(json.dumps({'status':'captured','characters':len(result['text'])}))
    except Exception as error:
        code=str(error) if isinstance(error,ValueError) and str(error).startswith('article_') else 'article_capture_failed'
        print(json.dumps({'error':code}));sys.exit(1)
