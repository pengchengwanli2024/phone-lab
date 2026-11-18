# Listing 证据血缘（事实 → 声明 → 字段）

把“证据驱动、可追溯”的 Listing 写法落到本项目：每句文案引用 Claim ID，每个声明引用本品 Fact ID 与 Keyword ID；缺证据的声明不能进入交付字段，证据变化时可按 ID 定位到具体渠道的具体字段做局部修改。

实现是独立模块 [listing_lineage.py](../commerce/listing_lineage.py)，通过共享 HTTP/MCP 暴露三个只读工具，Codex、Hermes、Harness 使用同一接口。没有新增 UI。

## 当前范围

| 方案环节 | 本项目现状 |
| --- | --- |
| 事实锚定（本品档案） | `commerce_listing_lineage_facts_draft` 按 `case_id` 从既有商品证据档案（见 [PRODUCT_EVIDENCE_WORKBENCH.md](PRODUCT_EVIDENCE_WORKBENCH.md)）和商品资料只读整理事实候选，`proof` 一律为空，需人工核对后补齐 |
| 外部情报（竞品、词库、评论） | **未接入卖家精灵（SellerSprite）MCP**。关键词与评论洞察由调用者提供；既有 `commerce_business_analyze`、`commerce_ozon_search_terms_search` 的结果可作为来源。第三方 MCP 可由使用者自行按既有扩展运行时登记为 `mcp_http` 插件，需自备账号并逐项测试启用 |
| 结构化生成与 ID 绑定 | 模板 [listing-lineage-workflow.json](../commerce/examples/listing-lineage-workflow.json) 提供 Generator 与 Critic 两个 agent 定义和一个工作流，运行在既有扩展运行时 |
| 幻觉与合规拦截 | `commerce_listing_lineage_audit` 做确定性引用核对；Critic 补充语义判断，结论仅为建议 |
| 血缘管理与局部更新 | `commerce_listing_lineage_impact` 按 ID 定位受影响字段；`commerce_listing_lineage_export` 输出四张 CSV 文本。**不写入飞书多维表格**，需人工导入并把关联列设为双向关联 |
| 多平台分发 | 同一文档的 `fields` 可含多个渠道（`channel` + `id` 唯一），共用同一声明库；各渠道文案仍需分别生成与审阅 |

## 文档结构

`schema` 为 `commerce-listing-lineage-v1`。`facts`、`claims`、`fields` 必填，`keywords`、`restricted_terms` 可选。未知字段、重复 ID、格式不符的 ID 一律拒绝（`lineage_*` 错误）。

```json
{
  "facts": [{"id": "F-001", "dimension": "材质", "statement": "合成示例：100% 聚酯纤维，克重 180g", "proof": ["合成示例-质检报告编号"]}],
  "keywords": [{"id": "K-004", "term": "wrinkle free", "source": "合成示例词库"}],
  "claims": [{"id": "C-012", "statement": "Wrinkle free drape", "fact_ids": ["F-001"], "keyword_ids": ["K-004"], "insight_refs": ["合成示例-竞品评论主题"]}],
  "fields": [{"id": "Bullet_2", "channel": "Amazon US", "text": "Wrinkle free drape for travel.", "claim_ids": ["C-012"], "keyword_ids": ["K-004"], "version": "v1.2", "max_chars": 500}],
  "restricted_terms": [{"term": "antibacterial", "reason": "合成示例：无检测支撑"}]
}
```

上限：事实 200、关键词 500、声明 300、字段 100、受限词 500。`proof` 是证明文件的名称或编号文本，工具不读取也不校验文件本身。

## 从证据档案生成事实候选

`commerce_listing_lineage_facts_draft({case_id})` 读取同商品的证据档案与商品资料，不保存、不调用模型、不访问外部来源：

- **只有描述本品自身的记录成为事实**：`document` 类来源的 `model`（型号）、`variant`（规格/变体），以及商品资料里 `kind=source_statement` 的原文字段。每条候选带来源 ID、版本、SHA、链接和审阅状态。
- **货源记录不直接成为本品事实**。货源页描述的是某个候选货品，档案本身不能证明它与本品同款（实测中同一商品的货源里就混有英文版、西文版等不同款式）。这些记录列在 `supply_candidates`，附型号/规格文字和 `supplier_item_identity_unconfirmed`。人工确认同款后，把该来源 ID 放进 `supplier_source_ids` 显式点名，才会生成带 `identity_confirmed_by_caller: true` 的事实。
- 排除并说明原因：`review_state=conflict` 的来源、已归档来源、竞品（标签另列为 `insight_candidates`，只能作为声明的 `insight_refs` 线索）、市场/搜索词资料、推断类字段、没有属性字段的来源。
- 所有候选 `proof` 为空，因此引用它们的声明在审核里是 `needs_proof`；核对实物、水洗标或检测报告后补 `proof` 才能通过。源码型号文字是供货方陈述或图文推断，不证明本品实物。
- Fact ID 按读取顺序生成，资料变化后会不同；写入正式文档后请固定 ID。

