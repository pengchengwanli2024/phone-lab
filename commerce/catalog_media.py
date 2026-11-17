"""Bounded public HTTPS image reads, with DNS pinning and no ambient credentials."""
import base64
import hashlib
import http.client
import ipaddress
from pathlib import Path
import re
import socket
import ssl
import threading
from urllib.parse import urlsplit
from product_catalog import public_url,source_reference
from public_media_dns import resolve_public_ipv4
from research import canonical,digest

_slots=threading.BoundedSemaphore(3)
MAX_IMAGE=5*1024*1024


class PublicImageConnection(http.client.HTTPSConnection):
    def __init__(self,host,address):
        super().__init__(host,443,timeout=8,context=ssl.create_default_context());self.address=address
    def connect(self):
        sock=socket.create_connection((self.address,443),self.timeout)
        try:self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception:sock.close();raise


def doh_addresses(host):
    """Resolve only the vendor CDN fallback over verified TLS to a fixed resolver.

    Some local proxy DNS routes return RFC 2544 fake IPs. Those IPs are never
    contacted: the image request still pins a globally routable address and
    verifies the original hostname. No ambient proxy/auth configuration is used.
    """
    return resolve_public_ipv4(host,PublicImageConnection,'catalog_image')


def image_addresses(host,*,lovart_artifact=False):
    try:addresses=list(dict.fromkeys(r[4][0]for r in socket.getaddrinfo(host,443,type=socket.SOCK_STREAM)))
    except OSError:raise ValueError('catalog_image_unavailable')from None
    if addresses and all(ipaddress.ip_address(a).is_global for a in addresses):return addresses
    # General URLs stay closed; Lovart is limited by fetch to generated files.
    fake=ipaddress.ip_network('198.18.0.0/15')
    vendor=host.endswith(('.ozonstatic.cn','.ozonstatic.ru'))or(lovart_artifact and host=='a.lovart.ai')
    if addresses and vendor and all(ipaddress.ip_address(a)in fake for a in addresses):
        return doh_addresses(host)
    raise ValueError('catalog_image_address_rejected')


def fetch(url):
    if not public_url(url):raise ValueError('catalog_image_url_rejected')
    p=urlsplit(url)
    artifact=(p.hostname=='a.lovart.ai'and p.port in (None,443)and not(p.username or p.password or p.query or p.fragment)
              and re.fullmatch(r'/artifacts/generator/[A-Za-z0-9_-]+\.(?:png|jpe?g)',p.path)is not None)
    addresses=image_addresses(p.hostname,lovart_artifact=artifact)
    c=PublicImageConnection(p.hostname,addresses[0])
    try:
        c.request('GET',p.path+('?' + p.query if p.query else ''),headers={'Accept':'image/png,image/jpeg','User-Agent':'commerce-product-preview/1.0'})
        response=c.getresponse()
        if response.status!=200:raise ValueError('catalog_image_http_error')
        size=response.getheader('Content-Length')
        if size and (not size.isdigit() or int(size)>MAX_IMAGE):raise ValueError('catalog_image_too_large')
        raw=response.read(MAX_IMAGE+1)
        if len(raw)>MAX_IMAGE:raise ValueError('catalog_image_too_large')
        if not (raw.startswith(b'\x89PNG\r\n\x1a\n') or raw.startswith(b'\xff\xd8\xff')):raise ValueError('catalog_image_format_unsupported')
        return raw
    except (OSError,ssl.SSLError,http.client.HTTPException):raise ValueError('catalog_image_unavailable') from None
    finally:c.close()


