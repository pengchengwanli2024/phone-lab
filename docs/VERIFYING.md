# 本地一键验证

完整模式强制执行隔离 HTTP/Chromium 经营控制台收件、刷新、390深色和演示隔离验收。经营控制集成后，完整模式追加经营路径/视频策略、共享预算、手机本地核心及实际服务校验、自动经营控制投影与收件专项。它仍不包含真实手机投递、真实金融交易、仓库作业或全仓全部后端套件。

在项目根目录运行：

```sh
make verify-fast
make verify
```

两个入口都实际执行必需依赖检查、Python/JavaScript 语法、生成产物同步、TypeScript 类型、现有 npm 单测、合成 Python 测试和无头浏览器交互。任何必需项缺依赖、失败、超时、Python 测试跳过、交互回执缺失或源码在运行中变化，入口都返回非零。没有自动安装、自动修复、构建写回、模型付费或共享服务重启。

`verify-fast` 使用四个 Python 模块；`verify` 追加商品证据、跨模块交付、HTTP/MCP 测试。两者均运行当版共享 Web 交互回归。完整入口的“通过”仅指下表范围，不代表整个产品、全部 Python 测试或原生宿主已验收。

| 检查 | fast | verify |
| --- | --- | --- |
| 锁定 Python/npm 依赖、Playwright/浏览器可用性 | 必需 | 必需 |
| 验证器专项测试、Commerce/所需爬虫导入/验证器语法检查 | 必需 | 必需 |
| `commerce/ui/build.py --check`，只检查不构建写回 | 必需 | 必需 |
| `npm run check` / `npm test`，在 workbench 副本执行 | 全部现有脚本 | 全部现有脚本 |
| Python 模块 | `test_a2ui_cost`、`test_product_workspace`、`test_listing_workspace`、`test_full_flow` | 左侧加 `scripts/verify.py` 的 `FULL_MODULES` 明确列出的证据、经营预算、移动协议、多店铺、素材、资讯、搜索词、引用及研究原子保存/真实 stdio 合同等；运行回执保存实际列表 |
| `modern_web_regression.mjs` 实际 HTTP/浏览器 | 必需：模块跳转、商品草稿保留、窄屏、输入法、弹窗键盘/opaque iframe 桥接等 | 同左 |
| `operating_control_ui.mjs` | 不运行 | 必需：原任务读写、预算模式隔离、多账户切换、凭据不回显及店铺绑定 |
| `catalog_library_ui.mjs` | 不运行 | 必需：库存视图合并与跨店隔离、可读原字段、商品卡下载、原素材分片/SHA下载、篡改拒绝及宽窄屏 |
| `product_research_ui.mjs` | 不运行 | 必需：原文/中文/人工校对保存与刷新读回、来源/研究头冲突留稿、稀疏 HOLD、缺项定位可见焦点，以及保存处理中/未知结果的模式切换保护与原请求恢复 |

Python 单测通过现有临时状态 fixture 验证计算、保存后重读、版本冲突、商品/店铺隔离和交付限制；完整模式另经 HTTP 和实际 MCP stdio 子进程验证跨客户端合同。浏览器使用真实共享页面与桥接，保留原驱动明确标记的独立模块模拟检查；模型提供者由原 QA fixture 替换为模拟实现。截图仅作诊断附件；必须有成功交互断言、完成标记和匹配候选源码的 JSON 回执。Node 测试必须有非空的成功汇总，skipped/cancelled/todo 也会导致失败。

完整模式另运行 `test_operating_loop`：经营回路的授权默认停用、按证据版本去重、重启与重复事件不重复派发、未知结果阻断、撤销与过期、每日上限、连续失败停用，以及批准沿用原审阅路径。模型为模拟实现，不证明真实模型质量或任何外部经营动作。

完整模式另运行 `test_agent_text_fence`、`test_trigger_failure_spacing` 与 `test_trigger_failure_spacing_seam`：前者检查不可信 agent 文本的归一、不可见字符去除、凭据屏蔽、行首标记折叠与“只改提示副本”约束（明示不做西里尔同形折叠）；后两者检查连续失败后的推迟规则与它在真实 SQLite 触发器上的接缝（skipped 记录、触发器仍启用、成功重置、unknown 不推迟，以及已派发讨论后来失败时才计入、未定结果不计入）。`test_trigger_firing` 与 `test_team_prompt_safety_integration` 在真实 Copilot/运行账本上用合成模型回复检查：围栏与定时执行说明确实进入模型输入，存储的问题、回答和回答哈希保持原字节。均为合成数据，不调用真实模型。

完整模式另运行 `test_decision_checks` 与 `test_decision_checks_mcp`：选品记分卡、需求趋势互证、竞品快照变化、货件差异核对与单变量实验评估五项只读计算的合成数据检查，以及隔离 HTTP 和三种实际 stdio 入口的只读标注与结果一致性。它们不证明阈值适用于真实店铺，也不涉及任何平台读写。

完整模式强制运行 `test_workspace_research` 与 `test_workspace_research_stdio`，覆盖完整来源和研究头的原子版本校验、并发单次写入、原回执幂等重放，以及 Codex/Hermes 实际 stdio 经隔离 HTTP 保存、读回与冲突拒绝。它们使用临时合成数据库和本轮 loopback fixture，不证明原生宿主或真实商品资料已经保存。

