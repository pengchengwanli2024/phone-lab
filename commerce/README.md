# AI 跨境运营工作台

面向 DeepSeek Harness、Codex、Hermes 与浏览器的本机工作台。React 界面、HTTP 和 MCP 复用同一 Python 业务核心、对象、来源版本及任务账本。

当前为单机原型。账号接入、工具可用、任务入队、经营执行与消息送达分别核对；具体能力和未完成项见 [需求台账](../docs/PLATFORM_BACKLOG.md)。尚无独立多用户或多租户账号体系。

## 运行

Python 3.11 或更新版本；本地进程锁依赖 Unix 接口，Windows 未验证。浏览器使用已打包资源，构建界面另需 Node.js。

```sh
python3 commerce/manage.py open
```

该命令启动本项目服务，并通过单次本机票据打开工作台。默认地址为 `127.0.0.1:38731`；随机凭据、数据库、连接设置和日志保存在被忽略的 `.commerce-state/`。不要公开这些文件或带认证信息的链接。

```sh
python3 commerce/manage.py doctor
python3 commerce/manage.py backup
```

店铺连接通过工作台“能力库 → 接入与知识”的私有向导配置。保存字段、授权范围确认、读取成功和消息送达不是同一状态；没有授权时不使用示例结果代替真实数据。

## MCP 与宿主

从项目根目录运行对应 stdio 服务：

```sh
python3 commerce/mcp_server.py codex
python3 commerce/mcp_server.py hermes
python3 commerce/mcp_server.py harness
```

`python3 commerce/prepare.py` 生成本机专用连接定义，不修改客户端设置；生成文件包含本机路径，属于私有配置。Harness 本地安装与恢复方法见 [安装说明](SOURCE-INTEGRATION.md)。宿主自己的聊天与导航仍由宿主管理；MCP 返回结构化数据不代表宿主原生富组件已验收。

## 工作路径

- 从已有商品继续，保持工作项、来源、币种和原任务身份。
- 核对研究与报价资料，区分来源陈述、事实、判断和待补项。
- 在同一商品中填写成本；空白为未知，明确零值为零，不自动换汇。
- 编辑商品内容，核对字段和引用版本，再记录本地审阅或交接。
- 在任务记录核对真实状态和回执；未知结果不自动重发。

“智能助手”用于读取当前范围、追问和提出可审阅建议。补充问题使用同一输入框，Enter 换行，⌘ / Ctrl + Enter 明确发送；中文输入法确认选词不提交。示例资料范围与外观在设置中调整；切换资料范围会重新加载专业页，应先保存编辑。

情报提供公开来源检索、分页、筛选、查看、收藏、关注主题和影响核查入口。来源新鲜不等于内容已独立核实，也不代表店铺或运输路线已受影响。

消息渠道复用现有客户端适配，提供飞书、企业微信、微信与钉钉的接入类型选择和只读诊断。选择记录不包含凭据，不自动启动网关；专用客户端未配置共享 MCP、账号未授权或送达未核对时保持明确状态。微信须先选择账号类型，尚未适配的类型不给出虚假成功入口。

## 构建与检查

```sh
npm ci --prefix commerce/workbench
npm --prefix commerce/workbench run check
npm --prefix commerce/workbench test
python3 commerce/ui/build.py
python3 commerce/ui/build.py --check
node --test commerce/qa/intel_search_unit.mjs
```

共享组件源为 `ui/kit.js`、`ui/primitives.css` 和 `ui/tokens.json`。不要手改 `web/app.js`、`web/style.css` 中的生成区块。标准成本接口可独立使用；动态 Surface 的可选校验依赖见 `a2ui/requirements.txt`，采集依赖见 `../crawlers/requirements.lock`。缺依赖时保留明确的失败或标准入口，不制造成功状态。

设计与业务范围见 [体验合同](../docs/PLATFORM_EXPERIENCE.md)、[需求主稿](../docs/PLATFORM_REQUIREMENTS.md)。第三方许可与固定来源见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。运行数据、实际截图、私有回执及设备状态不随源码发布。

合成后端回归可运行 `python3 -m unittest discover -s commerce/qa -p 'test_*.py'`。SeaLeap 原始仓库是可选本机依赖，不随本仓库分发；未提供快照时依赖原文件的测试明确跳过，目录存在但完整性不符时失败。安装及版本边界见 [sealeap/README.md](sealeap/README.md)。真实模型、媒体工具及宿主条件另行检查，跳过不表示通过。
