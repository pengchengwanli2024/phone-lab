"""Isolated synthetic HTTP providers and product data for browser acceptance."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
from fixture_product_workspace import seed
from creative_direction import DIRECTION_FIELDS
from service import Commerce
import server


def main():
    if not os.environ.get('COMMERCE_STATE'):raise SystemExit('Isolated COMMERCE_STATE required')
    app=Commerce(server.STATE)
    image=server.STATE/'synthetic-product.png';clip=server.STATE/'synthetic-clip.mp4'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=96x96','-frames:v','1','-update','1',str(image)],check=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=96x96:rate=24','-t','4','-c:v','libx264','-pix_fmt','yuv420p',str(clip)],check=True)
    image_bytes=image.read_bytes();receipts=[]
    class Provider(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def reply(self,value):
            raw=json.dumps(value).encode();self.send_response(200);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)
        def do_GET(self):
            if self.path.startswith('/read'):return self.reply({'synthetic':True,'value':'received local plugin result'})
            if self.path.startswith('/jobs/'):
                return self.reply({'id':'synthetic-video','status':'succeeded','outputs':[{'url':base+'/clip.mp4'}]})
            if self.path=='/clip.mp4':
                raw=clip.read_bytes();self.send_response(200);self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw);return
            self.reply({'ok':True,'data':[{'id':'synthetic-llm'}]})
        def do_POST(self):
            data=json.loads(self.rfile.read(int(self.headers.get('Content-Length','0'))));receipts.append({'path':self.path,'data':data})
            (server.STATE/'synthetic-provider-receipts.json').write_text(json.dumps(receipts))
            if self.path=='/jobs':
                if data.get('duration_seconds'):return self.reply({'id':'synthetic-video','status':'pending'})
                return self.reply({'status':'succeeded','outputs':[{'base64':base64.b64encode(image_bytes).decode()}]})
            if self.path=='/v1/chat/completions':
                probe='connectivity_test' in data['messages'][-1]['content']
                output={'ok':True} if probe else {'action':'finish','output':{'synthetic':True,'message':'Actual local HTTP model receipt'}}
                return self.reply({'model':'synthetic-llm','choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(output)}}]})
            self.reply({'ok':True})
    provider=ThreadingHTTPServer(('127.0.0.1',0),Provider);base='http://127.0.0.1:'+str(provider.server_port)
    threading.Thread(target=provider.serve_forever,daemon=True).start()
    cid=seed(app);source=app.catalog.get(cid)
    p=app.catalog.creative(cid,source['source_sha256'],'synthetic-ext-project')
    brief=p['brief'];brief['product']['verified_facts']=[{'id':'f1','text':'合成规格：容量500毫升','evidence_ref':'synthetic:spec'}]
    p=app.creative.save(p['id'],brief,p['revision'])
    product=app.creative.register(p['id'],'product_image',image,{'source_ref':'synthetic:product','display_name':'合成产品原图'})
    reference_path=server.STATE/'synthetic-reference.png';reference_path.write_bytes(image_bytes)
    reference=app.creative.register(p['id'],'reference_image',reference_path,{'source_ref':'synthetic:reference','display_name':'合成参考图'})
    p=app.media.direction_save(p['id'],p['revision'],{k:'合成参考：产品主体、特写、真实场景与清晰信息层级' for k in DIRECTION_FIELDS},[reference['id']])
    request=app.media.request_create(p['id'],p['revision'],'product_main','synthetic-image-request')
    video=app.media.request_create(p['id'],p['revision'],'ugc_video','synthetic-video-request')
    from media_providers.adapters import GENERIC
    for kind in ('image','video'):
        profile=app.media_providers.configure({'label':'合成本机'+('图片' if kind=='image' else '视频')+'服务','provider':'local','adapter':'generic_json_async','base_url':base,'model':'synthetic-'+kind,'media_kind':kind,'enabled':True,'capabilities':{'image_input':True,**({'min_duration_seconds':4,'max_duration_seconds':15} if kind=='video' else {})},'protocol':GENERIC})
        app.media_providers.test_profile(profile['id'],profile['revision'])
    model=app.models.configure({'label':'合成本机通用模型','engine':'ollama','base_url':base+'/v1','model':'synthetic-llm'})
    app.models.test(model['id'],model['revision']);app.models.set_enabled(model['id'],True,model['revision'])
    marker={'synthetic':True,'case_id':cid,'project_id':p['id'],'asset_id':product['id'],'image_request':request['id'],'video_request':video['id'],'provider_url':base,'model_id':model['id']}
    (server.STATE/'extensible-fixture.json').write_text(json.dumps(marker))
    server.Handler.secret=server.token();server.Handler.service=app
    http=server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler)
    app.autonomy.start(recover=True)
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(SystemExit(0)))
    print(json.dumps({'synthetic':True,'port':server.PORT}),flush=True)
    try:http.serve_forever()
    finally:app.autonomy.stop();provider.shutdown();provider.server_close();http.server_close()


if __name__=='__main__':main()
