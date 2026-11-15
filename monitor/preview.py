#!/usr/bin/env python3
"""Loopback-only, read-only phone preview; badges stay outside captured pixels."""
import argparse
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import urllib.parse
import urllib.request

from control import STATE

PAGE = """<!doctype html><html lang="zh-CN"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>手机观察</title>
<style>
:root{color-scheme:dark;font-family:system-ui,sans-serif;background:#14171b;color:#ecf0f3}
*{box-sizing:border-box}body{margin:0;padding:22px 28px}header{display:flex;align-items:baseline;gap:18px}
h1{font-size:20px;font-weight:600;margin:0}header p{font-size:12px;color:#a4acb6;margin:0}
main{display:flex;gap:32px;justify-content:center;margin-top:18px}section{min-width:0;width:min(39vw,400px)}
.bar{height:32px;display:flex;align-items:center;justify-content:space-between;font-size:13px}
.badge{font-size:11px;color:#a4acb6;display:flex;align-items:center;gap:6px}
.badge:before{content:'';width:5px;height:5px;border-radius:50%;background:#8a929d}
.badge.active:before{background:#72d4a2}.badge.active{color:#b6e9cd}.badge.error:before{background:#e5b66c}
.screen{background:#090b0d;border:1px solid #30363e;border-radius:16px;overflow:hidden;min-height:200px}
img{display:block;width:100%;height:auto;max-height:calc(100vh - 160px);object-fit:contain}footer{margin-top:18px;color:#a4acb6;font-size:12px;line-height:1.7}
@media(max-width:650px){body{padding:16px}main{gap:12px}section{width:48%}header{display:block}header p{margin-top:8px}.bar{height:48px;display:block}.badge{margin-top:4px}}
</style>
<header><h1>手机观察</h1><p>状态放在画面外 · 原始截图不叠字 · 本机预览</p></header>
<main><section><div class="bar"><span>vivo · Android</span><span id="android-status" class="badge">连接中</span></div><div class="screen"><img id="android" alt="Android 实时截图"></div></section>
<section><div class="bar"><span>iPhone · iOS</span><span id="ios-status" class="badge">连接中</span></div><div class="screen"><img id="ios" alt="iPhone 实时截图"></div></section></main>
<footer>绿色小点“本任务控制中”仅代表通过本提示工具执行的操作；没有控制心跳时显示“只读预览”。<br>Android 本机使用静音状态栏图标。iPhone 走 WDA；不可用时退回 devicectl 只读截图，不启动 XCTest。</footer>
<script>
let busy=false;async function update(){if(busy)return;busy=true;try{const r=await fetch('/state',{cache:'no-store'});if(!r.ok)throw Error();const data=await r.json();for(const device of ['android','ios']){const s=data[device],b=document.getElementById(device+'-status');b.textContent=s.error?'画面暂不可用':s.stale?'画面延迟':s.active?'本任务控制中':'只读预览';b.className='badge '+(s.error||s.stale?'error':s.active?'active':'');if(s.frame&&!s.stale)document.getElementById(device).src='/frame/'+device+'?t='+s.frame;}}catch(e){for(const d of ['android','ios']){const b=document.getElementById(d+'-status');b.textContent='预览连接中断';b.className='badge error';}}finally{busy=false}}update();setInterval(update,2000);
</script></html>"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--minutes", type=int, default=30)
    parser.add_argument("--ios-udid", default="", help="iPhone UDID for the read-only devicectl fallback")
    args = parser.parse_args()
    if not 1 <= args.minutes <= 120:
        parser.error("minutes must be between 1 and 120")
    config = json.loads(args.config.read_text())
    serial = config["android_serial"]
    base = str(config.get("wda_url") or "").rstrip("/")
    if base:
        url = urllib.parse.urlsplit(base)
        # Configuration may refer only to a private/loopback device endpoint.
        if url.scheme != "http" or url.username or url.password or not ipaddress.ip_address(url.hostname).is_private:
            parser.error("wda_url must be an HTTP private/loopback IP without credentials")
    ios_udid = args.ios_udid or str(config.get("ios_udid") or "")
    xcrun = "/opt/homebrew/bin/xcrun" if Path("/opt/homebrew/bin/xcrun").is_file() else (shutil.which("xcrun") or "xcrun")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    cache = {d: {"image": None, "frame": 0, "error": True} for d in ("android", "ios")}
    lock = threading.Lock()
    stop = threading.Event()

    def capture(device):
        while not stop.is_set():
            try:
                if device == "android":
                    result = subprocess.run(["adb", "-s", serial, "exec-out", "screencap", "-p"],
                                            capture_output=True, timeout=10)
                    image = result.stdout if result.returncode == 0 else b""
                else:
                    image = b""
                    if base:
                        try:
                            with opener.open(base + "/screenshot", timeout=2.5) as r:
                                value = json.load(r)["value"]
                            image = base64.b64decode(value.get("screen") if isinstance(value, dict) else value)
                        except Exception:
                            image = b""
                    if not image and ios_udid:
                        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
                            target = Path(tmp.name)
                        try:
                            done = subprocess.run(
                                [xcrun, "devicectl", "device", "capture", "screenshot",
                                 "--device", ios_udid, "--destination", str(target)],
                                capture_output=True, timeout=25,
                            )
                            if done.returncode == 0:
                                image = target.read_bytes()
                        finally:
                            try:
                                target.unlink()
                            except OSError:
                                pass
                if not image.startswith(b"\x89PNG\r\n\x1a\n"):
                    raise ValueError("Invalid image")
                with lock:
                    cache[device] = {"image": image, "frame": time.time(), "error": False}
            except Exception:
                with lock:
                    cache[device]["error"] = True
            stop.wait(3)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            allowed = {f"127.0.0.1:{args.port}", f"localhost:{args.port}"}
            if self.headers.get("Host") not in allowed:
                self.send_error(403)
                return
            origin = self.headers.get("Origin")
            if origin and origin not in {"http://" + h for h in allowed}:
                self.send_error(403)
                return
            path = urllib.parse.urlsplit(self.path).path
            if path == "/":
                body, mime = PAGE.encode(), "text/html; charset=utf-8"
            elif path == "/state":
                values = {}
                for d in cache:
                    try:
                        lease = json.loads((STATE / (d + ".json")).read_text())
                    except (OSError, ValueError):
                        lease = {}
                    with lock:
                        c = cache[d].copy()
                    values[d] = {"active": bool(lease.get("active") and lease.get("expires", 0) > time.time()),
                                 "frame": c["frame"], "error": c["error"],
                                 "stale": time.time() - c["frame"] > 15}
                body, mime = json.dumps(values).encode(), "application/json"
            elif path in ("/frame/android", "/frame/ios"):
                with lock:
                    body = cache[path.rsplit("/", 1)[1]]["image"]
                if body is None:
                    self.send_error(503)
                    return
                mime = "image/png"
            else:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    for d in cache:
        threading.Thread(target=capture, args=(d,), daemon=True).start()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    timer = threading.Timer(args.minutes * 60, server.shutdown)
    timer.daemon = True
    timer.start()
    print(f"Preview: http://127.0.0.1:{args.port} (read-only, {args.minutes} minutes)", flush=True)
    try:
        server.serve_forever()
    finally:
        stop.set()
        timer.cancel()
        server.server_close()


if __name__ == "__main__":
    main()