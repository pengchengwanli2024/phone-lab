# phone-lab

面向 DeepSeek Harness、Codex 和 Hermes 的本地手机工具与跨境电商工作台。项目以本机共享后台为核心，提供明确标注的演示数据、共享任务账本和受限业务笔记访问。

本版属于原型。五个平台的真实店铺 API、自动执行器、机器人网关和生产部署尚未完成；任务排队不表示已经执行。

## 包含什么

- `commerce/`：Python HTTP/stdio MCP 后台、Harness 原生面板和 Web 界面。包含经营概览、订单与库存演示、任务创建/取消、简报草稿、单位经济与补货计算，以及业务目录内的中英文笔记检索。
- `android/`：ADB 健康检查、输入法切换和实验设备安装脚本。
- `ios/`：Xcode/真机健康检查、devicectl 与 WebDriverAgent 客户端。
- `scrape/`：显式选择设备的界面采集实验，不附带任何采集结果。
- `network/`：公开网络端点的只读连通性检查和国家关键词搜索面板。

模拟数据仅用于演示和合成测试。默认工具读取真实模式，未授权的数据保持缺失，不替换成模拟结果。当前服务面向同一台机器的单一用户，绑定回环地址，尚无多用户或多租户权限体系。

## 运行共享后台

使用 Python 3.11 或更新版本。服务本身只使用 Python 标准库；Harness 面板需要另行安装 Node.js 和兼容的 DeepSeek Harness。进程锁使用 Unix 接口，Windows 尚未验证。

```sh
git clone https://github.com/pengchengwanli2024/phone-lab.git
cd phone-lab
python3 commerce/runtime.py
```

服务默认使用 `127.0.0.1:38731`，在被忽略的 `.commerce-state/` 内创建本机随机凭据和运行状态。请勿把运行目录复制到公开仓库或公开网络位置。

MCP 客户端采用 stdio，命令分别为：

```sh
python3 commerce/mcp_server.py codex
python3 commerce/mcp_server.py hermes
python3 commerce/mcp_server.py harness
```

在客户端配置中使用本次克隆的实际绝对路径。以下命令生成被忽略的本机连接配置与 Harness patch，不修改现有客户端设置：

```sh
python3 commerce/prepare.py
```

详细配置见 [commerce/README.md](commerce/README.md)。角色配置与后续执行层设计见 [commerce/AGENT_TEAM.md](commerce/AGENT_TEAM.md)。

## 手机工具

使用者须自行安装 ADB 或 Xcode/相关 iOS 工具，连接并授权自己的设备。真实设备标识通过命令参数或环境变量传入，源码没有预置设备。

```sh
SERIAL="$ANDROID_SERIAL" bash android/healthcheck.sh
IOS_UDID="$IPHONE_UDID" bash ios/healthcheck.sh --all
WDA_URL=http://127.0.0.1:8100 bash ios/wda.sh status
```

先在本机设置上述设备变量。健康检查可能截图、读取设备信息或发送 HOME 输入；安装、切换输入法和采集脚本会操作目标手机。具体说明见 [Android](android/README.md)、[iOS](ios/README.md)、[采集实验](scrape/README.md) 和 [网络检查](network/READONLY-CHECKS.md)。

## 验证

```sh
python3 -m unittest discover -s commerce/qa -p 'test_*.py' -v
python3 -m unittest discover -s network -p 'test_check_network.py' -v
```

这些测试使用合成数据、临时状态与模拟网络结果，不证明真实店铺、设备或生产服务已验收。`commerce/qa/browser.mjs` 是可选的 Chrome 交互检查；原生宿主检查还需要本机应用与独立配置。

开源发布范围与隐私检查见 [OPEN_SOURCE.md](OPEN_SOURCE.md)。代码使用 [MIT License](LICENSE)；适配来源及完整许可见 [第三方声明](commerce/THIRD_PARTY_NOTICES.md)。

## 桌面采集与公开信息

新增 [桌面爬虫工具与安装](crawlers/README.md)、[官方来源与业务页面](crawlers/SOURCES.md) 及 [工作台/MCP 接口和边界](crawlers/integration.md)。采集队列支持进度、取消、重试和重启恢复；公开文章与待校对中文保留各自哈希和来源证据。服务仅监听本机，未连接的店铺、未知字段和失败路线保留明确状态。

本次源码副本保留原有店铺功能范围，仅同步桌面爬虫、信息聚合及共享 UI 组件；其它并行开发模块不包含在此提交中。
