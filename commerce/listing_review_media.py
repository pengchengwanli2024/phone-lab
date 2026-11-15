"""Bounded, request-scoped product previews over the existing private image cache."""
import base64
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import threading
import uuid
from catalog_media import preview,MAX_IMAGE
from research import canonical,digest

def bytes_sha(value):return hashlib.sha256(value).hexdigest()

MAX_PREVIEW=192*1024
_slots=threading.BoundedSemaphore(2)

def descriptor(releases,r,index):
    urls=r['data']['frozen']['payload']['fields']['image_refs']
    if type(index)is not int or not 0<=index<len(urls):raise ValueError('listing_review_image_index')
    url=urls[index];source=digest(canonical(['listing-review-images-v1',r['sha256']]))
    root=releases.service.state/'catalog-images'
    if root.is_symlink():raise ValueError('listing_review_image_changed')
    return url,source,root/(hashlib.sha256((source+url).encode()).hexdigest()+'.image')

def _paths(releases,raw):
    root=releases.service.state/'listing-review-images'
    if root.is_symlink():raise ValueError('listing_review_image_changed')
    return root/(raw.stem+'.json'),root/(raw.stem+'.preview')
def _bytes(path,limit):
    if path.is_symlink()or not path.is_file()or not 0<path.stat().st_size<=limit:raise ValueError('listing_review_image_changed')
    return path.read_bytes()

def cached(releases,r,index):
    url,source,path=descriptor(releases,r,index);meta_path,thumb=_paths(releases,path)
    if not meta_path.exists():raise ValueError('listing_review_image_not_cached')
    try:
        meta=json.loads(_bytes(meta_path,8192));raw=_bytes(path,MAX_IMAGE);image=_bytes(thumb,MAX_PREVIEW)
        if meta['request_sha256']!=r['sha256']or meta['index']!=index or meta['url']!=url or meta['source_sha256']!=bytes_sha(raw)or meta['preview_sha256']!=bytes_sha(image):raise ValueError()
        if meta['mime']not in ('image/png','image/jpeg')or not(image.startswith(b'\x89PNG\r\n\x1a\n')if meta['mime']=='image/png'else image.startswith(b'\xff\xd8\xff')):raise ValueError()
        return dict(**meta,content_base64=base64.b64encode(image).decode(),status='ready',independently_verified=False)
    except (ValueError,KeyError,TypeError,OSError):raise ValueError('listing_review_image_changed')from None

def read(releases,r,index):
    url,source,path=descriptor(releases,r,index);meta_path,thumb=_paths(releases,path)
    if meta_path.exists():return cached(releases,r,index)
    if r['data']['synthetic']and not path.is_file():raise ValueError('listing_review_demo_no_network')
    if not _slots.acquire(False):raise ValueError('listing_review_image_busy')
    temp=None
    try:
        root=meta_path.parent;root.mkdir(mode=0o700,exist_ok=True)
        files=[p for p in root.iterdir()if p.is_file()]
        if len(files)>=2048 or sum(p.stat().st_size for p in files)>128*1024*1024:raise ValueError('listing_review_image_cache_full')
        value=preview(releases.service,dict(url=url,source_ref='application:'+r['id']),source)
        raw=base64.b64decode(value['content_base64'],validate=True);media=releases.service.creative.probe(path)
        if bytes_sha(_bytes(path,MAX_IMAGE))!=value['sha256']:raise ValueError('listing_review_image_changed')
        image=raw;mime=value['mime']
        if len(image)>MAX_PREVIEW:
            temp=path.with_name(uuid.uuid4().hex+'.jpg')
            for size,quality in ((960,5),(640,8)):
                width=max(1,int(media['width']*min(1,size/max(media['width'],media['height']))));height=max(1,int(media['height']*min(1,size/max(media['width'],media['height']))))
                releases.service.creative.run(['ffmpeg','-nostdin','-v','error','-y','-i',path,'-frames:v','1','-vf',f'scale={width}:{height}','-q:v',str(quality),'-update','1',temp],8)
                if temp.is_file()and temp.stat().st_size<=MAX_PREVIEW:break
            image=_bytes(temp,MAX_PREVIEW);mime='image/jpeg'
        meta=dict(request_sha256=r['sha256'],index=index,url=url,source_sha256=value['sha256'],preview_sha256=bytes_sha(image),mime=mime,width=media['width'],height=media['height'],captured_at=datetime.now(timezone.utc).isoformat())
        for destination,content in ((thumb,image),(meta_path,canonical(meta).encode())):
            if destination.is_symlink():raise ValueError('listing_review_image_changed')
            part=destination.with_name(uuid.uuid4().hex+'.part');part.write_bytes(content);part.chmod(0o600);part.replace(destination)
        return cached(releases,r,index)
    finally:
        if temp and temp.exists():temp.unlink()
        _slots.release()

def for_export(releases,r):
    rows=[]
    for index,url in enumerate(r['data']['frozen']['payload']['fields']['image_refs']):
        try:rows.append(cached(releases,r,index))
        except ValueError as exc:rows.append(dict(index=index,url=url,status='unavailable',error=str(exc)))
    return rows
