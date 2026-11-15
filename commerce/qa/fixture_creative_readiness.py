"""Empty synthetic product for preparation actions and real local file intake."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from fixture_product_workspace import seed
from service import Commerce
import server


def main():
    if not os.environ.get('COMMERCE_STATE'):raise SystemExit('Isolated COMMERCE_STATE required')
    app=Commerce(server.STATE);cid=seed(app);source=app.catalog.get(cid)
    p=app.catalog.creative(cid,source['source_sha256'],'synthetic-readiness-project')
    brief=p['brief'];brief['product']['verified_facts']=[]
    p=app.creative.save(p['id'],brief,p['revision'])
    image=server.STATE/'synthetic-readiness-image.png'
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=96x96','-frames:v','1','-update','1',str(image)],check=True,capture_output=True,timeout=15)
    (server.STATE/'readiness-fixture.json').write_text(json.dumps({'synthetic':True,'project_id':p['id'],'case_id':cid,'image_path':str(image)}))
    server.Handler.secret=server.token();server.Handler.service=app
    http=server.CommerceHTTPServer(('127.0.0.1',server.PORT),server.Handler)
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(SystemExit(0)))
    print(json.dumps({'synthetic':True,'port':server.PORT}),flush=True)
    try:http.serve_forever()
    finally:app.autonomy.stop();app.agent_runtime.stop();http.server_close()


if __name__=='__main__':main()
