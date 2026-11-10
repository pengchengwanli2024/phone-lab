#!/usr/bin/env python3
"""Bounded public-endpoint checks; never launch apps or change device settings."""

import argparse
import concurrent.futures
import datetime as dt
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from zoneinfo import ZoneInfo


TARGETS = (
    ("baseline", "https://www.gstatic.com/generate_204", 204),
    ("tiktok_public_web", "https://www.tiktok.com/robots.txt", 200),
    ("tiktok_api_transport_only", "https://api16-normal-c-useast1a.tiktokv.com/", None),
)
MARKER = "PHONE_LAB_METRICS:"
FIELDS = ("http_code", "time_namelookup", "time_connect", "time_appconnect", "time_total", "ssl_verify_result")
WRITE_OUT = MARKER + ";".join("%{" + field + "}" for field in FIELDS)
PROXY_ENV = {"http_proxy", "https_proxy", "all_proxy", "no_proxy"}
ERROR_KINDS = {5: "proxy_dns", 6: "dns", 7: "connect", 28: "timeout", 35: "tls_handshake", 51: "certificate", 60: "certificate", 55: "send", 56: "receive", 63: "response_size_limit"}


def timestamp():
    return dt.datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def clean_env():
    return {k: v for k, v in os.environ.items() if k.lower() not in PROXY_ENV}


