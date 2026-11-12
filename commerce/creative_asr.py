"""Cached local Whisper transcription. Never downloads models while processing."""
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
from creative_tools import command, environment

MODELS=Path(__file__).resolve().parents[1]/'.local/creative-asr/models'


def available():
    try:
        manifest=json.loads((MODELS/'manifest.json').read_text())
        model=MODELS/'tiny.pt'
        return bool(command('whisper') and model.is_file() and not model.is_symlink() and manifest.get('model')=='tiny' and hashlib.sha256(model.read_bytes()).hexdigest()==manifest.get('sha256'))
    except (OSError,ValueError,TypeError):return False


def transcribe(wav, output, duration):
    if not available():raise ValueError('creative_asr_cached_model_unavailable')
    output=Path(output);output.mkdir(mode=0o700,parents=True,exist_ok=True)
    argv=[command('whisper'),str(wav),'--model','tiny','--model_dir',str(MODELS),'--device','cpu','--fp16','False','--threads','2','--temperature','0','--word_timestamps','True','--output_format','json','--output_dir',str(output),'--verbose','False']
    try:done=subprocess.run(argv,capture_output=True,timeout=100,env=environment())
    except subprocess.TimeoutExpired:raise ValueError('creative_asr_processing_timeout') from None
    path=output/(Path(wav).stem+'.json')
    if done.returncode or not path.is_file() or path.stat().st_size>2*1024*1024:raise ValueError('creative_asr_failed')
    try:data=json.loads(path.read_text())
    except (ValueError,UnicodeError):raise ValueError('creative_asr_invalid_output') from None
    text=data.get('text','')
    if not isinstance(text,str) or len(text)>12000:raise ValueError('creative_asr_invalid_output')
    segments=[]
    for s in data.get('segments',[]):
        start,end=s.get('start'),s.get('end')
        if not all(isinstance(v,(int,float)) and math.isfinite(v) for v in [start,end]) or not 0<=start<=end<=duration+2:continue
        words=[]
        for w in s.get('words',[]):
            if all(isinstance(w.get(k),(int,float)) and math.isfinite(w[k]) for k in ['start','end']) and isinstance(w.get('word'),str):
                words.append({k:w[k] for k in ['word','start','end']})
        segments.append(dict(start_seconds=start,end_seconds=end,text=str(s.get('text',''))[:2000],words=words))
    return dict(text=text,language=data.get('language','unknown'),segments=segments,source='local_whisper_tiny',review_status='machine_generated_pending_review',independently_verified=False)