def evidence_bytes(service,ref):
    """Read the exact current, case-bound original; never fall back to a URL."""
    if ref.get('id')!=digest(canonical({k:v for k,v in ref.items() if k!='id'})):
        raise ValueError('catalog_evidence_reference_changed')
    if (ref.get('role')!='original' or ref.get('source_kind') not in ('competitor','supplier')
            or type(ref.get('image_index')) is not int or ref['image_index']<0
            or ref.get('reference_only') is not True or ref.get('product_fact') is not False):
        raise ValueError('catalog_evidence_reference_changed')
    media=service.product_evidence.media
    source=media.source(ref['case_id'],ref['entry_id'],ref['entry_sha256'])
    if source['archived'] or source['kind']!=ref['source_kind'] or source['revision']!=ref['entry_revision']:
        raise ValueError('catalog_evidence_reference_changed')
    if ref['image_index']>=len(source['images']):raise ValueError('catalog_evidence_reference_changed')
    image=source['images'][ref['image_index']]
    if (image['role']!='original' or image['media_id']!=ref['media_id']
            or public_url(source_reference(image['url']))!=ref.get('url')):
        raise ValueError('catalog_evidence_reference_changed')
    path,doc=media.asset(ref['case_id'],ref['entry_id'],ref['media_id'])
    if (doc['role']!='original' or doc['source_url']!=image['url'] or doc['sha256']!=ref['sha256']
            or ref.get('raw_sha256')!=doc['sha256'] or doc['size']!=ref.get('size')
            or any(doc.get('media',{}).get(k)!=ref.get(k) for k in ('width','height'))):
        raise ValueError('catalog_evidence_reference_changed')
    raw=path.read_bytes()
    if len(raw)!=doc['size'] or hashlib.sha256(raw).hexdigest()!=doc['sha256']:raise ValueError('evidence_image_changed')
    # A source revision can change while the file is read. Never return bytes
    # under a reference whose exact source head has already changed.
    media.source(ref['case_id'],ref['entry_id'],ref['entry_sha256'])
    return raw


def preview(service,ref,source):
    if not _slots.acquire(blocking=False):raise ValueError('catalog_image_busy')
    try:
        if ref.get('origin')=='product_evidence':
            raw=evidence_bytes(service,ref)
        elif ref.get('asset_id'):
            path,meta,_=service.creative.asset(ref['project_id'],ref['asset_id'])
            raw=path.read_bytes()
            if hashlib.sha256(raw).hexdigest()!=meta['sha256']:raise ValueError('creative_asset_changed')
        else:
            root=service.state/'catalog-images';root.mkdir(mode=0o700,exist_ok=True)
            key=hashlib.sha256((source+ref['url']).encode()).hexdigest();path=root/(key+'.image')
            if not path.is_file():
                if len(list(root.iterdir()))>=512 or sum(f.stat().st_size for f in root.iterdir() if f.is_file())>512*1024*1024:raise ValueError('catalog_image_cache_full')
                raw=fetch(ref['url'])
                # Atomic cache publication; all inputs remain in private state.
                import uuid
                temp=root/(uuid.uuid4().hex+'.part');temp.write_bytes(raw);temp.chmod(0o600);temp.replace(path)
            if path.is_symlink():raise ValueError('catalog_image_unavailable')
            raw=path.read_bytes()
            media=service.creative.probe(path)
            if media['width']<=0:raise ValueError('catalog_image_format_unsupported')
        if len(raw)>MAX_IMAGE:raise ValueError('catalog_image_too_large')
        mime=('image/png' if raw.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if raw.startswith(b'\xff\xd8\xff')
              else 'image/webp' if raw.startswith(b'RIFF') and raw[8:12]==b'WEBP' else None)
        if not mime:raise ValueError('catalog_image_format_unsupported')
        result={'content_base64':base64.b64encode(raw).decode(),'mime':mime,'sha256':hashlib.sha256(raw).hexdigest(),'source_ref':source_reference(ref.get('source_ref')),'independently_verified':False}
        if ref.get('origin')=='product_evidence':
            result.update(reference_only=True,source_kind=ref['source_kind'],product_fact=False,
                publication_approved=False,use_for_image_generation=False,width=ref['width'],height=ref['height'])
        return result
    finally:_slots.release()