def run(argv, timeout):
    """Do not expose commands, environment, stderr or device output in reports."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=clean_env())
        return p.returncode, p.stdout, None
    except subprocess.TimeoutExpired:
        return None, "", "runner_timeout"
    except OSError:
        return None, "", "runner_unavailable"


def curl_args(url, proxy, timeout):
    # -q must be first: ignore curlrc, which could otherwise add cookies or writes.
    args = ["-q", "--silent", "--show-error", "--output", "/dev/null", "--proto", "=https",
            "--connect-timeout", str(min(4, timeout)), "--max-time", str(timeout),
            "--max-filesize", "262144", "--proxy", proxy or "", "--noproxy", "" if proxy else "*",
            "--write-out", WRITE_OUT, url]
    return args


def parse_result(code, stdout, runner_error, expected_http):
    result = {"exit_code": code, "transport_ok": False, "http_expected": None,
              "http_code": None, "error": runner_error}
    if MARKER not in stdout:
        result["error"] = runner_error or "metrics_unavailable"
        return result
    try:
        values = stdout.rsplit(MARKER, 1)[1].strip().split(";")
        if len(values) != len(FIELDS):
            raise ValueError
        metrics = dict(zip(FIELDS, values))
        status = int(metrics["http_code"])
        timings = {field: float(metrics[field]) for field in FIELDS[1:5]}
        if not all(math.isfinite(v) and v >= 0 for v in timings.values()):
            raise ValueError
        verified = int(metrics["ssl_verify_result"]) == 0
        tls_completed = timings["time_appconnect"] > 0
        # curl's default verification code is also zero when TLS never started.
        certificate_result = verified if tls_completed or not verified else None
        result.update(http_code=status, tls_certificate_verified=certificate_result,
                      timing_seconds={"dns_end": timings["time_namelookup"],
                                      "connect_end": timings["time_connect"],
                                      "tls_end": timings["time_appconnect"],
                                      "total": timings["time_total"]})
        result["transport_ok"] = code == 0 and 100 <= status <= 599 and verified and tls_completed
        if expected_http is not None:
            result["http_expected"] = result["transport_ok"] and status == expected_http
        if code != 0:
            result["error"] = runner_error or ERROR_KINDS.get(code, "curl_or_device_error")
        elif not result["transport_ok"]:
            result["error"] = "https_not_verified"
        elif expected_http is not None and status != expected_http:
            result["error"] = "unexpected_http_status"
    except (ValueError, OverflowError):
        result["error"] = "invalid_metrics"
    return result


def probe(route, target, args):
    name, url, expected = target
    route_name, device, proxy = route
    command = curl_args(url, proxy, args.timeout)
    if device:
        # Serial stays in the argument array and is never interpolated into shell text.
        argv = [args.adb, "-s", args.android_serial, "shell", shlex.join(["curl", *command])]
    else:
        argv = [args.curl, *command]
    code, stdout, error = run(argv, args.timeout + 5)
    return {"route": route_name, "target": name, **parse_result(code, stdout, error, expected)}


def host_proxy():
    code, text, _ = run(["scutil", "--proxy"], 4)
    if code != 0:
        return None
    fields = dict(re.findall(r"^\s*(HTTPSEnable|HTTPSProxy|HTTPSPort)\s*:\s*(\S+)\s*$", text, re.M))
    host = fields.get("HTTPSProxy")
    if fields.get("HTTPSEnable") != "1" or host not in ("127.0.0.1", "localhost", "::1"):
        return None
    try:
        port = int(fields["HTTPSPort"])
        if not 1 <= port <= 65535:
            return None
    except (KeyError, ValueError):
        return None
    return "http://" + ("[::1]" if host == "::1" else host) + ":" + str(port)


def parse_device_state(connectivity, wifi, whitelist):
    state = {"wifi_connected": None, "wifi_validated": None, "vpn_connected": None,
             "wifi_rssi_dbm": None, "clash_power_exempt": None}
    if connectivity is not None:
        agents = [line for line in connectivity.splitlines() if "NetworkAgentInfo{" in line]
        if agents:
            wifi_agents = [line for line in agents if "type: WIFI[" in line]
            state["wifi_connected"] = any("state: CONNECTED/CONNECTED" in line for line in wifi_agents)
            state["wifi_validated"] = any("state: CONNECTED/CONNECTED" in line and "&VALIDATED" in line for line in wifi_agents)
            state["vpn_connected"] = any("type: VPN[" in line and "state: CONNECTED/CONNECTED" in line for line in agents)
    if wifi is not None:
        match = re.search(r"RSSI:\s*(-?\d+)", wifi)
        if match and -127 <= int(match[1]) <= 0:
            state["wifi_rssi_dbm"] = int(match[1])
    if whitelist is not None:
        state["clash_power_exempt"] = "com.github.metacubex.clash.meta" in whitelist
    return state


def device_state(args):
    def read(*command):
        code, output, _ = run([args.adb, "-s", args.android_serial, "shell", *command], 6)
        if code != 0 or not output.strip() or "Permission Denial" in output:
            return None
        return output
    return parse_device_state(read("dumpsys", "connectivity"), read("dumpsys", "wifi"), read("dumpsys", "deviceidle", "whitelist"))


def summarize(samples):
    routes = {}
    for sample in samples:
        entry = routes.setdefault(sample["route"], {"requests": 0, "transport_failures": 0, "unexpected_http": 0, "max_total_seconds": None})
        entry["requests"] += 1
        entry["transport_failures"] += int(not sample["transport_ok"])
        entry["unexpected_http"] += int(sample["transport_ok"] and sample["http_expected"] is False)
        total = sample.get("timing_seconds", {}).get("total")
        if total is not None:
            entry["max_total_seconds"] = max(entry["max_total_seconds"] or 0, total)
    transport_failed = any(r["transport_failures"] for r in routes.values())
    unexpected_http = any(r["unexpected_http"] for r in routes.values())
    if not samples:
        status = "not_measured"
    elif transport_failed:
        status = "transport_failure_observed"
    elif unexpected_http:
        status = "http_response_unexpected"
    else:
        status = "public_endpoints_reachable"
    return {"status": status, "application_acceptance": "not_tested", "routes": routes}


def int_range(low, high):
    def parse(value):
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("需要整数") from None
        if not low <= number <= high:
            raise argparse.ArgumentTypeError(f"范围为 {low}–{high}")
        return number
    return parse


def arguments(argv=None):
    parser = argparse.ArgumentParser(description="只读网络检查：固定公开目标，不操作手机界面或设置。")
    parser.add_argument("--android-serial", help="明确选择目标安卓；不填写时只检查电脑，不自动选择其他设备")
    parser.add_argument("--adb", default=shutil.which("adb") or "/opt/homebrew/share/android-commandlinetools/platform-tools/adb")
    parser.add_argument("--curl", default=shutil.which("curl") or "curl")
    parser.add_argument("--android-proxy-port", type=int_range(1, 65535), default=7890)
    parser.add_argument("--rounds", type=int_range(1, 10), default=3)
    parser.add_argument("--interval", type=int_range(0, 60), default=5, help="每轮结束后的间隔秒数")
    parser.add_argument("--timeout", type=int_range(3, 30), default=8, help="单次请求总超时秒数")
    parser.add_argument("--no-host", action="store_true", help="只检查显式指定的安卓")
    parser.add_argument("--output", type=Path, help="保存脱敏 JSON；已存在的文件不会覆盖")
    args = parser.parse_args(argv)
    if args.no_host and not args.android_serial:
        parser.error("--no-host 需要 --android-serial")
    if args.android_serial and (args.android_serial.startswith("-") or re.search(r"[\s\x00-\x1f]", args.android_serial)):
        parser.error("安卓设备标识格式无效")
    if args.output and args.output.exists():
        parser.error("输出文件已存在，请使用新文件名")
    return args


def save_report(path, report):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w") as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main(argv=None):
    args = arguments(argv)
    routes = []
    proxy = None
    if not args.no_host:
        routes.append(("host_no_explicit_proxy", False, None))
        proxy = host_proxy()
        if proxy:
            routes.append(("host_system_loopback_proxy", False, proxy))
    if args.android_serial:
        routes.extend((("android_device_routing", True, None),
                       ("android_explicit_loopback_proxy", True, f"http://127.0.0.1:{args.android_proxy_port}")))
    report = {"schema": "phone-lab-network-v1", "started_at": timestamp(),
              "scope": "read_only_public_endpoints", "host_loopback_proxy_detected": bool(proxy),
              "rounds": args.rounds, "timeout_seconds": args.timeout, "interval_seconds": args.interval,
              "limitations": ["Does not test TikTok feed, search, comments, account region or subscription health.",
                              "No explicit proxy does not bypass a system VPN or TUN.",
                              "API root HTTP errors can still demonstrate HTTPS reachability.",
                              "Timing fields are cumulative elapsed times, not separate stage durations.",
                              "Other device users can change routing during measurements; snapshots are not causal proof.",
                              "Unknown device-state fields remain null; iPhone is not measured by this tool."],
              "device_snapshots": [], "samples": []}
    for round_number in range(1, args.rounds + 1):
        print(f"只读检查 {round_number}/{args.rounds}", file=sys.stderr, flush=True)
        if args.android_serial:
            report["device_snapshots"].append({"round": round_number, "at": timestamp(), **device_state(args)})
        jobs = [(route, target) for route in routes for target in TARGETS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(probe, route, target, args) for route, target in jobs]
            for future in futures:
                report["samples"].append({"round": round_number, **future.result()})
        if round_number < args.rounds:
            time.sleep(args.interval)
    report["finished_at"] = timestamp()
    report["summary"] = summarize(report["samples"])
    if args.output:
        save_report(args.output, report)
        print(json.dumps(report["summary"], ensure_ascii=False))
    else:
        print(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False))
    return 0 if report["summary"]["status"] == "public_endpoints_reachable" else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("检查已停止；未修改手机设置。", file=sys.stderr)
        sys.exit(130)
    except OSError:
        print("无法保存报告或执行本地工具；未输出底层路径或错误原文。", file=sys.stderr)
        sys.exit(2)
