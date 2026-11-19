# 电商用户任务地图

本地图供操作者、助手和验证者定位任务。它只描述入口、原数据负责人、结果及恢复，不授予工具权限、不创建任务、不替代业务状态或工程可写配方。工程修改仍受 `commerce/engineering/features.json` 的独立范围限制。

沿用六组导航和原HTTP/MCP。入口里的 `case_id`、店铺和市场从原记录选择，不按商品/店铺显示名猜测。真实和合成资料分别验证。页面存在、配方登记、结构试运行和诊断成功均不表示经营完成。

## 如何使用与取证

1. 选择下表任务，先核入口、目标及前置资料；界面入口使用原导航，深链接保留准确对象。
2. 从用户入口操作，保存后重新读取；同步核原记录/原任务/原回执，不能只截最终绿色状态。
3. 失败先区分产品缺陷、驱动/检查器漂移、环境失败、资料/授权缺失和外部结果未知。未知先查询原请求，不重发。
4. 证据记录任务ID、准确范围、源码/构建及实际加载版本、宿主版本、数据规模、动作和结果、恢复、已知成本及限制。旧证据按依赖判断是否需复验。
5. 表中脚本是现有验证入口，不是通过声明。每次结果仍以对应版本的私有回执为准；脚本没有覆盖的步骤写Not Run，不缩短任务来制造通过。

## 任务索引

| ID / 用户目标 | 用户入口和前置范围 | 操作与可观察结果 | 原状态负责人 / 恢复 | 验证入口 |
| --- | --- | --- | --- | --- |
| T01 情报进入选品 | 情报→全球情报；主题、地区、时间及来源 | 搜索→正文/译文→原文依据→关联商品研究；保留日期、完整/摘要/失败及引用版本 | `public_web.py`、`intel_articles.py`、`intel_store.py`；失败单源保留、显式补采，不把缓存当新采集 | `commerce/qa/test_public_web.py`、`test_intel_articles.py`、`test_intel_fulltext.py`、`intel_fulltext_checks.mjs` |
| T02 候选成为商品工作项 | 店铺管理→商品与上架→商品候选/商品工作区；准确候选和case | 浏览/筛选→原详情→关联或建立工作项→读回商品身份、图片与原始来源 | `product_catalog.py`、`product_workspace.py`；未保存切换可保留，失败明确重读，不隐式另开竞争读取 | `commerce/qa/test_product_workspace.py`、`test_product_workspace_reads.py`、`product_read_recovery_ui.mjs` |
| T03 比较供应与交付 | 商品工作区→货源/交付；同case、数量、币种、报价有效期 | 对照多报价→缺项→明确选择→产品事实/交付清单；相似货源不等于核实同款 | `product_workspace.py`及原组织资料/报价；版本变化标陈旧，返回准确缺项字段 | `commerce/qa/test_product_workspace.py`、`test_copilot_workspace_gaps.py`、`listing_review_checks.mjs` |
| T04 计算成本与定价 | 店铺管理→成本与定价或商品成本；同case、目标平台/市场、原币费用 | 编辑→计算/情景比较→保存→返回/重读；缺费为未知，估算与实际费用分开 | `product_workspace.py`、原成本情景与表单修订；冲突保留本地输入并核对保存版本 | `commerce/qa/test_product_workspace.py`、`test_cost_scenarios.py`、`react_workspace_regression.mjs` |
| T05 生产商品图片及视频 | 内容→创意工作室，或商品→图片与视频；同商品制作项目、真实事实、参考及权利 | 产品理解→参考拆解→创意/脚本分镜→样片/生产→审阅→交付；图像、UGC与展示视频各核质量 | 原creative/media项目、制作版本、任务与审批；局部重做创建明确版本，已发送未知请求先核原回执 | `commerce/qa/test_product_media.py`、`test_media_video_review.py`、`creative_preflight_ui.mjs`、`media_video_review_ui.mjs` |
| T06 一件Ozon商品到发布审阅 | 店铺管理→商品工作区→上架准备；准确case/platform/store_ref/market | 商品资料和图片→报价/成本/目标规则→店铺差异→冻结审阅包；缺项能回原字段，保存后恢复原步骤 | `listing_workspace.py`、`operating_pipeline.py`、owner-review原版本；改版使旧批准失效，诊断不等于发布 | `commerce/qa/test_listing_workspace.py`、`test_operating_pipeline.py`、`listing_workspace_checks.mjs`、`owner_review_checks.mjs` |
| T07 准确版本发布与回读 | 上架准备→申请与回执；真实资料、负责人签收及用户准确写入批准 | 核冻结快照→单次提交→原申请回执→平台状态回读；更新、价格/库存、下架各有准确动作范围 | 原listing release/submission/action；部分失败逐项记录，UNKNOWN先查询原申请，应用回退不逆改平台结果 | `commerce/qa/test_listing_submissions.py`、`test_listing_submission_mcp.py`、`listing_submission_checks.mjs`、`listing_actions_checks.mjs`；真实写入待用户确认 |
| T08 处理日常经营异常 | 店铺管理→经营与提醒；规范店铺范围/当前来源，原提醒或订单/库存 | 发现→原对象核对→明确处理→原回执→复查；已阅、挂起、草稿、已处理分开 | `listing_workspace.py`、`business_workflows/store.py`及原ops/attention；读取失败清除失效结果，保留范围，逐项部分失败 | `commerce/qa/test_store_scopes.py`、`test_order_support.py`、`test_business_workflows.py`、`store_content_ui.mjs` |
| T09 订单到客服及售后 | 店铺管理→订单与客服；同店铺/市场/订单/行及原来源 | 选中订单→客服上下文→核对→草稿→获授权发送/接管→原回执；退款另行批准 | 原订单/support记录；目标变化拒绝旧草稿外发，未知发送不重试；未接平台发送时保持缺适配 | `commerce/qa/test_order_support.py`、`test_business_workflows.py`、`store_content_ui.mjs`；真实消息/退款未获准不执行 |
| T10 库存、采购及履约 | 店铺管理→库存与补货/订单装箱；SKU、仓库、供应商、订单及包装事实 | 库存核对→补货/采购准备→装箱/报价→出库/运单/跟踪/异常；各步有自己的凭证 | 原inventory/restock/shipping及平台连接器；估算不当发货，采购付款/仓库/承运缺适配明确停下 | `commerce/qa/test_shipping_packing.py`、`test_shipping_rates.py`、`test_shipping_transport.py`、`test_business_workflows.py`、`test_order_fulfillment.py`；隔离回执不是仓库、承运或付款，真实履约及物流各自验收 |
| T11 费用、结算及效果复盘 | 店铺经营资料/成本/报告，素材使用版本；店铺/市场/窗口及归因依据 | 关联订单、费用、退款、物流、广告和结算；核差异→待审改进→新版本；无数据、零、无法归因分开 | 原财务/经营来源与素材版本；不从单次销量变化推断素材因果，缺对账适配不得标完成 | `commerce/qa/test_operating_statistics.py`、`test_operating_pipeline.py`；逐笔对账/效果迭代完整路径仍需专项证据 |
| T12 助手接续同一任务 | 原页面共享助手/任务中心；原thread/run与商品/店铺/市场范围 | 读取证据→补缺/受控组件→审阅→继续原任务；草稿、附件、历史、焦点和读位保持 | 原copilot/任务账本，`copilot-events.js`只观察；断线读取原run，旧响应不进入新对象，取消不重发 | `commerce/qa/test_copilot_transport.py`、`test_copilot_store_scope.py`、`test_copilot_material_upload_mcp.py`、`capability_adoption_ui.mjs` |
| T13 把结果变成可用经验 | 能力与设置→资料与知识/技能；原结果或明确纠错及有效来源 | 经验提案→保留案例评估→审阅→采用→撤回；检查真实任务收益 | 原LayeredMemory/扩展定义/工程经验各分域；过期/撤回停止作为当前依据，结构试运行不等于行为有效 | `commerce/qa/test_paos_round2.py`、`test_extension_runtime.py`、`test_engineering_features.py`；行为对照按R5补验 |
| T14 连接平台与替换宿主 | 能力与设置→连接与授权/模型；平台×店铺×操作×宿主版本 | 明确读写能力/来源新鲜度→读取/授权→原回执→复核；浏览器、opaque iframe、三路MCP与Harness各自记录 | 原platform/storefront/runtime；撤权停止后续派发，Shopify/WooCommerce均保留，移动远程后置 | `commerce/qa/test_platform_connections.py`、`test_platform_integrity.py`、`test_host_recovery_contract.py`、`test_database_recovery.py` |

