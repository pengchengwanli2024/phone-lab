# 来源项目的研究与吸收

## 2026-11-16：OpenMausBot 的运行边界与预览调度

固定来源：[OpenMausBot `f8a2b5034f54c69bba0c0256103eb6a3fea8c65c`](https://github.com/milind-soni/OpenMausBot/tree/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c)。本轮选择性读取了服务端合同、驱动注册、MCP挂载/工具选择、恢复、设备控制与预览实现及对应测试，没有运行上游应用、安装其依赖或验证其真实云服务。

它的主要价值是把模型执行、工具授权、设备使用和会话结果集中在服务端，再让各客户端读取同一状态。本项目已有Python/SQLite共享后台及HTTP/MCP接口，吸收应补实际缺口，继续沿用当前账本、业务审阅和客户端产物。

| 上游源码/文档与机制 | 本项目对照及本轮处理 |
| --- | --- |
| [`contracts.ts`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/server/contracts.ts)、`harness/registry.ts`：驱动能力声明、共享探测、执行器生命周期 | 保留现有`host_execution.py`、`model_providers/`、`agent_runtime/`，没有增加第二套运行器。提供方可用、模型可用与真实任务完成仍分别核对；本轮不冒称兼容全部上游引擎或ACP |
| [`tool-selection.md`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/docs/tool-selection.md)、`agent-tool-policy.ts`、`drivers/turn-mcp.ts`：工具目录裁剪与调用时检查并存，空允许集合不放开全部工具 | 对照现有`agent_runtime/policy.py`和`copilot/capabilities.py`的服务端范围、版本冻结与复核。选择能力不能授予平台授权；只读判断不按名称前缀或第三方注解推断。本轮不改其它会话正在集成的能力选择器 |
| [`automatic-recovery.md`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/docs/verification/automatic-recovery.md)、`automatic-recovery.ts`：只有证明未开始的启动失败才考虑备用引擎，并核对工作区/能力 | 保留现有宿主租约、原生接收与完成回执、UNKNOWN和明确恢复。超时或无输出不能证明未执行，不因上游有fallback就自动重发、换模型或绕过经营审阅 |
| [`turn-dispatch-guard.ts`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/server/turn-dispatch-guard.ts)、`runtime/invariants.ts`：取消、代次与终态约束，迟到结果不属于新任务 | 原业务父任务已有owner/代次约束；本轮在手机快照接入相同原则，设备断开、重连或fleet停止后，旧截图不能回写当前缓存，延迟启动的旧worker也不能改采新连接 |
| [`computer-frames.ts`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/server/computer-frames.ts)及其测试：共享速率、并发上限、失败退避、复用已有帧与按需观察 | **本轮新增实现**：`phone_frame_policy.py`接入`phone_fleet.py`及原HTTP路由，4次/秒令牌补充、最多4次突发、最多3个并发截图；失败按5/10/20/40/80/120秒退避，成功重置。等待需求按先后安排，避免前几台长期独占；没有请求就不启动新的截图，也不因仅发现设备而截图 |
| `computer-control.ts`、`computer-selection.ts`：人类接管、租约归属、用户选定设备不得暗中迁移 | 保留`monitor/control.py`与显式开始/结束控制。预览预算只约束手机墙静态截图，不授予控制权，不将输入排队到另一台设备；Android详情实时流仍沿原桥接。本轮没有新增多人控制或远程接管 |
| [`agents-tool-bridge.md`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/docs/agents-tool-bridge.md)、`drivers/tool-failure.ts`：统一工具生命周期与失败归因，回答不是执行证明 | 继续使用本项目原工具/经营回执及受控生成式目录；工具错误不当成模型账号错误，外部文本不当指令。没有移入上游任意HTML组件或命令执行能力 |

缓存补齐：fleet最近成功读取的快照最多复用15秒，过期或时钟回拨时原`/phone/fleet/frame`返回503，状态沿用`phone_frame_unavailable`及原`frame_at`；失败、限流或仅返回缓存时不会刷新最后成功时间。`phone_bridge.snapshot`同时拒绝未来时间戳的流帧，防止旧缓存重新进入fleet。正在进行的只读截图仍依赖原提供方超时退出；停止会丢弃结果，不声称已经强制终止底层进程。

许可核对：固定版本根[`LICENSE`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/LICENSE)为Apache-2.0，根[`NOTICE`](https://github.com/milind-soni/OpenMausBot/blob/f8a2b5034f54c69bba0c0256103eb6a3fea8c65c/NOTICE)保留作者与第三方归属。本轮只借鉴机制并在原Python结构中独立实现，没有复制上游TypeScript、图片、商标、依赖或运行包。首轮未引入云电脑/Local VM、Composio连接、语音、手机配对或团队导入；后续用户明确要求继续吸收，适配范围见下文。

源码阶段验证：`python3 -m unittest discover -s commerce/qa -p 'test_phone_*' -v`在Python 3.13、3.14及现有运行虚拟环境中均48项通过；覆盖合成设备并发/公平/退避、缓存过期、断开/停止/重连隔离，以及实际loopback HTTP鉴权、Origin、响应和原手机桥接/MCP打开入口。另用现有`.local/commerce-runtime/venv/bin/python`运行`test_host_execution`、`test_host_recovery_contract`、`test_host_parent_fencing`共35项通过，确认本轮对照的既有宿主边界；默认解释器缺少`jsonschema`的早期失败保留在私有记录，没有修改宿主源码或安装依赖来绕过检查。

同日授权加载与实际验证：共享产物不一致时加载前检查先行拒绝，未重载；产物同步后，本项目日常后台在在线备份、空闲核对和源码冻结后完成重载，99张保护表原有行、配置及其它网关一致。现场发现历史paired iPhone在传输不可用时仍误列在线，新增4项发现测试并修复，最新52项手机回归通过。实际Harness手机入口→Chrome、本机手机页刷新/0台空态、浏览器返回工作台及重新进入通过，真实HTTP鉴权与失败响应通过。用户因暂不能连接手机明确先验服务与Harness，真机画面、控制与多机负载仍Not Verified；原生其它模块/模型执行不据此宣称通过。本轮未公开推送，私有加载记录沿原`openmausbot-20261116/live`保留。

## 2026-11-16：OpenMausBot 的团队、预设与本机使用入口

用户追加要求后继续对照固定版本的 `docs/team-sharing.md`、`presets.md`、`headless-cli.md`、`voice-mode.md` 和 `custom-mcp-servers.md`。采用原服务和原任务账本独立实现以下适配，未复制上游代码或安装上游运行器：

| 适用能力 | 本项目入口与边界 |
| --- | --- |
| 可配置助手 | 能力库 → 智能体团队 → 成员。保存名称、既有岗位、说明和最多三个启动模型偏好；不会因保存而调用模型。新会话冻结成员配置，说明同时传入普通回答与研究阶段；备用仅在启动前选定，不在未知结果后重发 |
| 内部频道与多人提问 | 频道保存共享说明、业务范围和1–4位成员；明确提问后分别创建原Copilot请求。讨论读取同一研究task当前run、逐成员状态和结果，可取消活动请求或打开原对话继续；没有自主互聊、外部群聊或新增工具权限 |
| 团队预设共享 | 选定频道导出受限JSON/Markdown，导入先预览并核对哈希；仅新增停用成员和示例范围频道，不带模型映射、凭据、授权、业务对象或历史。文本仍须人工审阅后分享 |
| MCP工具发现 | 工具发现页只对已登记MCP-HTTP扩展执行握手和tools/list，返回有界目录与Schema供审阅。不会调用、测试或启用工具；仍沿能力库原登记、测试和授权流程使用。不包含SSE、stdio、任意命令或OAuth新连接 |
| 本机答案朗读 | 已完成成员回答旁“生成朗读”，按原thread/run/答案哈希核对后，用已安装macOS语音和ffmpeg生成临时WAV，手动播放；不上传文字、不安装语音、不自动播放。不包含麦克风转写、实时通话或云语音 |
| 无界面操作 | `python3 commerce/assistant_cli.py --help`；doctor/catalog/open/ask/get/wait/cancel与预设export/preview/import，沿原鉴权HTTP调用。wait超时只停止等待，不取消或重发；ask须显式给频道版本和幂等键 |

云电脑、每成员Local VM、Composio/OAuth账号、手机远程配对和实时通话涉及独立基础设施、账号或设备，尚未接入。现有工作流、技能、模型账户、记忆、经营审阅和手机控制继续复用，本轮不以另一套编排替换。本轮实际验证：完整依赖环境下运行后端全量1574项（1573通过、1跳过）；初次解释器缺parsel的2项错误保留，未安装依赖，改用已有采集环境复验。最后实际流程发现并修复状态摘要漂移、仅标点补问和团队原会话恢复接缝后，原Copilot118项、运行器17项、新模块及共享产物70项、前端285项、类型及统一构建同步检查通过。日常服务已按空闲、在线备份、源哈希及保护表核对加载，未改旧请求或其它网关。

实际免费本机Qwen成员提问、同键不重复运行、原会话继续发送并保留模型/绑定、两个排队请求取消、浏览器文件导出/预览/停用导入、真实本机MCP握手/目录读取和本机WAV点播通过；1440/390像素、深浅色、编辑表单/键盘检查通过。MCP目录使用明确标注的临时本机验收服务，并非外部MCP账号验收；服务已停止、登记项仍停用。小模型的回答内容仍需人工核对。

首次原生接续因Mac锁屏受阻的记录保留。用户解锁、协作owner完成另行获批的Harness重启后，本轮已实际验证原生17.010秒MCP目录请求完整返回、原回答/固定Qwen/示例范围恢复、本机语音点播结束4.5663秒、原生文件选择→预览→确认导入为停用配置，以及双成员明确提问completed且各仅1条原turn。临时目录服务已停止、登记仍停用；窗口已归位订单页/空输入/智能选择/系统主题并释放。本轮未自行重启Harness或重发其它unknown。真机继续按用户决定后置，未执行公开推送。逐项私有证据在原`openmausbot-20261116/remaining/verification.json`。

## 2026-11-16：追加自动路由、有限协作、完整预设与本机触发器

用户明确追加四项后，继续对照同一固定 OpenMausBot 版本的团队路由、共享格式和触发机制，另核对官方团队包格式。此前章节“没有自主互聊”的限制现由以下有界顺序协作补齐；未复制上游运行器或绕过原工具、经营审阅和账户权限。

| 能力 | 本项目实现与入口 | 边界 |
| --- | --- | --- |
| 自动群聊路由 | `assistant_team_routing.py`；智能体团队 → 频道 → 响应方式、关键词、擅长领域和主责 | 确定性 @点名/关键词/擅长/主责选择，可仅响应点名；不声称是上游语义路由或外部群接入 |
| 成员协作 | `assistant_team_discussions.py`；讨论记录 → 顺序协作并汇总 | 1–4 人、1–3 轮贡献及主责最终汇总，最多 13 个原成员请求。前序回答带原请求与哈希，作为不可信参考；失败/未知/补问/审阅停止，不自动重发；读取状态不推进 |
| 完整预设 | `assistant_team_packages.py` / `assistant_team_preset_store.py`；导入团队、团队预设、完整导出 | v1 兼容、v2 与 YAML-frontmatter Markdown；团队指令、主责、成员/频道、剧本、起始笔记、技能说明、接入需求和触发器。无凭据/历史/模型继承，导入停用/示例范围/暂停；不支持的上游条件可见延后，讨论绑定需重新设置 |
| 团队触发器 | `assistant_team_triggers.py` 接原 `capability_lifecycle`；触发器及 CLI/MCP | 手动、一次、间隔、每周、本机事件和原讨论结束后；明确启用、版本冻结、事件去重、忙碌不重叠、未知不重放。复用本机鉴权入口，不建公网 webhook、不装外部账号 |

使用步骤见 [README 的智能体团队](README.md#智能体团队与团队预设)。真机、云电脑/每成员 VM、外部群账号、Composio/OAuth、跨网服务和实时通话按用户决定后置；上述本机适配不代表这些设施已集成。模型回答质量与事实仍需核对，运行完成不等于真实经营动作完成。

## 2026-11-16：十个参考项目的实际落地对照

本次按用户要求复核既有吸收记录、当前依赖/调用链及实际验收。11个链接对应10个项目，json-render官网与仓库合并统计。2026-11-16再次读取10个项目的官方README及json-render官网，并对照当前代码与既有验收回执；本表不是10个上游仓库的逐行审计。**直接依赖、协议接入、思路借鉴、业务验收是不同层级**；没有证据的来源归因不补写，已有基础能力不冒充本轮新发明。下表“已实现”只指明确列出的适配范围，不代表整个上游产品已搬入或项目已全面上线。

| 参考项目与上游能力 | 本项目已吸收/应用 | 当前代码依据 | 尚未吸收、未完成及取舍 |
| --- | --- | --- | --- |
| [OpenBitFun](https://github.com/openBitFun/OpenBitFun)：持续任务、上下文管理、桌面/手机接续、可扩展工作区 | **思路借鉴，有对应实现**：原任务持久化、时间线/待办、任务范围记忆召回、来源变更失效及范围核对。L1/L2/L3沿本项目原资料账本实现，不声称复用了其记忆代码 | `autonomy.py`、`followups.py`、`task_timeline.py`、`copilot/memory_scope.py`、`layered_memory.py` | Rust运行器、Relay/账号服务、四种Harness模式、Mini App市场未引入；手机远程身份与接管按用户决定后置。通用Hooks和自动学习没有作为本轮已完成项 |
| [CopilotKit](https://github.com/CopilotKit/CopilotKit)：前端Agent状态、交互式Surface/AG-UI | **SDK实际使用 + 适配器储备**：锁定`@copilotkit/react-core 1.87.0`、`@ag-ui/client 1.0.2`；成本Surface确实调用SDK。`CommerceAgent`已有事件/恢复适配及专项测试，当前主聊天仍挂载`window.CommerceCopilot`，没有使用该适配器 | `workbench/package.json`、`src/surface-provider.tsx`、`src/calculation.tsx`、`src/cost-page.tsx`、`src/commerce-agent.ts` | 未完成以AG-UI适配器统一接管主聊天；不能把代码存在或SDK安装算作生产主链全面接入。原聊天已有实际增量journal/游标恢复与受控组件展示；compatible/Hermes按实际提供方能力，Codex适配为CLI消息事件、host-native最终结果降级。Intelligence及自动学习未接入，不承诺所有提供方逐Token |
| [OpenDots](https://github.com/CopilotKit/OpenDots)：对象会话、聊天内审阅、可编辑产物 | **思路借鉴，有对应实现**：商品/任务范围与原对话绑定、未发送草稿保持、原资料/修订CAS、变更后重新审阅及回到原工作 | `copilot/context.py`、`copilot/methods.py`、`form_drafts.py`、`product_workspace.py`、`listing_release.py`、`web/copilot-ui.js` | 未安装OpenDots应用或Intelligence。通话、Slack、每Agent独立计算机不是本轮接入项；当前独立对话仍在本项目账本内 |
| [OpenBot](https://github.com/CopilotKit/OpenBot)：权限、动作前审批、执行后审计、失败状态分离 | **思路借鉴，有对应实现**：待执行/失败/未知分开，读失败撤销正向就绪；准确版本人工核查、预算、幂等、单次HTTP正文及真实任务回执 | `extension_runtime/`、`agent_runtime/policy.py`、`copilot/receipts.py`、`listing_actions.py`、`listing_submissions.py`、`owner_review.py` | 未引入其身份系统、每Bot容器/浏览器、Kubernetes/PostgreSQL或另行许可的Intelligence。桌面本机权限不等于多用户/多租户隔离。真实上架尚待资料、签收及单独执行授权 |
| [openmuse → OpenFuse](https://github.com/CopilotKit/openfuse)：可见工作、持久任务、接管与审批 | **借鉴进度/草稿/审批/回执同屏**：时间线、等待输入/审阅、取消/明确恢复、版本和原回执可见；原执行者继续负责实际动作 | `task_timeline.py`、`attention.py`、`followups.py`、`host_execution.py`、`workbench/src/task-timeline.tsx` | 该旧地址实际重定向OpenFuse，不能把名称当作图片/视频生产框架。其浏览器/终端计算机、Gmail/Calendar、PDF/财务应用未搬入；本项目媒体生产来自自己的创意/执行器与提供方适配 |
| [OpenIntelligentUI](https://github.com/CopilotKit/OpenIntelligentUI)：按任务选择文本、比较、原生或自定义交互 | **选择性借鉴**：模型从10类受控组件中选择/排序；缺项、报价/成本、交付、上架、技能及证据/差异/回执仍取原观察和账本；比较计算由确定性后端负责 | `generative/catalog.json`、`web/generative-ui.js`、`supply_quotes.py`、`cost_scenarios.py`、`ui/kit.js`、`copilot/reads.py`、`a2ui/contract.json` | 未引入其任意HTML/CSS/JS生成沙箱。已增加`generative/catalog.json`中10类受控业务组件的模型选择/排序与原引用绑定；目录以外的工具、图表及代码不在此范围，也不开放代码执行。已有3D情报地图是固定业务模块，不是已实现任意生成3D工具的证据 |
| [json-render仓库](https://github.com/vercel-labs/json-render) / [官网](https://json-render.dev/)：Catalog/Schema与渲染Registry分离 | **架构思路借鉴**：成本目录、字段Key/节点身份和事件定义单源，生成Python/React两侧合同；未知组件/字段/动作拒绝 | `a2ui/contract.json`、`a2ui/build_contract.py`、`workbench/src/cost-contract.ts`、`a2ui/cost.py` | 未安装`@json-render/*`。其协议不是A2UI；SSR/全应用路由、PDF/Email/Remotion、多框架渲染及全站动态目录没有直接接入。新增业务catalog复用原成本字段标签与身份，覆盖证据、报价、交付、上架、技能、成本、差异、追问、建议和回执；仍仅支持已登记组件 |
| [OpenUI](https://github.com/thesysdev/openui)：受控组件、目录驱动提示、渐进渲染 | **部分思想吸收**：允许组件与实际渲染器分层、复用本项目组件及标准表单降级；没有增加另一份状态真相 | `a2ui/contract.json`、`workbench/src/calculation.tsx`、`workbench/src/surface-provider.tsx` | 未安装OpenUI Lang解析器/运行时。现以本项目受控目录实现“目录→模型选择→校验→增量预览→最终展示”，预览有大小/事件上限与明确限量提示；不将排队状态或上游速度宣传作为流式/性能证据 |
| [assistant-ui](https://github.com/assistant-ui/assistant-ui)：组合式聊天、草稿/阅读状态、工具结果 | **交互思路借鉴，有对应实现**：输入草稿、选区/组合输入、阅读滚动/加载更早记录保持、工具依据与原回执、原问题续接；已补受限参考资料上传、文字提取/对象引用和发送时冻结 | `web/copilot-ui.js`、`workbench/src/assistant.tsx`、`workbench/tests/copilot-composer.test.mjs`、`copilot-drafts.test.mjs`、`copilot/receipts.py`、`copilot/materials.py` | 未安装`@assistant-ui/*`，没有替换既有聊天运行器。完整附件/视觉理解链路、语音输入/实时通话、任意历史分支编辑和长会话虚拟列表未实现；本机答案朗读已由其它适配实现，不归因为直接复用assistant-ui；提供方增量能力分别声明；未知写入不使用普通聊天重试 |
| [A2UI](https://github.com/a2ui-project/a2ui)：数据而非任意代码、受控目录/原生渲染及能力协商 | **协议/规范子集接入**：保留0.8投影和受限1.0成本Surface；Schema、节点/事件、绑定范围、修订/幂等由服务端复核，不支持时回标准表单 | `a2ui/spec/`、`a2ui/catalog.json`、`a2ui/cost.py`、`workbench/src/cost-page.tsx` | 不宣称完整实现全部版本/组件/补丁语义。Flutter/SwiftUI/Compose等客户端、全站任意Surface组合及所有宿主原生写流程没有全面验收；不能因上游提供渲染器就标本项目兼容 |

### 本轮生成式补齐（2026-11-16）

本轮沿用原Python运行器、SQLite账本、成本Surface和共享界面，不新增模型运行器或UI框架。`commerce_copilot_catalog/events`提供只读目录/原请求增量；业务展示采用本项目`commerce-generative-surface-v1`，不冒称A2UI全协议。模型只选择组件及既有引用，字段值、图片读取、导航对象与操作校验由宿主产生。

| 核对范围 | 本轮实现与验收边界 |
| --- | --- |
| 统一目录、字段身份 | 10类业务组件目录；成本字段标签沿用原`a2ui/contract.json`，稳定组件身份与来源绑定 |
| 原成本动态Surface | 继续复用既有受控成本表单及标准表单降级，不替换持久化与测算器 |
| 校验、来源与写入边界 | 未知组件/引用/自造数据/动作拒绝；错误布局保留已校验回答并降级；报价、上架、技能来源变化后重新核对，原审阅/CAS门禁保留 |
| 证据、追问、建议、差异、回执 | 已进入业务目录；建议仍走原人工审阅，本地任务回执仍读原任务，不把排队或模型回复当经营成功 |
| 报价、交付、上架与技能 | 当前对象只读卡片、报价需求与商品小计、交付缺项、上架产品信息及准确保存版本图片、技能条件；可回到原商品工作区，不代选供应商/签收/发布 |
| 宿主呈现 | 浏览器/React/iframe使用同一renderer；stdio宿主返回结构化数据和原工作区降级入口。实际Harness已用本机Qwen单次请求验收Questions卡片、草稿保持及清理恢复；Codex/Hermes原生富UI不据此宣称兼容 |
| 真增量、断线与限量 | 提供方实际内容增量写入原run journal，按游标读取/重连，不重发模型；预览明确未校验，最终失败/UNKNOWN撤下预览；限量不终止正式答案。读取增量采用共享HTTP/MCP，不依赖额外推送服务 |
| 模型按任务组合 | 模型按本轮菜单选择/排列组件，服务端从冻结观察解析内容；最终结果、回执与原上下文绑定。非任意HTML/JS，也不自动授予目录外工具 |

本轮上述8项在受控目录范围均已实现。统一构建后实际复验280项前端、类型检查、5项共享bundle/Harness合同及全源`build.py --check`均通过；另有51项生成式/传输/能力及接口回归通过。此前1401项完整后端回归为1399通过、1跳过，唯一产物同步失败已单独复验通过，不将原失败日志改写为全绿。9组隔离真实DOM验收覆盖刷新同请求/草稿、报价MOQ与整包数量、交付/成本、上架产品字段与图片、图片重绘保持、准确对象导航、UNKNOWN及预览上限，包含1440浅深色和390视口。

Harness本轮实际选择免费本机Qwen，只发送一次概念问题，显示模型选择的Questions卡片并正确停在等待补充；原run journal回读到31条真实回答增量、组件与最终settled事件。原生没有捕获逐Token画面，不据此宣称所有模型均逐Token展示。结束已清空本次未发送草稿并恢复助手欢迎/智能选择，保留当前业务页面、系统主题和其它会话原unknown请求；30张经营表及12份根配置的前后哈希一致，无经营动作或店铺写入。

生成式helper及相关共享产物已核对一致；全源同步检查曾因并行团队页面仍在编辑而提示待重建，统一构建后已实际复验通过，保留原过渡失败记录。团队与内容新页面本身的实际业务和原生验收仍由各自会话负责，不因整包同步就算作本轮已验。上述完成范围不等于全站新功能、所有宿主版本或真实店铺已全面上线；真实经营资料、负责人签收和准确版本发布授权继续分别验收。

### 原三批适配项的逐项统计

统计单位为**从原已确认范围归并的13个适配项**，不是上游仓库、页面或长期42项需求。保留软件实现与真实运营验收两个维度：

| 编号/原批次 | 计划应用的内容 | 实施状态 | 当前实际边界/剩余 |
| --- | --- | --- | --- |
| B1-01 | 统一组件目录与字段身份 | 已实现（限定目录） | 成本字段/节点/Schema单源；不是全站所有动态组件都已登记 |
| B1-02 | 助手按任务范围检索项目记忆 | 已实现 | 原对象/店铺/市场/模式及资料版本约束，来源撤回使派生依据失效；不是无限跨项目记忆 |
| B1-03 | 证据、差异、回执与缺项展示 | 已实现 | 结构化依据、前后差异和真实任务状态；不将排队/HTTP接受当业务完成 |
| B1-04 | 草稿、滚动及输入交互保持 | 已实现 | 模块往返、并发冲突、选区/组合输入、历史读取；不是所有宿主和版本均已验收 |
| B2-01 | 多报价与包装事实、数量比较 | 已实现 | MOQ/整包装/有效期/币种/来源及显式选用；真实首发采购费用仍缺，不能代填 |
| B2-02 | 成本情景 | 已实现 | 不可变情景、当前输入比较、变化失效；不推定利润或结算已接通 |
| B2-03 | 可编辑商品交付包 | 已实现（约定范围） | 商品内容/翻译/素材引用、审阅清单、版本及私有导出；不是完整图片/视频专业编辑器，实际首发交付仍待经营核对 |
| B2-04 | 最小能力登记与技能可执行条件 | 已实现（最小范围） | 固定来源/模式/输入/依赖检查；声明式扩展可测试、启停、版本化，不能把任意下载脚本当获准执行 |
| B2-05 | 类型化流程及版本 | 已实现 | 文本/画布共用计划、DAG校验及不可变历史；载入旧版只产生草稿，不重放任务 |
| B3-01 | 单一真实渠道/平台动作 | 部分完成 | Ozon图库/整卡准确版本、人工确认、单次发送/未知恢复和回读代码已接通；真实只读及合成写流程已验，真实店铺写入仍为0，待准确商品授权；个人微信实收未闭环 |
| B3-02 | 媒体执行器 | 部分完成 | 图片制作/登记/版本/审阅已有证据；已增加参考拆解、脚本、素材选择/粗剪、字幕/音轨、制作预检、实际短片及封面/字幕/质量报告交付包，有合成素材真实渲染、播放和Harness验收。完整商品UGC生产质量与真实效果回流仍未闭环，提供方和付费授权独立核对 |
| B3-03 | 移动身份与远程接管 | 按用户决定后置 | 尚未完成服务器域名入口、移动可信身份、撤销、跨网重连和手机运营/通知闭环；桌面手机浏览器承接不是移动远程完成 |
| B3-04 | 资产备份与恢复 | 已实现（隔离范围） | 数据库、登记媒体和私有配置在隔离副本按哈希恢复；不等于生产灾难切换、全部第三方依赖或所有设备已恢复 |

**合计：10项在上述约定范围已有实现，2项部分完成，1项明确后置。** 13项中没有把“尚无真实写入验收”藏到“代码已完成”里；也不把后置移动项重新包装成新批次。此次2026-11-16原生复验补齐上架目录、冻结申请/当前S6包5图切换、缺资料/旧版阻止提交及核查入口焦点；正常/未知真实写流程依用户要求未运行。之前其它页面原生证据仍按各自版本保留，不由本轮只读验收一并覆盖。

### 适合继续吸收但尚未落地的能力性质

| 能力 | 当前状态 | 是否属于已确认实施项 |
| --- | --- | --- |
| AG-UI统一主聊天 | 事件与恢复适配器已有并通过专项，但主聊天仍用原共享助手工厂，尚未调用该适配器 | 技术储备/进一步接线候选；保留既有架构并不要求为此替换整套聊天 |
| 从执行轨迹自动提炼技能/自动学习 | 未形成自动采集→提案→评估→批准发布→回滚闭环；分层记忆和人工提炼不等于自动学习 | 长期候选，未承诺本轮实现 |
| 通用Hooks | 已有确定性门禁、事件和任务状态；通用用户可配置Hook体系未实现 | 长期候选 |
| 完整插件生态 | 已有受限声明式登记/测试/启停/版本/回滚；分发市场、依赖解析与任意代码沙箱未做 | B2最小能力已完成，扩大生态属于后续范围 |
| 长会话虚拟化与更多动态可视组件 | 已有分页读取、较早记录和滚动保持；虚拟列表、任意图表/3D/编辑器的受控目录未完成 | 未纳入本轮8项生成式承诺，需先定义收益与合同 |
| 企业SSO、多租户与每Agent隔离电脑 | 未引入OpenBot/OpenDots的企业身份、容器电脑或后台基础设施 | 当前桌面首发不采用，不计为漏做 |

可配置助手团队、内部多人提问、停用模板导入、本机答案朗读、MCP工具发现及CLI的实现见本文件OpenMausBot章节。它们与上述项目有功能相似处，但已有明确的另一参考来源，不能为了填表重新归因为从这10个项目复制或直接集成。

### 明确追加的业务适配（与原13项有交叉，不重复加总）

| 用户确认的补充 | 当前状态与依据 | 仍未完成/需另验 |
| --- | --- | --- |
| 商品/货源采用商品列表，图片、筛选、详情和来源关联 | 已有受限实现：`product_catalog.py`、`web/catalog-ui.js` | 平台抓取覆盖和报价真实完整性不由卡片界面保证，缺值仍保留 |
| 图片/视频按产品理解、参考拆解、创意和版本审阅生产 | 部分完成：`creative_workflow.py`、`creative_studio.py`、`creative_editing.py`、`creative_preflight.py`、`media_providers/` | 图片候选及本地短片/粗剪/字幕/交付包已有实际证据；真实商品完整UGC、生产质量及效果迭代仍归B3-02，不以2.5秒合成试制等同业务全部完成 |
| 销售/内容表现关联素材版本，定期提出迭代 | 未形成完整真实业务闭环 | 已有运营统计/分析、素材版本及反馈入口；真实点击/转化/退货/观看数据、准确素材归因及受审核再生产不能由统计折线或示例报告代替 |
| 上架与日常管理的桌面闭环 | 部分完成，归B3-01 | 上架准备/审阅/单次执行与回读代码已有；真实资料、门禁和实际发布/经营回读尚待分别关闭 |
| 自动跟页、选中对象带入、店铺/筛选版本与错误提示、输入上方可见范围 | `copilot/page_context.py`及现有页面发布接缝已接入；本轮实际核对商品对象只读问答、情报页位置、历史问题接续和简报返回原模块/会话 | 上下文展示不构成经营执行授权；本轮已验路径不代替所有页面、平台与错误分支的全量验收 |
| 通用WebSearch、Open-WebSearch与AnySearch技能 | 项目技能保留；后台新增`public_web.py`及`public_web_transport.py`，直接复用已安装Open-WebSearch的固定请求入口，统一HTTP/MCP/助手工具接线。实际完成三地区搜索、正文读取、中文分析、本机简报执行和跨宿主回读 | AnySearch未作为后台运行依赖；搜索摘要、未知日期及未独立核实来源明确区分。公开网页内容不能授权动作；真实店铺写入、付费与发布仍按原授权边界验收 |

### 未落地能力的计划性质与顺序

| 能力 | 是否已在本轮承诺/实施 | 后续处理 |
| --- | --- | --- |
| 首发真实成本/品牌/包装/税率、交付与S6、准确上架授权及回读 | 已确认，仍待真实资料与人工环节 | 首发最高优先；不能由模型签成已核实。先补事实/准确版本，随后由经营负责人签收，再单独授权店铺写入 |
| UGC带货与产品展示短视频、按效果迭代 | 用户明确追加，部分实施 | 继续按理解产品→参考拆解→创意→脚本/分镜→生产/审阅→效果版本关联；数据不足不伪造效果，未连接/未付费不假装生成 |
| 其它电商平台与Shopify/WooCommerce | 保留适配方向，未全面真实接通 | Ozon桌面优先；逐平台授权、类目、价格/库存、规则与回执分别验收，不能用通用字段称全部可运营 |
| 移动远程运营/个人微信提醒 | 已确认后置 | 待用户提供服务器/域名并完成可信入口与实收；与桌面首发分开 |
| 完整插件分发与依赖沙箱生态 | 长期目标；受限生命周期已有部分实现 | 现有声明式扩展已支持登记、校验、测试、启停、版本及回滚；继续沿原执行器。市场分发、自动依赖解析、任意第三方代码的独立沙箱和全生态兼容未实现，不是原B2最小能力登记的漏项 |
| 全项目自动学习、通用Hooks、自动记忆提炼 | 长期候选，未完成方案/权限验收 | 现有来源绑定的分层记忆不等于自动学习；不能默认启用 |
| 全站任意生成式UI/任意代码沙箱、第二渲染协议 | 未作为本轮执行承诺 | 当前不采用任意生成代码；新受控组件需业务收益、Schema/事件与各宿主兼容测试，非简单安装SDK |
| 上游通话/Slack/Gmail/财务、每Bot容器电脑、Rust运行器 | 未纳入本次业务范围 | 不列为漏做或待上线必需项；有实际业务需求再评估 |

上线所需经营资料与签收责任在本轮实际私有审阅包集中提供，不在开源文档中放入真实商品、账号、素材或经营数据。本表不变更已有授权，也不授权新的开发范围、付费、真实消息、店铺写入或生产部署。

## 2026-11-14：从界面参考扩展到功能缺口

本轮对照实际调用链补充功能信息，不以项目宣传、组件数量或已安装SDK推定业务已经可用。以下为选择性源码/文档核对，不是上游完整安全审计或其生产有效性的独立证明；没有安装新的运行器、框架或服务。

| 参考与证据 | 吸收方式 | 项目接入、冲突与边界 |
| --- | --- | --- |
| [OpenBitFun](https://github.com/openBitFun/OpenBitFun/blob/main/README.md) | 借鉴任务持久化、上下文分层与跨设备接续 | 保留项目Python/SQLite和现有宿主适配；Rust运行器、Relay及账号服务是另一套基础设施，未引入。长期记忆、Hooks与远程能力需逐项验收 |
| [CopilotKit](https://github.com/CopilotKit/CopilotKit/blob/main/README.md) | 复用已安装的受控Surface/React接线；借鉴共享状态和审阅交互 | 以仓库锁定依赖和现有A2UI合同为准。开源界面与Intelligence持久化/学习服务分开，不把项目唯一存储迁到宿主或托管服务 |
| [OpenDots](https://github.com/CopilotKit/OpenDots/blob/main/README.md) | 借鉴对象会话、草稿保留、修订冲突和变更后重新审阅 | 项目复用原工作项/会话/版本账本；其页面SQLite与Intelligence会话的存储拆分不替换本项目核心，角色或工具开关不成为执行授权 |
| [OpenBot读取失败回归](https://github.com/CopilotKit/OpenBot/blob/48f34f42f91ead7b37c8b7312d0a93522a4faba9/app/tests/skills-read-failure.test.tsx)及[架构](https://github.com/CopilotKit/OpenBot/blob/48f34f42f91ead7b37c8b7312d0a93522a4faba9/README.md) | 借鉴失败/空态分离、运行器/权限/审计分层 | 沿原岗位门禁解释缺项、责任和复验，不把BLOCKED变为空数据或完成。模板MIT与独立Intelligence服务许可分别核对，不移入其记忆/学习服务 |
| [OpenMuse现转向OpenFuse](https://github.com/CopilotKit/openfuse) | 借鉴任务进度、接管、草稿、审批与原回执的同屏呈现 | 官方入口已重定向，不能按旧名称假定媒体制作能力。其Alpha、Rich Threads及外部账户前置条件单列；项目沿原执行器和租约，不接通新的容器或远程权限 |
| [OpenIntelligentUI](https://github.com/CopilotKit/OpenIntelligentUI/blob/main/README.md) | 借鉴按任务选择解释、比较和可操作工具 | 本轮把报价比较接入确定性后端和共享表格；其自定义HTML/CSS/JavaScript沙箱与本项目受控目录边界不同，不复用任意生成代码，也不假定支持跨调用补丁 |
| [json-render](https://github.com/vercel-labs/json-render/blob/main/README.md) | 借鉴目录/Schema与具体渲染注册表分离 | 成本目录/字段身份已有唯一契约；新比较和缺项视图只接收后台结构化数据。其规范不等同A2UI，不另装第二套渲染运行时 |
| [OpenUI](https://github.com/thesysdev/openui/blob/main/README.md) | 借鉴由允许组件生成提示、流式界面与状态适配分层 | OpenUI Lang与项目A2UI/业务JSON是不同合同，不能直接互换。暂不增加解析器、组件库或更换状态存储；上游性能宣传不算项目测量结果 |
| [assistant-ui](https://github.com/assistant-ui/assistant-ui/blob/main/README.md) | 借鉴会话状态、编辑器/阅读状态与工具结果分部件呈现 | 已补草稿/选区/滚动/组合输入及原回执保持；不为外观更换执行器，不将普通重试套用于未知业务结果 |
| [A2UI](https://github.com/a2ui-project/a2ui/blob/main/README.md) | 复用已锁定协议子集；借鉴数据驱动、原生目录和能力协商 | 原0.8投影与成本1.0 Surface分别维护，宿主不支持时明确降级；上游多端渲染不证明本项目各客户端已兼容 |

上述补充为官方文档核对及基于本项目合同的取舍判断；不等于已逐行审计全部上游、运行其部署或独立验证其生产效果。本轮未安装新SDK、遥测、云记忆或远程执行服务。

### 实际功能缺口及接续顺序

| 范围 | 代码观察 | 应补齐的闭环与验收 |
| --- | --- | --- |
| 商品助手的缺项解释 | `copilot/reads.py`原只保留阶段缺项数量，原岗位系统已有原因/责任/复验 | 本轮已接入有界只读说明及可读依据卡；新产物改变后重新读取，保留历史快照与未接入能力的阻断 |
| 供应链资料（B04） | 已在原产物账本接入多报价、不可变版本、MOQ、cm/kg包装和带时区有效期 | 保存与明确选用分开；新增按需求件数、MOQ和整包装计算采购数量、超出量与精确货款小计的只读对比，同一接口可供当前商品助手读取。变更数量撤下旧结果；报价版本/有效期变化阻断旧选择及助手依据。同工作项、同币种选用才更新原供应产物。过期或版本变化保留HOLD、使旧成本/助手依据失效；实际供应来源仍待人工核对，无换汇或自动采购 |
| 商品交付审阅（B06） | 已接入内容、翻译、真实图片交付哈希和成本的自动检查，以及事实、翻译、素材权利、规则四项人工清单 | 复用原业务审阅回执并绑定当前资料版本；缺项禁止确认，资料变更须复核，可导出私有交付清单。S6独立专业合规仍BLOCKED，不授予发布权限 |
| 技能与插件（X01/A07） | 已增加不创建任务的只读执行条件检查，复用固定来源、脚本/模式及草稿上下文校验 | 显示具体输入缺项与来源漂移；账户与外部权限保持未核实，模型运行可用性不在此探测。离线检查可请求不等于数据已有效，原执行器仍须明确触发并复验 |
| 经营结果 | S7/S9/S10分别保留广告归因、真实客户来源和结算适配器缺口 | 按真实来源与明确范围分别接入；未知费用/反馈不填零，模型解释与经营效果验证分开 |

需求优先级继续使用[现有台账](../docs/PLATFORM_BACKLOG.md)，不另建并行路线图。以上是当前本地闭环范围；真实账户、付费、对外发送、店铺写入及经营结果仍需其原有授权和独立验收。

日期：2026-11-10。本轮针对源代码、测试和技术文档作选择性研究，不是完整源码安全审计或真实经营验收。

## 固定来源

- [ozon-ops](https://github.com/tiantangcao1980-web/ozon-ops/tree/2121d98d9c34b62dc6580adf93f0e7943e29832e)：固定提交 `2121d98d9c34b62dc6580adf93f0e7943e29832e`，296 个版本控制路径。重点读取单位经济、选品、补货、SKU 毛利、广告判定及相关测试。
- [kjds](https://github.com/tiantangcao1980-web/kjds/tree/806fe6887dceec47501a3d36925ef27cead53eb2)：固定提交 `806fe6887dceec47501a3d36925ef27cead53eb2`，43 个版本控制路径。重点读取检索/分词、HTTP 客户端、动作护栏、预警引擎和许可说明。

参考仓库置于忽略打包的 `.reference-sources/`，没有执行其安装、打包或店铺操作脚本。适配代码的归属与完整 MIT 文本见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 已吸收的内容

| 来源能力 | 当前项目中的接入 | 针对半成品所做的调整 |
| --- | --- | --- |
| 单位经济拆分、缺数据 HOLD | `commerce_unit_economics` → `operations_analysis.py` | 所有成本和费率显式输入；没有默认采购价、默认佣金或旧 OGL 费率；使用 Decimal 计算，保留同币种成本明细 |
| 库存覆盖与整箱补货 | `commerce_restock_plan` → `operations_analysis.py` | 销量除以输入的实际窗口天数；计算过程不提前舍入日均；缺窗口或没有观测到需求时返回 HOLD，采购量为未知 |
| 中英混合按需检索 | 原 `commerce_knowledge_search` → `knowledge_ranking.py` | 加入中文二元组、少量运营同义词、标题权重、IDF、概念覆盖和重复次数上限；保留原有业务目录、软链接、大小和条数限制 |

两个新增工具都属于只读草稿计算，不读取真实店铺，不自动调价、投放广告、下采购单或修改库存。`data_source=caller_input` 表示数据由调用者提供，不代表已授权或已核对的店铺数据。

## 可以直接调用的接口

```json
{
  "tool": "commerce_unit_economics",
  "arguments": {
    "input": {
      "currency": "CNY", "price": 100,
      "purchase_cost": 30, "domestic_shipping": 2, "packaging": 1,
      "fulfillment_cost": 10, "electronic_fee": 1,
      "commission_rate": 0.1, "payment_rate": 0.01,
      "return_rate": 0.02, "ad_rate": 0.05
    }
  }
}
```

以上是合成演示，结果总成本 62、单件贡献 38、贡献率 0.38。金额全部为同一币种，采用两位小数的简化贡献模型，不自动换汇，也不等同于财务结算或净利润。

```json
{
  "tool": "commerce_restock_plan",
  "arguments": {
    "input": {
      "available": 10, "sold_units": 60, "window_days": 30,
      "lead_time_days": 14, "safety_days": 7, "pack_size": 6
    }
  }
}
```

合成结果为日均 2、覆盖 5 天、目标 42 件、整箱建议补货 36 件，优先级 P0。模型仅按输入窗口外推，不覆盖季节性、在途到货和未来销量变化；不会创建采购或库存操作。

知识检索仍使用 `commerce_knowledge_search`，例如 `{"query":"如何补货"}` 可以命中业务目录中的英文 `Replenishment` 内容。未扩大 Obsidian 目录或导入上游技能库；笔记内容仍作为资料而非执行指令。

## 留待改造的部分与已发现的问题

1. **历史运费与选品阈值。** `ozon-ops/src/rules/economics.mjs` 自身将费率标为 E 级二次资料，且默认采购成本为零、佣金假定 17%。本轮没有把它们作为现行 Ozon 费率或通用经营规则使用。实际物流、品类佣金、币种及汇率需按店铺模式独立核验。
2. **写请求的禁重试承诺。** `kjds/ops-core/src/actions.mjs` 调用 `request(..., {maxRetries:0})`，但 `http.mjs` 的单次请求参数不接收该字段，仍用客户端重试次数。该写执行链暂不接入；需先修复重试控制，再验收并发领取、限额和未知回执，才能支持写操作。
3. **广告 CSV 的币种和缺失数值。** `ozon-ops/src/ads/decide.mjs` 在 `spendCurrency=CNY` 时仍将 revenue 除以汇率，并把多种缺失数值转为零。该 CSV 解析和预算规则暂不直接接入，以免静默改变经营口径。
4. **补货窗口。** 原 `computeRestockPlan` 固定除以 30，而读库函数可传不同 `windowDays`。本轮适配使用显式窗口，并增加稀疏销量与整箱取整检查。
5. **技能库不在 KJDS 仓库内。** 其 README 所述的两个大型技能库是额外构建输入，当前 43 个路径不含这些技能正文。本轮仅吸收检索机制，没有批量拉取、注册或宣称已具备全部技能内容。额外 API 镜像材料的许可也没有假定为 MIT。

## 验证与范围

`python3 -m unittest discover -s commerce/qa -p 'test_*.py' -v`：17 项合成测试通过，包括原有 HTTP/MCP 共享任务、访问校验、模拟隔离、笔记范围与归档，以及新增计算、缺数据、非有限数、币种标记、窗口、稀疏销量、中文查英文和重复词排序。

现有界面布局保持原批准版本，本轮新增能力通过共享服务和 MCP 调用，不增加自动执行器。运行实例及独立 MCP 调用的验证结果见 [source-integration-result.json](qa/source-integration-result.json)：

- 已重新启动经过进程归属核对的本机共享服务，原有任务与简报数量保持一致；真实服务中的两个新增工具均完成合成调用，缺参数返回 HOLD。
- Codex、Hermes、Harness 三种独立 stdio 入口均发现 16 项工具，并完成新增工具调用；新增工具带只读标记。这里验证的是 MCP 协议入口，不等同于重新进行三个宿主应用的原生工具发现；旧会话工具缓存未强制刷新。
- 对固定 KJDS HTTP 模块运行了无网络的模拟夹具：传入 `maxRetries:0`，首次模拟 500 后仍出现第二次 fetch，复现单次禁重试参数被忽略。该写执行链未采用。

原来的 14 工具验收记录保留为历史快照；本次没有改动 Harness profile、重启 Hermes 网关、导入整个技能库或添加新的可视化界面入口。没有调用真实店铺接口。

## 后续界面接入与证据扩展

上述“仅通过后台/MCP”“未增加界面”的描述是第一批接入的历史范围。后续已新增“运营测算”表单和中英知识搜索，沿用原批准视觉；支持缺项、显式零、比例转换、结果撤销和测算证据导出。

按用户补充要求，新增通用与五平台调研模板、原文/中文栏、既有 Hermes 模型翻译、来源/时间/位置/哈希、校对与数字差异检查以及 CSV＋JSON 导出。本次新增 5 项调研工具，完整工具表以当前后台发现为准。平台模板是本项目采集清单，不是实时全类目上架规则；详情见 [RESEARCH_STANDARD.md](RESEARCH_STANDARD.md)。

新验证独立记录在 `qa/workbench-ui-result.json`、`qa/workbench-harness-result.json`、`qa/translation-smoke.json` 与 `qa/workbench-activation.json`。旧的 17 项与 16 工具验收材料未覆盖。新的后台合成检查共 28 项。未修改共享 Harness profile，也未重启 Hermes 网关；只重启经归属确认的本项目共享服务，保留原有任务与简报。


## Personal Agent OS：首批能力采纳（2026-11-13）

本轮按该项目实际工作树中的 `services/api/commerce_reviews.py`、`commerce_growth.py`、`commerce_quality.py`、`commerce_imports.py` 核对能力，没有把 README 的功能声明直接当成验收结果。原项目保持只读；未迁移账号、运行库、资料、客户端框架或外部依赖。

| 可借鉴能力 | phone-lab 处理 |
| --- | --- |
| 评论去重、样本提示与多语言主题 | 增强既有 `commerce_business_analyze`，保留资料版本、幂等、证据导出和界面入口；实现集中在 `business_workflows/review_analysis.py` |
| 3D 装箱估算 | 独立 `packing_estimate.py`，通过 `commerce_packing_estimate` 提供只读 HTTP/MCP 调用；不新增 UI |
| 数据质量、来源版本和任务恢复 | 当前已有业务 preflight、版本失效和恢复实现，本轮复用，不另建状态源 |
| 批量订单导入、完整工作流画布、分层记忆 | 涉及新的业务契约或已有模块边界，本轮未迁移；原项目的实现不证明当前项目已有这些能力 |

评论分析按同一已选商品范围内的 `origin_ref + record_id` 去重；相同身份内容不同会拒绝并回滚，不静默选择。不同来源同名 ID 不合并，正文相同但 ID 不同也不推定为同一用户。新结果使用 `keyword_topics_v2`；历史草稿和幂等请求保持原结果，不自动重算。保留原五个主题标签并新增安装/材质，英文使用词边界匹配，俄文使用词干提示。缺失评分不参与均分。20条是小样本提示阈值，达到阈值仍不证明代表性、情感判断或经营结论；原文引用上限仍为每主题20条。

装箱参数为箱体**内径 cm**、重量 **kg**，输入格式如下（合成示例）：

```json
{"input":{"container":{"length_cm":10,"width_cm":10,"height_cm":10,"max_weight_kg":5},"items":[{"sku":"SYNTHETIC-A","length_cm":5,"width_cm":5,"height_cm":5,"weight_kg":1,"quantity":8}],"max_boxes":10}}
```

总量最多500件、100种SKU、500箱；`rotation_allowed` 默认 true，`no_stack` 默认 false。禁叠放采取保守语义：单件独占一箱。输出包含每件坐标/朝向、箱重、体积利用率和未装入数量/原因。全部装入也只返回 `ESTIMATED`，部分为 `PARTIAL`，无可行装入为 `NO_FIT`。启发式不保证最少箱数，缓冲材料、抗压、重心及承运商规范须人工复核。相比所查来源，新箱同样先检查单件限重，空余空间以不重叠长方体分割，不沿用来源中漏检新箱限重和扣减高度不一致的实现。

新接口复用本机用户鉴权，不新增外部执行权限、不创建任务或改库存。通过 `test_paos_adoption.py` 与 `test_paos_mcp.py` 验证合成计算和隔离 HTTP/三种 stdio MCP 入口；这不代表三个宿主的原生 UI 已验收或日常运行服务已重载。源码参考的实际文件 SHA-256 保留在本机私有验证目录；无公开来源地址或许可证的声明性推定。

本轮实际结果：上述两个专项测试文件与原业务/共享服务回归共29项 Passed，Python编译与共享UI产物同步检查 Passed；日常服务重载及宿主原生新版本加载 Not Verified。


## Personal Agent OS：第二批能力采纳（2026-11-13）

本轮继续参考 `services/api/commerce_imports.py`、`workflow_contract.py`、`knowledge_service.py` 和 `memory_governance_service.py` 的导入隔离、DAG校验、原文绑定与撤回传播机制。实现保留现有标准库后端和React工作台，不引入原项目的数据库/认证/FlowGram或第二套执行器。实际源码文件SHA保留本机私有验证目录。

### 批量订单导入

`order_imports.py` 提供 `commerce_order_import_preview/get/list/confirm`，确认后的同一份行记录由原 `commerce_orders_list(import_batch_id=..., demo=...)` 读取。预览只保存私有暂存，不写订单行；确认需准确预览哈希与显式确认，SQLite同一事务内按店铺/市场/平台/合成范围及订单+行号去重。未提供行号时以同订单内SKU为行标识；同一订单可有多行，不能把订单号当作唯一订单行。已有行内容冲突会隔离，不覆盖原订单。

支持UTF-8 CSV（可带BOM），最多512KB/2000行；本轮未引入XLSX依赖。列映射必含 `order_id/sku/order_date/quantity/unit_price/currency`，可含 `line_id`。逐行币种必填，不补默认币种、不换汇；当前支持的币种由模块 `CURRENCIES` 固定列出。金额用Decimal字符串。日期为真实日历日期或带时区ISO时间，不推断时区。错误回执只含行号/固定原因，不回显被隔离的原文；未映射列不持久化。批次预览和隔离预览各最多50行，汇总仅计算本批新增行且逐币种独立统计订单数、行数和数量；不代表利润、结算或全店经营概览。导入来源始终为 `operator_csv_import_unverified`，不与平台同步或演示订单混淆。

### 原商品计划画布

`workflow_plan.py` 是原 `ProductWorkspace` 的plan表单投影，使用同一 `form_drafts`、来源哈希和修订号。旧 `goal/steps` 无需迁移即能读取为顺序依赖图；显式保存后，图的edges/positions仍存于原plan。支持最多12步骤、DAG依赖、布局和同商品已有任务关联；任务状态读取Core原账本。跨对象任务、循环、重复/悬空边、非有限或越界位置在服务端拒绝。

画布负责工作计划的编辑与回读，不调度、不执行连线，也不授予模型或经营权限。现有执行器保持独立的授权/回执语义。文本目标编辑器保存时保留存续节点的依赖与位置，避免旧入口静默清空画布；并发冲突保留当前输入。

### 基于已有资料的业务分层记忆

`layered_memory.py` 的L1直接引用 `business_source_versions`，不复制原始资料。L2提案必须绑定同一业务对象/模式的source_id、准确版本/哈希、record_key与实际连续原文引文；保存提案不会成为已确认事实。确认/撤回均要求准确内容哈希、修订和显式确认。人工确认仅表示操作者认可，不代表独立核实，也不使商品规格或经营门禁自动通过。

L3仅对同范围、已确认且有效的L2做确定性摘录，不调用模型或增加新断言。来源升级/过期/不可用、事实撤回或纠正会在读取/检索时令派生内容失效；历史记录仍可审查。纠正先建提案，确认新提案才在同一事务撤回旧事实。检索标明L1/L2/L3，排除未确认和失效的派生内容。列表最多500项、检索最多100命中，保留截断标记；范围仅为既有业务资料，不改变Obsidian原笔记或任何宿主的个人记忆。

第二批UI独立页面为 `workbench/src/order-imports.tsx`、`workflow-canvas.tsx`、`layered-memory.tsx`，复用共享tokens和组件。与固定UI owner发生共享窗口冲突后，本会话只撤回自身入口hunks，保留其模型/手机增量，后续先在私有候选隔离构建和浏览器验证；共享整合与日常加载分别记录，不借其它版本的宿主截图作本轮证据。

第二批已在主集成确认的串行窗口接入日常工作台：店铺管理→订单导入、商品→工作流画布、能力库→业务记忆，均可由模块查找进入。保留手机镜像、模型与宿主执行增量；沿用原订单、商品计划和业务资料，不建立第二份数据源或执行器。

实际验证：64项相关Python/HTTP/stdio MCP回归 Passed；整合产物的61项前端测试、TypeScript及共享构建同步检查 Passed。同一整合产物在隔离临时状态中完成CSV预览/确认/重复导入、计划保存/冲突/草稿保持、L1→L2确认→L3→撤回失效三条闭环，覆盖1440/390浅深色，9图、0个JS异常。日常DSH原生实际打开三个新页面，核对导航、真实空态和已有商品修订后返回运营台；日常仅只读验收，未进行测试写入或模型请求。原生验收前后28张受保护表、5张新增业务表、7份配置与3个受监督服务PID一致，58个源码/产物哈希一致；证据保留本机私有验证目录。本会话未重启后台或其它网关，未修改店铺、发送业务消息。Hermes/Codex原生新页面及原生写流程未验收；不以stdio或隔离浏览器结果代替。
