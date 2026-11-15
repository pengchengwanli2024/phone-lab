"""Synthetic video output boundary for real browser/HTTP review acceptance."""
from pathlib import Path
import os
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import media_outputs
import fixture_extensible_runtime as fixture

original_request=media_outputs.request


def output_request(config,method,url,**kwargs):
    if method=='GET' and url.startswith('https://synthetic-video.heygen.example/'):
        deadline=time.monotonic()+15
        while not (fixture.server.STATE/'allow-video-download').exists():
            if time.monotonic()>deadline:raise ValueError('synthetic_download_gate_closed')
            time.sleep(.03)
        return (fixture.server.STATE/'reviewed-synthetic-video.mp4').read_bytes()
    return original_request(config,method,url,**kwargs)


if __name__=='__main__':
    if not os.environ.get('COMMERCE_STATE'):raise SystemExit('Isolated COMMERCE_STATE required')
    fixture.server.STATE.mkdir(mode=0o700,parents=True,exist_ok=True)
    subprocess.run(['ffmpeg','-nostdin','-v','error','-y','-f','lavfi','-i','color=blue:size=96x96:rate=2','-t','30',
        '-c:v','libx264','-pix_fmt','yuv420p',str(fixture.server.STATE/'reviewed-synthetic-video.mp4')],check=True,capture_output=True,timeout=15)
    media_outputs.request=output_request
    fixture.main()
