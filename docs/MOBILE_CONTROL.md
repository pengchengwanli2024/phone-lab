# 手机指挥本地核心 v1

`commerce/mobile_control.py` 提供可复现的本地指挥、准确待审投影和一个安全接续闭环。它复用原 core 数据库、`tasks`、`commerce_task_create`、`commerce_task_continue`、`commerce_task_execute` 和 `commerce_task_result`。没有新增执行器、调度器、金融批准、外发或网络监听。

本模块由主控统一接线到共享 service/MCP/HTTP；源码接线、实际工具调用和正式加载的验收由主控另行记录，本专项不冒领集成已上线。当前没有配置真实飞书应用或 owner，也没有安装、启动或验收真实 SDK 长连接。所有消息与卡片的 `delivery_status` 都是 `not_sent`；函数返回结果不表示手机收到结果。外部交易恒为 `external_operations_executed=false`。

## 指挥收件合同

```json
{"schema":"commerce-mobile-command-v1","intent":"new_task","text":"合成任务资料"}
```

调用 `MobileControl.receive(command, idempotency_key)`。三个字段必须准确存在，未知字段、未知版本、未知意图及空白幂等键均拒绝。文字最长 6000 字；资料原样保存在原任务 input 中，不解析为工具、shell、授权、额度或代码。收件与原任务在同一个 core 事务提交；同键同请求返回原回执，同键异请求冲突。

| intent | 飞书单聊明确前缀 | 本地结果 |
| --- | --- | --- |
| new_task | `/新任务 内容` | 原 analysis 待办，不执行 |
| research_request | `/研究请求 内容` | 原 analysis 待办，不启动研究/模型 |
| feature_suggestion | `/功能建议 内容` | 原 analysis 待办，不修改功能 |
| status | `/状态` | 本机原 tasks 状态计数快照 |
| budget_query | `/预算查询` | root 注入的共享预算只读快照；未接入为 UNKNOWN |
| pause_request | `/暂停请求 原因` | 原暂停请求待办，**不表示已暂停运行** |

没有明确前缀的“好的”、付款或任意自然语言不作为决策。研究请求仅收件；实际研究需原领域明确授权。查询回执有 `recorded_at`，重复消息返回当时的查询快照，新的查询应使用新消息 ID。创建、排队、已批准、运行和真实结果分别表示。

预算通过可选 `budget_reader` 注入原领域只读方法，仅投影 `schema/status/currency/total_limit/remaining/period/source_sha256`。该模块不新建预算、不授予消费。主控已确认的暂定 10000 CNY 需由共享预算模块负责记录；周期未知按累计总上限表达，不能据此推断剩余额度或任何外部动作已获准。

## 准确待审投影

`project(kind, reference)` 重新读取原领域，返回 `commerce-mobile-candidate-v1`：准确对象标识、版本、状态、金额/币种、理由和有效期字段。投影避免输出客户资料、聊天全文和原始业务 payload；暂不能证明的交易金额、币种及有效期保持 null。

| kind | reference | 原合同 |
| --- | --- | --- |
| attention | 原 attention id | `attention.get`；保留 UNKNOWN 等当前状态 |
| followup | 原 followup id | `followups.get`；检查/已阅不等于原业务已完成 |
| order_support | 原绑定订单的 support draft id | 原 business + order_support.decorate；不发送回复 |
| listing | `{case_id,platform,store_ref,market}` | 原 listing preview SHA/revision；不签收、不上架 |

这四类候选 `actionable=false`，没有批准按钮，理由为原领域审阅接续尚未实现。它们不会调用 owner_review、listing submission、付款、客服发送或任意外部动作。未知金额不从价格草稿推算，草稿不标为已回复/已付款。

## 首个本地接续

可信本机集成调用 `FeishuSDKAdapter.prepare_local(original_task_id, complete_parameters)`，可指定 `owner_open_id` 和 1–900 秒有效期。原任务必须来自本模块收件、仍为 queued，且原任务未登记执行。完整参数由原 `unit_economics` 校验，不能夹带操作或工具；首版仅支持这一个计算，缺项拒绝。

卡片绑定原任务全量 SHA、明确动作、参数、owner、私有身份策略版本和有效期。卡片显示原任务、输入版本、零交易金额/CNY、输入售价/原币和理由。零交易金额表示仅本地计算，不表示可以支付。两按钮的 value **仅为各自随机 256-bit nonce**；不包含共享管理密钥、身份声明、原始指令或客户资料。数据库仅存 nonce 摘要。

