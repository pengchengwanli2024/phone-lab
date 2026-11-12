# 两个来源项目的研究与吸收

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
