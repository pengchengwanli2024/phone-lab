# -*- coding: utf-8 -*-
"""将独立桌面入口与后端装入指定 Hermes home，不修改其它配置档案。"""
import argparse
import json
from pathlib import Path
import shutil


def install(home, project):
    """只复制本插件文件，连接文件不含服务密钥；现有业务服务不重启。"""
    source = Path(__file__).resolve().parent
    home, project = Path(home).expanduser().resolve(), Path(project).expanduser().resolve()
    if not (home / "config.yaml").is_file() or not (project / "commerce/server.py").is_file():
        raise ValueError("请指定已有 Hermes home 和项目根目录")
    backend = home / "plugins/commerce-workbench"
    desktop = home / "desktop-plugins/commerce-workbench"
    if (backend.exists() and backend.is_symlink()) or (desktop.exists() and desktop.is_symlink()):
        raise ValueError("目标是符号链接，请人工核对归属")
    for relative in ("plugin.yaml", "__init__.py", "dashboard/manifest.json", "dashboard/plugin_api.py"):
        target = backend / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / relative, target)
    config = backend / "connection.json"
    config.write_text(json.dumps({"project_root":str(project),"port":38731},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    config.chmod(0o600)
    desktop.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source / "desktop/plugin.js", desktop / "plugin.js")
    return {"status":"installed","plugin":"commerce-workbench","backend_enable_required":True,"service_restarted":False}


def main():
    """显式指定安装范围，避免意外写入其它 profile。"""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hermes-home",required=True)
    parser.add_argument("--project-root",required=True)
    args=parser.parse_args()
    print(json.dumps(install(args.hermes_home,args.project_root),ensure_ascii=False))

if __name__ == "__main__": main()
