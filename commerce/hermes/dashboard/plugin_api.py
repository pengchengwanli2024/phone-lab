# -*- coding: utf-8 -*-
"""Hermes 工作台受鉴权代理；凭据留在后端，仅访问固定本机服务。"""
import json
from pathlib import Path
import re
import urllib.error
import urllib.request
import webbrowser
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

router = APIRouter()
CONFIG_FILE = Path(__file__).resolve().parents[1] / "connection.json"
MAX_REQUEST_BYTES = 131072  # 与现有宿主桥保持相同请求上限
MAX_RESPONSE_BYTES = 16777216  # 单份内联界面的最大响应字节数
TOOL_PATTERN = re.compile(r"commerce_(?:[a-z_]+|a2ui_[a-z_]+)")

class LocalFailure(Exception):
    """保留可公开的错误码，不把请求体或本机异常带进前端。"""
    def __init__(self, status, code):
        """记录已过滤的后台回执。"""
        self.status, self.code = status, code

class NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止携带共享凭据跟随跳转。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """拒绝所有重定向，避免认证头离开固定回环服务。"""
        return None

def connection():
    """只从私有连接文件定位既有状态目录，不创建或替换凭据。"""
    data = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) - {"project_root", "port", "state_dir"}:
        raise ValueError("invalid_local_connection")
    root = Path(data["project_root"])
    port = data.get("port", 38731)
    if not root.is_absolute() or not (root / "commerce").is_dir() or type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid_local_connection")
    state = Path(data.get("state_dir", str(root / ".commerce-state")))
    if not state.is_absolute(): raise ValueError("invalid_local_connection")
    secret = (state / "auth.token").read_text(encoding="utf-8").strip()
    if not secret or len(secret) > 256 or any(c.isspace() for c in secret):
        raise ValueError("invalid_local_credentials")
    return f"http://127.0.0.1:{port}", secret

def validate_call(data):
    """仅允许原 commerce 命名空间与对象参数，拒绝调用端身份覆盖。"""
    if not isinstance(data, dict) or set(data) != {"tool", "arguments"}:
        raise ValueError("invalid_commerce_call")
    if not isinstance(data["tool"], str) or not TOOL_PATTERN.fullmatch(data["tool"]) or not isinstance(data["arguments"], dict):
        raise ValueError("invalid_commerce_call")
    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > MAX_REQUEST_BYTES:
        raise ValueError("request_too_large")
    return {**data, "client": "hermes"}

def local_request(method, path, data=None):
    """固定地址、禁代理、禁跳转；原后台仍执行工具权限与版本校验。"""
    allowed = {("GET", "/workspace"), ("POST", "/v1/invoke"), ("POST", "/v1/connections/ticket")}
    if (method, path) not in allowed: raise ValueError("invalid_local_route")
    origin, secret = connection()
    body = None if data is None else json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(origin + path, data=body, method=method,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + secret})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    try:
        with opener.open(req, timeout=15) as response:
            payload = response.read(MAX_RESPONSE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        code = "commerce_request_failed"
        try:
            value = json.loads(exc.read(4096)).get("error")
            if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,99}", value): code = value
        except (ValueError, AttributeError): pass
        raise LocalFailure(exc.code, code) from None
    if len(payload) > MAX_RESPONSE_BYTES: raise ValueError("commerce_response_too_large")
    if secret.encode("utf-8") in payload: raise ValueError("credential_in_response")
    return payload

def failure(exc):
    """返回可操作但不含私密上下文的错误。"""
    if isinstance(exc, LocalFailure):
        return JSONResponse({"error": exc.code}, status_code=exc.status, headers={"Cache-Control": "no-store"})
    return JSONResponse({"error": "commerce_service_unavailable"}, status_code=503, headers={"Cache-Control": "no-store"})

@router.get("/workspace")
def workspace():
    """读取已运行服务生成的同一 HTML，不执行项目代码、不复制数据。"""
    try:
        html = local_request("GET", "/workspace").decode("utf-8")
        return JSONResponse({"html": html}, headers={"Cache-Control": "no-store"})
    except Exception as exc: return failure(exc)

@router.post("/invoke")
async def invoke(request: Request):
    """有界读取请求后在线程池代理一次；任何失败均不自动重发。"""
    from starlette.concurrency import run_in_threadpool
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_REQUEST_BYTES: return JSONResponse({"error":"request_too_large"}, status_code=413)
    try:
        data = validate_call(json.loads(body))
    except (ValueError, TypeError): return JSONResponse({"error":"invalid_commerce_call"}, status_code=400)
    try:
        payload = await run_in_threadpool(local_request, "POST", "/v1/invoke", data)
        return JSONResponse(json.loads(payload), headers={"Cache-Control":"no-store"})
    except LocalFailure as exc:
        # 保留已确认的业务拒绝；传输中断仍标记结果未知且不重试。
        return JSONResponse({"__commerceBridgeError":exc.code}, headers={"Cache-Control":"no-store"})
    except Exception as exc: return failure(exc)

@router.post("/browser")
def browser():
    """仅在用户点击后打开原浏览器入口，票据不返回给前端。"""
    try:
        result = json.loads(local_request("POST", "/v1/connections/ticket", {}))
        ticket = result.get("ticket", "")
        if not isinstance(ticket, str) or not re.fullmatch(r"[A-Za-z0-9_-]{20,120}", ticket):
            raise ValueError("invalid_ticket")
        origin, _ = connection()
        if not webbrowser.open(origin + "/open?ticket=" + ticket): raise ValueError("browser_open_failed")
        return {"opened": True}
    except Exception as exc: return failure(exc)