确认后在同一个 core 事务复核来源/状态/时效/权限，并调用原 `commerce_task_continue` 创建唯一关联后续任务，再调用原 `commerce_task_execute` 登记计算。原任务保留，后续任务的 `predecessor_task_id` 指向原 ID；不把后续任务冒充原任务本体。原 autonomy 执行器负责计算，模块本身从不启动/推动 worker。

拒绝不创建后续任务；另一按钮和重复点击只能读取已定回执。不同 callback 事件、并发点击也不会重复创建接续。重复发起已存在的有效卡片或已有接续被拒绝；不会换 nonce 悄悄扩大同一原任务的批准范围。

`decision_get` 只读原任务执行回执，可见 `pending/expired/blocked/rejected/approved_queued/running/completed/failed/interrupted/cancelled/unknown`。只有原任务实际完成且有计算结果才回传本地结果摘要与完整结果 SHA；金额仍是调用者输入的计算假设，不是结算事实。

在登记 dispatch 意图与原执行登记之间存在清楚保留的事务边界。崩溃或丢回执时，只核对已关联原后续任务的 `task_runs`；没有登记回执则返回 UNKNOWN，**不自动重发**。已存在登记时读同一个回执；source 变化、撤权、超时及 UNKNOWN 不获得新执行权限。源任务与原执行库只通过既有接口变更；数据库文件直接篡改不属于传输身份保证。

## 经营回路建议的决策卡（2026-11-18）

`commerce/operating_loop_mobile.py` 为回路中状态为“等你决定”的工单生成决策卡。卡片绑定工单、建议编号、准确结果哈希、负责人、私有身份策略版本和有效期（最长 900 秒）；两个按钮各带一个随机 nonce，数据库只存摘要。同一工单同一时刻只有一张有效卡。

点击经 `FeishuSDKAdapter.handle_sdk_event` 进入 `MobileControl._decide`：原本地任务卡的 nonce 未命中时，依次询问已登记的 decider，仍未命中才报 `mobile_nonce_invalid`。回路 decider 先把卡片标为处理中，再调用 `OperatingLoop.decide`；后者沿原审阅路径重新校验证据并只登记一次原岗位交接任务。证据已变、桌面已决定、过期、撤权或他人点击都不会改变工单。处理中途崩溃后回执读为 `unknown`，不自动重试。

它不是 MCP 工具；生成卡片不发送任何消息，`delivery_status` 恒为 `not_sent`。真实发送、手机实收和点击回传仍需按下文接入并实测。

## SDK 入口与主控接线

普通 MCP 可接线的仅为 `definitions(schema,string)` 所列四项与 `MobileControl.invoke` 白名单：command、receipt_get、decision_get、project。没有 remote approve、SDK event、prepare_local 工具。不要把对象方法按名字通用导出。

```python
from mobile_control import MobileControl, FeishuSDKAdapter

mobile = MobileControl(service, budget_reader=read_existing_shared_budget)
# 在所有原领域初始化后安装 mobile；由 root 决定是否增加上面的四个工具。
# 策略来自本机私有受控配置，不从消息、MCP 参数或卡片字段接收。
adapter = FeishuSDKAdapter(mobile, read_private_policy, app_id=private_sdk_app_id)
# 仅在该 app 已通过官方 SDK 长连接鉴权的 handler 内使用：
# envelope = json.loads(lark.JSON.marshal(sdk_event))
# receipt = adapter.handle_sdk_event(envelope)
```

`handle_sdk_event` 的返回值是本模块回执，不是 SDK 的卡片回调响应类型。可信 SDK 包装层应在本地保存/查询此回执，消息 handler 返回 None；卡片 handler 转为所选 SDK 的 `P2CardActionTriggerResponse`，仅显示“本地确认已记录/需核对”等 toast，不把排队写成完成。事件注册使用官方 `register_p2_im_message_receive_v1` 与 `register_p2_card_action_trigger`。真正结果消息通过另行验收的 outbox 发送。这里不提供自动 start、凭据加载或 send 入口，防止示例被当作已授权的真实连接命令。

`read_private_policy()` 准确返回四项：`app_id`、`tenant_key`、非空 `owner_allowlist`（open_id 列表）与正整数 `revision`。配置更改必须递增 revision；主控负责用原私有配置生命周期/锁管理读写和撤权，不在本模块接受配置写入。凭据、身份真实值不得进入仓库或日志。

适配器依赖**已认证 SDK 长连接**提供消息来源保证；解析普通 JSON 本身不提供认证。`handle_sdk_event` 不能挂到普通 MCP、通用 HTTP body、群 webhook 或浏览器桥。局部 Python 代码能构造合成事件用于测试，不是可接受的远程认证方法。消息/回调中的 `verified=true`、`actor=owner` 没有授权作用。