## 安全运行现有验证

- 先使用项目运行解释器及已有QA fixture的私有临时数据库、随机端口、合成凭据。按脚本定义提供前置条件；不让QA指向日常数据库，也不将生产凭据复制进fixture。
- Python合同入口：`python -m unittest discover -s commerce/qa -p test_copilot_material_upload_mcp.py`。`python`应为本机项目运行环境；导入失败先归因环境，不能当业务复现。
- 工作台：在`commerce/workbench`运行`npm test`及`npm run check`；构建同步用`python3 commerce/ui/build.py --check`。统一构建须先核当前owner和源码哈希，不能替其它会话覆盖候选。
- `capability_adoption_ui.mjs`和`product_read_recovery_ui.mjs`自行创建隔离fixture。按其`COMMERCE_PYTHON`和`QA_OUTPUT_DIR`入口选择本机解释器与私有证据目录；完成后清理自己创建的进程/状态，证据保留。
- Harness原生从当前真实页面开始，先记原会话、输入、主题和在途任务；用已释放窗口核实际加载版本，再按影响走查文件、键盘/弹窗、缺项/回执和恢复。不能用HTTP代理通过替代原生控件验收，不能终止他人后台任务。
- 对真实店铺只读数据，只读取当前任务所需范围。用户尚未批准的店铺写入、外发消息、采购付款、广告、付费制作或负责人签收保持待授权；合成验证不替代经营签收。

## 维护与完成口径

新能力或入口改变时，更新受影响任务的入口、原数据负责人和验证链接；任务地图不保存一份竞争的运行状态。逐任务证据保存在私有验收目录，并标Passed / Failed / Not Run / Blocked及范围，不在本表写永久“已通过”。

T06优先跑通同一Ozon商品的本地待审包；T08先跑一条订单或库存异常，T09–T11分别完成各子流程。其它平台逐项适配，窄屏回归不等于移动运营完成。任务完成需实际结果和必要恢复路径有证据，不能按页面数、工具数、卡片数或测试总数加总成完成率。
