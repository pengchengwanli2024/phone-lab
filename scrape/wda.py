#!/usr/bin/env python3
"""Minimal WebDriverAgent client used by the phone-lab scrapers."""
import base64, json, time, urllib.request, os
BASE = os.environ.get("WDA_URL", "http://127.0.0.1:8100")

def _req(method, path, data=None, timeout=90):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(BASE+path, data=body, method=method,
                                 headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    try: return json.loads(raw)
    except Exception: return {"raw": raw[:200]}
def session():
    return _req("POST","/session",{"capabilities":{}}).get("sessionId") or \
           (_req("POST","/session",{"capabilities":{}}).get("value") or {}).get("sessionId")
def end(sid):
    try: _req("DELETE", f"/session/{sid}", timeout=15)
    except Exception: pass
def shot(path):
    d=_req("GET","/screenshot",timeout=60); v=d.get("value",d)
    if isinstance(v,dict) and "screen" in v: v=v["screen"]
    open(path,"wb").write(base64.b64decode(v)); return path
def source():
    return _req("GET","/source?format=json",timeout=90).get("value")
def tap(x,y):
    s=session()
    try: return _req("POST",f"/session/{s}/wda/tap",{"x":int(x),"y":int(y)},timeout=90)
    finally: end(s)
def swipe(x1,y1,x2,y2,dur=0.3):
    s=session()
    try: return _req("POST",f"/session/{s}/wda/dragfromtoforduration",
                     {"fromX":x1,"fromY":y1,"toX":x2,"toY":y2,"duration":dur},timeout=90)
    finally: end(s)
def keys(text):
    s=session()
    try: return _req("POST",f"/session/{s}/wda/keys",{"value":[text]},timeout=90)
    finally: end(s)
def launch(bundle):
    s=session()
    try: return _req("POST",f"/session/{s}/wda/apps/launch",{"bundleId":bundle},timeout=90)
    finally: end(s)
def walk(node, out, depth=0):
    if not isinstance(node, dict): return
    out.append({"type":node.get("type"),"name":node.get("name") or node.get("label") or "",
                "value":node.get("value") or "","rect":node.get("rect") or {},"depth":depth})
    for c in node.get("children") or []: walk(c,out,depth+1)
