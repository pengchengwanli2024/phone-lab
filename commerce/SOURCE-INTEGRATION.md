# 来源项目的研究与吸收

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