每次事件重新检查本机应用、tenant、owner allowlist，核对 header 和 sender/operator 的租户，接收 schema 2.0、单聊 user 文本及 `card.action.trigger`，核对事件时间（过去 300 秒以内、未来最多 60 秒）。毫秒/微秒时间戳归一化；非有限时间拒绝。app/tenant/event_id 去重；app/tenant/message_id 去重并绑定原 owner，同 ID 异资料/身份拒绝。旧事件不因重复投递获得新时效。队列积压超过时效必须创建新请求，不回放陈旧批准。

原 SQLite core 的锁超时尚未针对飞书回调的 3 秒要求做真机压力验收。接入时必须实际验证所选 SDK 版本、消息及卡片帧分发、锁争用、快速回包、断网重连、撤权和跨网点击；不能凭 handler 注册成功宣称生产连接可用。本轮未安装或补丁任何 SDK。

## 首通道与最少配置

选择飞书企业自建应用机器人和官方 SDK 长连接；官方说明长连接在建连时鉴权，支持事件及卡片回传，不需公网回调域名。自定义群 webhook 仅出站，不能承担本方案的身份审批。[长连接事件说明](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-)、[接收回调及 3 秒响应](https://open.feishu.cn/document/event-subscription-guide/callback-subscription/receive-and-handle-callbacks)、[机器人能力差异](https://open.feishu.cn/document/uAjLw4CM/ukTMukTMukTM/reference/im-v1/guide/faq)。

1. 由用户/主控在可用企业账号创建企业自建应用，开启机器人；AppID/AppSecret 保存在私有配置。此模块不创建 app、不修改既有 commerce-bot profile。
2. 初期仅单聊，申请 `im:message.p2p_msg:readonly` 接收入站、`im:message:send_as_bot` 用于后续明确授权的出站。无需群历史、通讯录、付款或店铺权限。权限可见[官方机器人权限说明](https://open.feishu.cn/document/develop-robots/add-bot-to-external-group?lang=zh-CN)。
3. 订阅 `im.message.receive_v1` 和新版 `card.action.trigger`，事件/回调使用长连接；发布应用版本并将 owner 纳入可用范围。为 SDK 独立环境选择并锁定经过实际回调验证的官方版本，原服务不增加依赖。
4. 由可信本机管理员核对 tenant_key 和 owner open_id，写入私有策略及 revision，使用与长连接相同 AppID。不要把显示名/手机号当作审批身份。
5. 按上面内部 handler 接线；手机收到卡片、真实点击和真实结果消息必须分层验收。模块目前只构造候选卡片与回执，不发送任何消息。后续外发需由主控对接已有领域 outbox，记录真实 provider message_id、已发送/已送达/结果未知；不修改此模块去泛化金融批准。

本次核对了[官方 Python SDK 事件结构](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/event/context.py)、[卡片回调结构](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/event/callback/model/p2_card_action_trigger.py)和[长连接实现](https://github.com/larksuite/oapi-sdk-python/blob/v2_main/lark_oapi/ws/client.py)。当前分支对 `MessageType.CARD` 的处理含直接 return，不能由此推断所选新版回调实际帧路径已可用；接入验收需观察准确 SDK 版本和真实 `card.action.trigger`，不可只照示例安装就宣称手机回传成功。

当前缺项：真实 AppID/AppSecret、tenant_key、已核对 owner open_id、企业发布/可用范围、选定 SDK 环境和版本、可信 handler 接线、真实投递回执、手机跨网确认及常开部署。个人微信/WhatsApp 和企微不作为本轮批准通道；未来仍需各自可信身份合同。

## 可复现验证

```sh
.local/crawlers/venv/bin/python -m unittest discover -s commerce/qa -p test_mobile_control.py -v
make verify
```

专项使用临时数据库、合成 SDK 字段和 socket 网络拒绝，不接触日常业务库、不启动 worker 或调度、不发模型和外部消息。端到端测试明确调用原 `autonomy.work` 执行一次本地计算：入站→原任务→卡片→确认/拒绝→关联原后续任务→本地实际结果及回执，合成参数的贡献为 38 CNY。

覆盖重复/冲突消息、改 owner 重投、重启、并发点击、另一按钮重复、随机 nonce、过期、来源变化、撤权、UNKNOWN、dispatch 前后丢回执、原领域只读投影和预算未知。旧失败/漂移回执与最终命令、退出码、代码 SHA 位于私有 `.local/agent-team/mobile/latest.json` 与 `report.md`。`make verify` 范围沿用 [VERIFYING.md](VERIFYING.md)，不代表专项被该入口自动纳入，也不代表手机、真实 SDK、外部交易或原生客户端验收。
