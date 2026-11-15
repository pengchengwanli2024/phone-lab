# -*- coding: utf-8 -*-
"""只读检查已安装代理连接同一个后台；不导航桌面或创建业务记录。"""
import hashlib
import importlib.util
import json
from pathlib import Path
from fastapi import FastAPI
from fastapi.testclient import TestClient


def main():
    """只输出状态、大小与哈希，绝不输出页面、业务正文或认证信息。"""
    home = Path.home() / ".hermes"
    source = home / "plugins/commerce-workbench/dashboard/plugin_api.py"
    spec = importlib.util.spec_from_file_location("installed_commerce_workbench", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = FastAPI(); app.include_router(module.router)
    client = TestClient(app)
    page = client.get("/workspace")
    assert page.status_code == 200, "installed_workspace_unavailable"
    html = page.json()["html"]
    assert "__COMMERCE_BRIDGE_NONCE__" in html, "existing_bridge_missing"
    assert "commerce:call" in html and "commerce:copilot-draft" in html, "existing_protocol_missing"
    origin, secret = module.connection()
    assert secret not in html, "credential_in_html"
    status = client.post("/invoke", json={"tool":"commerce_status", "arguments":{}})
    assert status.status_code == 200, "installed_invoke_unavailable"
    result = status.json()
    assert result.get("version") == "0.1.0" and "platforms" in result, "unexpected_backend"
    output = {"status":"passed", "scope":"installed_adapter_real_loopback_read_only_not_native_UI", "workspace_bytes":len(html.encode("utf-8")), "workspace_sha256":hashlib.sha256(html.encode("utf-8")).hexdigest(), "backend_version":result["version"], "marketplace_writes":result["marketplace_writes"], "credential_in_html":False, "native_page_open":"pending_user_click", "models_requested":False, "devices_operated":False}
    print(json.dumps(output, ensure_ascii=False))

import unittest


class InstalledAdapterTests(unittest.TestCase):
    """显式运行时才接触日常后台的只读检查。"""
    def test_installed_read_only(self):
        """验证已安装文件与真实共享服务，而非合成响应。"""
        main()


if __name__ == "__main__": unittest.main()
