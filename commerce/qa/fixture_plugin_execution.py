"""Isolated host-receipt fixture: only the output GET boundary is synthetic."""
import json
import time
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import media_outputs
import fixture_extensible_runtime as fixture

original_request=media_outputs.request


def output_request(config,method,url,**kwargs):
    if method=='GET' and url.startswith('https://synthetic-results.lovart.ai/'):
        deadline=time.monotonic()+15
        while not (fixture.server.STATE/'allow-plugin-download').exists():
            if time.monotonic()>deadline:raise ValueError('synthetic_download_gate_closed')
            time.sleep(.03)
        marker=json.loads((fixture.server.STATE/'extensible-fixture.json').read_text())
        path,_,_=fixture.server.Handler.service.creative.asset(marker['project_id'],marker['asset_id'])
        return path.read_bytes()
    return original_request(config,method,url,**kwargs)


if __name__=='__main__':
    media_outputs.request=output_request
    fixture.main()
