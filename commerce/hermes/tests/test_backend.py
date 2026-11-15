# -*- coding: utf-8 -*-
"""Hermes 工作台适配器的输入、安全与真实页面约束测试。"""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "dashboard/plugin_api.py"

class BackendTests(unittest.TestCase):
    """仅使用隔离配置和合成响应，不修改日常业务数据。"""
    @classmethod
    def setUpClass(cls):
        """按文件加载独立适配器。"""
        spec = importlib.util.spec_from_file_location("commerce_hermes_backend", SOURCE)
        cls.backend = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.backend)

    def test_only_commerce_tools_are_accepted(self):
        """拒绝命令执行、路径和其它插件工具。"""
        for name in ("terminal", "commerce_../x", "commerce_status\n", "commerce_", "mcp__commerce__commerce_status"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.backend.validate_call({"tool": name, "arguments": {}})
        self.assertEqual(self.backend.validate_call({"tool": "commerce_status", "arguments": {}})["client"], "hermes")
        self.backend.validate_call({"tool": "commerce_a2ui_get", "arguments": {}})

    def test_arguments_must_be_an_object(self):
        """不隐式接受数组、空值或调用端身份。"""
        for args in (None, [], "", True):
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.backend.validate_call({"tool": "commerce_status", "arguments": args})
        with self.assertRaises(ValueError):
            self.backend.validate_call({"tool":"commerce_status", "arguments":{}, "client":"other"})

    def test_size_limit(self):
        """大请求在发送到共享服务前拒绝。"""
        with self.assertRaises(ValueError):
            self.backend.validate_call({"tool":"commerce_status", "arguments":{"x":"x" * 131072}})

    def test_connection_is_loopback_only(self):
        """配置不允许远端 URL 或任意请求路径。"""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / "commerce").mkdir(); state = root / ".commerce-state"; state.mkdir()
            (state / "auth.token").write_text("synthetic-test-token", encoding="utf-8")
            config = root / "connection.json"
            config.write_text(json.dumps({"project_root":str(root),"port":38731}), encoding="utf-8")
            with patch.object(self.backend, "CONFIG_FILE", config):
                self.assertEqual(self.backend.connection()[0], "http://127.0.0.1:38731")
                config.write_text(json.dumps({"project_root":str(root),"port":True}), encoding="utf-8")
                with self.assertRaises(ValueError): self.backend.connection()
                config.write_text(json.dumps({"project_root":str(root),"port":38731,"url":"https://example.com"}), encoding="utf-8")
                with self.assertRaises(ValueError): self.backend.connection()

    def test_page_uses_auth_header_not_cookie_or_url(self):
        """固定回环请求携带后端鉴权，不把令牌写进 HTML。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        with patch.object(self.backend,"local_request",return_value=b"<!doctype html><title>test</title>") as call:
            response=TestClient(app).get("/workspace")
            self.assertEqual(response.status_code,200)
            self.assertIn("html",response.json())
            self.assertEqual(call.call_args.args,("GET","/workspace"))
            self.assertEqual(response.headers["cache-control"],"no-store")

    def test_invoke_forwarded_once(self):
        """写请求不重试，并固定调用端标签。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        with patch.object(self.backend,"local_request",return_value=b'{"ok":true}') as call:
            response=TestClient(app).post("/invoke",json={"tool":"commerce_status","arguments":{}})
            self.assertEqual(response.json(),{"ok":True})
            self.assertEqual(call.call_count,1)
            self.assertEqual(call.call_args.args[2]["client"],"hermes")

    def test_confirmed_business_errors_are_preserved(self):
        """确定性版本冲突和权限拒绝不得误报为结果未知。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        for status, code in ((409, "workspace_source_changed"), (403, "permission_denied"), (400, "invalid_client")):
            with self.subTest(code=code), patch.object(self.backend,"local_request",side_effect=self.backend.LocalFailure(status,code)):
                response=TestClient(app).post("/invoke",json={"tool":"commerce_status","arguments":{}})
                self.assertEqual(response.status_code,200)
                self.assertEqual(response.json(),{"__commerceBridgeError":code})

    def test_transport_failure_is_not_a_confirmed_rejection(self):
        """连接异常与业务拒绝保持不同的协议结果。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        with patch.object(self.backend,"local_request",side_effect=TimeoutError("synthetic-private-timeout")):
            response=TestClient(app).post("/invoke",json={"tool":"commerce_status","arguments":{}})
            self.assertEqual(response.status_code,503)
            self.assertNotIn("__commerceBridgeError",response.json())
            self.assertNotIn("synthetic-private",response.text)

    def test_bad_invoke_never_reaches_service(self):
        """不合规调用不触达业务后台。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        with patch.object(self.backend,"local_request") as call:
            self.assertEqual(TestClient(app).post("/invoke",json={"tool":"terminal","arguments":{}}).status_code,400)
            call.assert_not_called()

    def test_errors_do_not_echo_private_details(self):
        """异常不把本机路径、请求体或凭据回显前端。"""
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        app=FastAPI(); app.include_router(self.backend.router)
        with patch.object(self.backend,"local_request",side_effect=OSError("synthetic-secret-and-private-path")):
            response=TestClient(app).get("/workspace")
            self.assertEqual(response.status_code,503)
            self.assertNotIn("synthetic-secret",response.text)

if __name__ == "__main__": unittest.main()