研究表单浏览器门禁独立启动临时合成 HTTP 服务，通过实际页面和 iframe 桥接保存，不用 DOM 注入或伪成功回执代替写入。未知结果检查先让真实端点提交，再暂缓并丢失该响应，最后由界面显式重试同一请求并核对原回执；普通未保存输入仍可明确放弃。它只复用已安装的 Playwright/Chrome，继承本轮隔离环境、Python 预加载路径和网络 guard。完整入口同时校验八类必需交互、非空成功检查、完成标记、无脚本错误/外部请求，以及五份候选文件的起止 SHA 与当前快照一致；driver 退出 0 或仅有截图均不足以通过。

## 已有依赖

需要 Python 3.12+、Node 20+、npm、项目锁定依赖、已安装的 Playwright 和 Chrome/Chromium。默认依次选择项目 `.local/crawlers/venv/bin/python`、`.local/commerce-runtime/venv/bin/python`、`.venv/bin/python`、`venv/bin/python`，最后才使用启动解释器；依赖不齐会失败，不会悄悄换环境重试。覆盖方式：

```sh
COMMERCE_PYTHON=/path/to/existing/venv/bin/python make verify
PLAYWRIGHT_MODULE=/path/to/existing/playwright/index.mjs CHROME_PATH=/path/to/chrome make verify-fast
```

Playwright 自动寻找 workbench 已安装模块及当前用户现有 npm npx 缓存；不执行 npx 或下载。Chrome 默认寻找 macOS 已安装应用和 PATH 中的 Chromium/Chrome。未发现现有依赖时，先由维护者按项目锁文件准备环境，再重跑。Python 依赖声明在 `commerce/requirements.txt` 和 `commerce/a2ui/requirements.txt`；npm 使用两个已有 package-lock。可用以下原有安装命令准备依赖，验证入口本身不执行这些命令：

```sh
/path/to/venv/bin/python -m pip install -r commerce/requirements.txt
npm ci --prefix commerce/workbench
npm ci --prefix commerce/workbench/map
```

`VERIFY_BOOTSTRAP` 只覆盖 Makefile 用于启动验证器的 Python；`COMMERCE_PYTHON` 指定实际测试 venv。

## 隔离与清理

每次将 Commerce、所需爬虫导入与验证器文本源码复制到独占 scratch 目录；不复制 `.local`、隐藏目录、业务状态、缓存、旧 QA JSON/图片或配置凭据。已知本机生成连接 `commerce/integrations/mcp.json`、`hermes.json`、`codex.toml` 按准确根路径排除，其它集成源码和嵌套配置仍在验证范围；这个排除不代替发布扫描。源文件/目录软链接被拒绝。两个已有 `node_modules` 通过链接复用，仅供现有工具读取。测试命令在源码副本执行，因此原 npm 测试的固定产物路径也落在副本中。

子进程使用新环境、空的临时 HOME/TMPDIR、独立 COMMERCE_STATE 和 npm 缓存，不继承 provider URL、密钥、代理、QA 开关或 NODE_OPTIONS。Python/Node 预加载网络 guard，只允许本轮 fixture 注册的 loopback 端口；外网 DNS、外网连接及未注册的本机端口被拒绝并记为失败。原浏览器驱动另拦截外部页面请求。此 guard 是回归运行约束，不是对恶意测试的操作系统安全沙箱；不应向白名单添加未经审查的脚本。

多会话协作登记 `commerce/WORK_COORDINATION.md` 按准确根路径排除在源码指纹和副本之外：它在检查运行期间会被其它会话追加，且没有任何代码或测试读取它；此前把它计入指纹，使各门禁全部通过的回执因“运行中漂移”作废。其它文档（包括子目录里的同名文件）、源码和产物仍在指纹内，任何改动照常使回执失效。

只清理本轮 `mkdtemp` 创建的 scratch 子树和本轮子进程组；不按名称或端口杀进程，不清理其它会话目录，不重启已有网关。失败日志、命令退出码、耗时和交互证据保留在本轮私有目录。并行运行各有独立 run_id，最新完成者更新 latest；历史回执不覆盖。

## 回执与验收边界

每轮产物位于 `.local/agent-team/builder/runs/<run_id>/`：

- `receipt.json`：profile、实际命令数组、退出码、耗时、必需门禁、未运行项、源码逐文件 SHA-256、整体指纹、运行中漂移与清理状态。
- 各门禁 `.log`：保留全部 stdout/stderr，失败也不删除。
- `evidence/python-unit.json`：实际测试数量、失败、错误和跳过明细。
- `evidence/browser-results.json`：浏览器实际交互断言、驱动要求、完成状态与候选 manifest 指纹；失败可能另有截图和服务日志。
- `evidence/product-research-browser.json`：研究表单的真实写入/冲突/未知恢复检查、完成标记、起止候选 SHA、脚本错误与外部请求；仅完整模式生成。

`.local/agent-team/builder/latest.json` 和 `report.md` 指向最新完成结果。任务状态 `awaiting_review` 与 `verification_status` 分开；执行完成或生成回执不等于通过，更不等于主控接受。入口退出码为 0 才代表该 profile 所列必需门禁全部通过；超时、未知和未运行均不能算通过。源码变化后必须重新检查。

未覆盖：原生 Harness/Codex/Hermes 的实际版本与交互、物理设备、真实店铺、真实模型、支付/消息/上架、白名单外 Python 套件、整个产品验收及开源脱敏。普通验证不会访问真实业务状态，不能提供真实经营动作成功的证明。
