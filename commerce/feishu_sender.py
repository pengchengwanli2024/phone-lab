"""One attempt per outbox claim. Ambiguous delivery is never automatically retried."""
import base64
import hashlib
import hmac
import json
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse
from ozon_reader import NoRedirect


def validate_webhook(value):
    if not isinstance(value,str): raise ValueError('invalid_feishu_webhook')
    parsed=urlparse(value)
    if parsed.scheme!='https' or parsed.hostname!='open.feishu.cn' or parsed.port not in (None,443) or parsed.username or parsed.password or parsed.query or parsed.fragment or not parsed.path.startswith('/open-apis/bot/v2/hook/') or len(parsed.path.rsplit('/',1)[-1])<20:
        raise ValueError('invalid_feishu_webhook')
    return value


def signed_message(text, secret, timestamp=None):
    data={'msg_type':'text','content':{'text':text}}
    if secret:
        timestamp=int(time.time()) if timestamp is None else timestamp
        key=f'{timestamp}\n{secret}'.encode()
        data.update(timestamp=str(timestamp),sign=base64.b64encode(hmac.new(key,b'',hashlib.sha256).digest()).decode())
    if len(json.dumps(data,ensure_ascii=False).encode())>19000: raise ValueError('feishu_message_too_large')
    return data


def send(webhook, signing_secret, text):
    validate_webhook(webhook)
    data=signed_message(text,signing_secret)
    request=urllib.request.Request(webhook,data=json.dumps(data,ensure_ascii=False).encode(),headers={'Content-Type':'application/json'},method='POST')
    try:
        with urllib.request.build_opener(NoRedirect()).open(request,timeout=12) as response:
            raw=response.read(65537)
            if len(raw)>65536:return {'outcome':'uncertain','code':'invalid_delivery_response'}
            parsed=json.loads(raw)
            if not isinstance(parsed,dict):return {'outcome':'uncertain','code':'invalid_delivery_response'}
            code=parsed.get('code') if 'code' in parsed else parsed.get('StatusCode')
            if type(code) is not int:return {'outcome':'uncertain','code':'missing_delivery_code'}
            return dict(outcome='confirmed' if code==0 else 'rejected',code=str(code),response_sha256=hashlib.sha256(raw).hexdigest())
    except urllib.error.HTTPError as error:
        return {'outcome':'rejected' if 400<=error.code<500 else 'uncertain','code':'feishu_http_'+str(error.code)}
    except (urllib.error.URLError,TimeoutError,OSError,json.JSONDecodeError,UnicodeError):
        return {'outcome':'uncertain','code':'feishu_delivery_unknown'}
