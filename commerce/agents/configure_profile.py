"""Run using the installed Hermes bootstrap; modify only the new project profile."""
from pathlib import Path
import json
import shutil
import os
import sys
import yaml

ROOT=Path(__file__).resolve().parents[1]
PROFILE=Path(os.environ.get('COMMERCE_HERMES_PROFILE',str(Path.home()/'.hermes/profiles/commerce-bot'))).expanduser()
assert PROFILE.is_dir(),'Create the dedicated commerce-bot profile first.'
p=PROFILE/'config.yaml'
backup=PROFILE/'config.before-commerce.yaml'
if not backup.exists():shutil.copyfile(p,backup);backup.chmod(0o600)
config=yaml.safe_load(p.read_text())
config.setdefault('mcp_servers',{})['commerce']={'command':sys.executable,'args':[str(ROOT/'mcp_server.py'),'hermes'],'connect_timeout':20,'enabled':True}
config['toolsets']=['mcp-commerce','clarify']
config.setdefault('platform_toolsets',{}).update({'cli':['mcp-commerce','clarify'],'feishu':['mcp-commerce','clarify']})
config.setdefault('terminal',{})['cwd']=str(ROOT.parent)
config['group_sessions_per_user']=True
config['timezone']='Asia/Shanghai'
config.setdefault('platforms',{}).setdefault('feishu',{}).setdefault('enabled',False)
p.write_text(yaml.safe_dump(config,allow_unicode=True,sort_keys=False));p.chmod(0o600)
shutil.copyfile(ROOT/'agents/SOUL.md',PROFILE/'SOUL.md')
(PROFILE/'SOUL.md').chmod(0o600)
result={'profile':'commerce-bot','status':'configured_gateway_not_started','tools':['mcp-commerce','clarify'],'channel':'feishu_pending_setup','existing_channels_copied':False,'model_settings_changed':False}
report=Path(os.environ.get('COMMERCE_STATE',str(ROOT.parent/'.commerce-state')))/'verification/agents'
report.mkdir(parents=True,exist_ok=True,mode=0o700)
(report/'profile-setup.json').write_text(json.dumps(result,indent=2));(report/'profile-setup.json').chmod(0o600);print(json.dumps(result))
