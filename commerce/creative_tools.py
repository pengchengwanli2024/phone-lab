"""Resolve a fixed local media tool set without relying on a login-shell PATH."""
import json
import os
from pathlib import Path
import shutil

NAMES={'ffmpeg','ffprobe','rsvg-convert','whisper'}
ROOT=Path(__file__).resolve().parents[1]


def command(name):
    if name not in NAMES:raise ValueError('creative_unsupported_tool')
    state=Path(os.environ.get('COMMERCE_STATE',str(ROOT/'.commerce-state')))
    try:configured=json.loads((state/'creative-tools.json').read_text()).get(name)
    except (OSError,ValueError,TypeError):configured=None
    paths=[configured,shutil.which(name),*(str(Path(folder)/name) for folder in ['/opt/homebrew/bin','/usr/local/bin',str(Path.home()/'.local/bin'),'/usr/bin'])]
    for value in paths:
        if value and Path(value).is_absolute() and Path(value).is_file() and os.access(value,os.X_OK):return str(value)
    raise ValueError('creative_local_tool_unavailable')


def environment():
    env=os.environ.copy();folders=[]
    for name in NAMES:
        try:folders.append(str(Path(command(name)).parent))
        except ValueError:pass
    env['PATH']=os.pathsep.join(dict.fromkeys([*folders,*env.get('PATH','/usr/bin:/bin').split(os.pathsep)]))
    return env
