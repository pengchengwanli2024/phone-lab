# 跨境电商共享后台

一个本机 HTTP 服务和 stdio MCP 适配器供 DeepSeek Harness、Codex 与 Hermes 共用。客户端共享任务 ID 与领域状态，不复制彼此的聊天历史或账户配置。

## 当前能力与边界

- 五平台经营概览、订单和库存界面使用明确标注的合成演示数据。平台标识为 `ozon/tiktok/amazon/mercado/temu`。
- 真实模式未接入或授权时返回空数据与缺失指标。五个平台的真实 API 适配器尚未实现，填写密钥不会自动获得真实经营能力。
- 任务创建具有跨客户端幂等性，支持查询和取消；目前只有 queued/cancelled 状态，没有自动执行器。
- 简报由本地模板生成，可归档为草稿；本版不调用模型生成经营结论。
- 笔记访问仅限显式配置的业务目录，拒绝路径穿越、软链接与超限文件。笔记内容是资料，不是工具执行指令。
- 单位经济与补货计算使用调用者显式提供的成本、费率和销量窗口；缺关键输入返回 HOLD，不自动换汇或内置历史费率。
- 另含实验性的双语资料采集清单、完整性检查/导出，以及通过使用者现有 Hermes 模型配置进行的翻译任务。译文保持待校对状态；完整性检查和哈希不能证明资料真实。翻译请求会将显式选中的文本交给所配置的模型提供方，可能产生费用。
- 当前为单机单用户原型，没有多用户、多租户或按店铺角色的权限管理，不开放公网。

## 配置和启动

在项目根目录执行：

```sh
python3 commerce/runtime.py
python3 commerce/prepare.py
```

`runtime.py` 启动同一个回环服务；`prepare.py` 生成 `commerce/integrations/` 和 `commerce/harness/cordis.patch.yml`。生成文件含本次克隆的绝对路径，必须留在本机；客户端配置应引用相应生成内容。

环境变量：

| 变量 | 用途 |
| --- | --- |
| `COMMERCE_STATE` | 私有状态目录；默认为项目根目录下 `.commerce-state/` |
| `COMMERCE_PORT` | 本机服务端口；默认 `38731`，所有客户端必须一致 |
| `COMMERCE_PYTHON` | Harness 启动后台时使用的 Python 可执行文件 |
| `DSH_PROFILE_PATH` | 可选 Harness desktop profile 目录覆盖 |
| `COMMERCE_HERMES_PROFILE` | 可选独立 Hermes `commerce-bot` profile 目录覆盖 |

若需要业务知识库，在私有状态目录的 `config.json` 中配置 `knowledge_root`，其值为自己选择的业务目录绝对路径。不要提交该文件，不要把整个私人 Vault 作为默认输入。

`install_harness.py` 用于 macOS 上已有 desktop profile 的本地链接安装；先执行 `prepare.py`，停止其他 profile 写入者并检查脚本。安装器会备份 manifest/lock 并检查无关配置未改变；它会修改所选 profile，不是启动后台的必要步骤。

`install_runtime.py` 是可选 macOS launchd 安装器，安装当前用户登录后的常驻服务。机器休眠、断电或退出用户后不保证在线。`agents/configure_profile.py` 需要已有的独立 Hermes profile 和 PyYAML，不启动机器人网关。

## MCP 工具

```text
commerce_status
commerce_dashboard
commerce_orders_list
commerce_products_list
commerce_task_create
commerce_task_list
commerce_task_get
commerce_task_cancel
commerce_report_create
commerce_reports_list
commerce_knowledge_list
commerce_knowledge_read
commerce_knowledge_search
commerce_summary_save
commerce_unit_economics
commerce_restock_plan
commerce_collection_template
commerce_collection_check
commerce_collection_export
commerce_translation_start
commerce_translation_get
```

经营读取支持 `demo/platform/store_id/market`，其中 `demo` 默认 false；订单另支持 `query/status`。任务和简报写入本机账本，要求幂等键。任务排队不代表外部执行。

内部 HTTP 接口为 `POST /v1/invoke`，请求结构是 `{tool, arguments, client}`，由运行时提供本机访问凭据。`client` 仅用于调用记录，不能作为独立授权身份。优先经 stdio 或 Harness 服务端桥接使用，勿把服务凭据写进客户端代码。

## 验证与后续

```sh
python3 -m unittest discover -s commerce/qa -p 'test_*.py' -v
```

测试使用临时状态和合成笔记，覆盖访问校验、真实/演示隔离、并发读取、跨客户端幂等任务、受限归档、运营计算与知识检索。可选浏览器和宿主检查需要相应本机应用；其结果、截图和配置不分发。

下一阶段仍需实现真实平台适配与授权、任务执行/确认/未知回执状态、渠道网关收发和常驻部署验收。角色设计见 [AGENT_TEAM.md](AGENT_TEAM.md)。适配来源、行为差异与许可见 [SOURCE-INTEGRATION.md](SOURCE-INTEGRATION.md) 和 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

## 信息聚合与桌面采集

“全球情报”模块读取八个固定公开来源，其中六个 feed 支持多路采集快照。使用 `commerce_crawler_start/list/get/cancel/retry` 管理独立采集队列；操作入队不代表已完成。正文与中文通过 `commerce_intel_article_*` 明确请求，机器译文保持待校对。限频、失败保留、进程与磁盘保护范围见 [集成说明](../crawlers/integration.md)。

界面源码使用 `web/intel-ui.js/css` 与共享 `ui/kit.js`、`ui/tokens.json`；运行 `python3 commerce/ui/build.py` 后用 `--check` 核对。生成区块不直接修改；此公开副本只打包已选择的 UIKit 与 Intel 模块。