传 `include_store_keywords: true` 时另附 **关键词候选**：读取当前店铺该 SKU 的真实搜索词快照（既有 `commerce_ozon_search_terms_search` 只读接口），去重并转成 `K-xxx`，各带快照 SHA、期间、query_index 和 unique_search_users。

关键词候选的边界：这是**本店该 SKU 的平台搜索词快照，不是全平台热搜或独立市场需求**；空结果不等于零需求，用户数不能跨词相加。没有店铺 SKU 的商品返回 `no_store_sku` 且不生成候选。

## 审核规则

声明状态（`audit_status`）：

| 状态 | 条件 |
| --- | --- |
| `rejected_no_evidence` | 未引用任何事实，或引用的 Fact ID 不存在。`insight_refs`（竞品评论洞察）不能替代本品事实 |
| `rejected_restricted_term` | 声明文字含调用者提供的受限词 |
| `needs_proof` | 引用的事实存在，但该事实没有登记证明文件 |
| `needs_fix` | 引用了不存在的 Keyword ID |
| `passed` | 以上都不成立 |

字段状态：引用了不存在或未通过的声明、文字含受限词、超过 `max_chars`、引用了不存在的关键词，任一成立即 `blocked`；登记的关键词未在文字中出现或未绑定任何声明为 `warning`；否则 `ready`。

整体 `status` 只有在至少有一个字段、且全部字段无阻断时为 `PASS`，否则 `HOLD`。`coverage` 另列出无证明的事实、未被引用的事实和声明、未埋入的关键词、仅有洞察来源的声明。

受限词与关键词按忽略大小写和空白差异的子串匹配，不做词形变化、同义词或跨语言匹配。

## 边界

- `PASS` 只表示文档内部引用自洽。它不证明事实为真、证明文件有效、声明措辞确实被事实支撑，也不代表平台合规或可以上架。
- 工具不能发现字段文字里未登记为声明的主张；这部分依赖 Critic 和人工审阅。
- 项目未内置任何平台违禁词库（如 FDA/EPA 敏感词、品牌词）；受限词表完全由调用者提供，词表缺漏不会被发现。
- 三个工具均不保存文档。版本与持久化沿用既有草稿流程（如 `commerce_business_draft`、商品工作区）；发布仍走既有的负责人核查与 listing submission，审核通过不替代其中任何一步。
- 影响定位只覆盖文档中登记的引用；未登记引用关系的主图、A+ 图片或其它渠道内容不会出现在结果里。
- 导出的 CSV 含业务资料，属于私有内容，不进入公开仓库。

## 使用工作流模板

模板文件是包含三个定义的容器，不能整体传给导入接口。

1. 分别读取 `generator` 与 `critic`，把 `spec.model_id` 换成已在私有设置中保存并测试过的模型 ID，经 `commerce_extension_import` 保存，再按既有流程测试、启用。
2. 读取 `workflow`，把第一步与第三步的 `uses.extension_id` 换成上一步得到的两个实际 ID，保存、测试、启用。
3. 运行时输入需包含 `facts`、`keywords`、`insights`、`channel`、`language`、`field_specs`、`restricted_terms`，预算需显式允许 2 次模型调用。

工作流把事实、关键词和受限词从运行输入原样传给审核步骤，模型只产出声明与字段，因此不能增改证据。输出含声明、字段、确定性审核结果和 Critic 意见，全部是待人工审阅的本地草稿。

## 验证

专项测试 `commerce/qa/test_listing_lineage.py` 已加入 `make verify` 的完整模式，覆盖：审核与影响定位规则、畸形输入拒绝、CSV 解析与公式单元格转义、隔离 HTTP 服务与三个实际 stdio 客户端的发现/只读注解/调用一致、鉴权边界，以及模板在既有扩展运行时上的完整执行。

模板测试使用模拟模型。真实模型的生成质量、Critic 的判断准确度、卖家精灵或飞书的实际连通、原生宿主界面均未验证。
