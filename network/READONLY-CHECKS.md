# 只读网络检查工具

`check_network.py` 用于保留一次有界的网络测量。它不启动手机应用、不点击界面、不切节点、不更新订阅、不更改设置；仍会产生少量公开站点请求。不能用它代替 TikTok 播放、搜索和评论验收。

## 使用

从项目目录运行，只检测电脑：

```sh
python3 network/check_network.py --rounds 3
```

同时检测明确指定的安卓手机，并保存本地结果：

```sh
adb devices
python3 network/check_network.py --android-serial '<目标设备标识>' --rounds 3 --interval 5 --output network/check-results/new-check.json
```

不会自动选择任何安卓设备。`--no-host` 可以仅检查指定安卓；`--android-proxy-port` 默认 7890，应与手机已有监听端口一致。端口未开启时会记录失败，不自动启动代理。

默认测量 3 轮，每轮结束间隔 5 秒，单次请求总超时 8 秒，最多并行 4 个请求。参数有上限，工具不会长期后台运行。输出文件已存在时拒绝覆盖；生成的文件权限为 0600。

## 测量路径

| 路径 | 含义 |
| --- | --- |
| `host_no_explicit_proxy` | 电脑 curl 不使用显式代理或代理环境变量；仍可能受系统 VPN/TUN 影响，不能称为严格直连 |
| `host_system_loopback_proxy` | 读取 macOS 已启用的 HTTPS 回环代理，经该代理发请求；没有可识别的回环配置时不测这条路径 |
| `android_device_routing` | 安卓 curl 不使用显式 HTTP 代理，经设备原有网络路由；Clash TUN 仍可能接管 |
| `android_explicit_loopback_proxy` | 明确经安卓原有回环 HTTP 代理发请求；不代表使用不同节点，也不改变配置 |

固定目标为通用 HTTP 204 联网检测、TikTok 公开 robots.txt、一个 TikTok API 域名的根路径。不会请求账号接口、访问订阅地址、读取 cookie 或获取私有业务数据。curl 使用 `-q` 忽略用户 curlrc，并保留 TLS 证书验证；请求正文丢弃，响应大小有上限，不跟随重定向。

## 如何解读

- `transport_ok` 表示该次请求退出正常、完成可验证的 HTTPS 连接，并收到 HTTP 响应。
- 仅有 curl 的证书返回码为 0 不足以说明证书通过：未完成 TLS 时，`tls_certificate_verified` 保持未知，避免在 DNS 失败时误报证书已验证。
- `http_expected` 对通用检测要求 204，对 robots.txt 要求 200；API 根路径不规定响应码，因此其 404 不会直接算作网络失败。
- HTTP 403 等响应会与 DNS、连接、超时、证书等传输失败分开记录。它不自动证明某一国家被限制或账号异常。
- `timing_seconds` 的 `dns_end`、`connect_end`、`tls_end` 都是自请求开始累计的秒数，`total` 是总时间。显式代理可能在代理端解析目标域名，本地 DNS 时间很短不代表目标 DNS 一定很快。[curl write-out 文档](https://curl.se/docs/manpage.html)
- 安卓状态仅提取 Wi-Fi/VPN 是否连接、系统联网验证、信号强度和 Clash 省电豁免；读取失败或格式不支持时为 `null`，不会当作已断开。
- 三轮没有观察到失败，只说明这段时间内公开目标可达。不能保证长期稳定、视频 CDN 可用或后台恢复正常；本工具不测 iPhone。
- 其他任务可能同时改变手机路由，快照和请求不是原子测量，不足以单独确定因果。

报告不保存设备标识、IP、Wi-Fi 名称、订阅链接、进程输出或错误原文。退出码 0 表示本次公开目标检查全部符合预期；1 表示观察到传输失败或非预期响应；2 表示参数或本地执行/保存问题。退出码 1 可以是真实网络测量结果，不等于工具实现出错。

## 本地验证

```sh
python3 -m unittest discover -s network -p 'test_check_network.py' -v
```

十项测试覆盖 API 根路径 404 的含义、公开网页 HTTP 拒绝与传输失败的区分、证书与超时失败、TLS 未完成时不声称证书通过、无样本与未知设备状态、原始内容过滤、设备标识不进入远程 shell 文本，以及不覆盖已有报告。

本工具仅测量公开端点，不附带私人设备的诊断记录或网络配置。
