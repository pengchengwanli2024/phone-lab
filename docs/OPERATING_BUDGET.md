# 本地经营预算核心

## 可执行合同

`operating_budget.OperatingBudget(core)` 只使用现有 `Core.db()/atomic()` 和 `tasks`。它不连接平台、不付款、不授权经营；外部执行器尚未全部接入。所有回执保留 `enforcement`，不能将占用成功解释成外部动作已获准或已完成。

- live / synthetic 各一份版本化累计策略；默认未配置，外部执行始终 false。所有角色、采购/付款/退款/广告/调价共享同一模式总额，不按角色或日期复制或重置。不在源码保存真实额度。
- 原任务 `input.demo` 必须明确为 bool，`input.budget_actions` 是原动作清单：每项 `{id, kind, role, input}`；kind 为 purchase/payment/refund/advertising/repricing，input 为结构化对象。绑定完整任务 input 与动作 input 的规范 JSON SHA256，且任务必须在策略 task_ids 内。已有任务缺此合同先由主控适配，不凭自由文本创建经营身份。
- 策略保存是独立本机管理方法，要求准确旧 revision、稳定幂等键和绑定新策略哈希的 local_operator 声明；这不是手机或人类身份认证。Agent 工具目录不暴露策略保存。不存在自动重置接口，初始化/重启不清历史，调高 cap 不增加经营权限。
- 金额以 CNY 十进制字符串/Decimal/整数元输入，账内整数分；拒绝 bool、float、NaN、负值和超过两位小数。非 CNY 只支持显式已折算的 CNY 上界，需原币金额、币种、上界汇率、含时区观察时刻和依据引用；缺换算拒绝占用。
- `reserve` 在 BEGIN IMMEDIATE 内计算所有任务/角色的累计 gross 实付 + 未释放占用。原任务/动作每模式至多一笔占用，来源变化不能建立另一笔以绕过 UNKNOWN。所有写入幂等键同参返回原完整回执，异参冲突。
- 状态：RESERVED → INTENT → UNKNOWN → PAID；INTENT 也可直接 PAID；只有 RESERVED 可 RELEASED。INTENT 前重新核对策略、原任务当前哈希和取消状态。UNKNOWN 不超时释放、不再派发；本模块没有派发方法。财务结果按原绑定记录，允许任务后来取消/变更，避免丢失已发生支出。
- PAID 是一次终结实付记录；超预留仍如实记录，并锁住该模式后续新占用/意图。退款绑定原 PAID 回执和唯一外部退款记录，累计不得超原实付，退款不恢复累计预算。当前不支持分次实付、无扣款对账释放、自动清除超支锁或周期重置。
- `ledger` 提供一致快照、分页记录与原事件；gross、退款、净额、占用、可用和超限分开。证据引用是接入方声明，本地写入不证明平台支付/退款真实性。

## 接入接口

| 方法 | 必需输入 | 输出/边界 |
| --- | --- | --- |
| `policy_get` | mode | 当前 policy revision、累计 usage、enforcement；读取不初始化额度 |
| `policy_save` | mode, cap_cny, task_ids, expected_revision, idempotency_key, operator_confirmation | 本机管理接口；全部保存均要求声明，扩额与范围变更也如此 |
| `reserve` | mode, binding, amount_cny, expected_policy_revision, idempotency_key | RESERVED 原回执；可选 source_currency / conversion |
| `transition` | mode, reservation_id, binding, event, expected_revision, idempotency_key | 原事件回执；event 为 intent / unknown / paid / release / refund |
| `ledger` | mode | 可选 task_id、offset、limit（1–100），返回当前页记录及这些记录的原事件；usage 始终为整模式共享总额 |

`binding` 精确包含 task_id、action_id、task_input_sha256、action_input_sha256。所有哈希使用模块 `digest(value)`：UTF-8、键排序、无多余空格、非 ASCII 不转义、拒绝 NaN 的 JSON。

intent 另需准确 `expected_policy_revision`；unknown / release 需 `evidence={reason: ...}`；paid / refund 需正数 `amount_cny` 与 `evidence={source, external_id, record_sha256}`。refund 还需原 paid 事件的 receipt_id。证据哈希必须为64位小写十六进制。金额结果字段全部为整数分。

operator_confirmation 精确包含 `{kind: "local_operator", name, confirmed: true, expected_revision, policy_sha256}`；policy_sha256 为 `digest({mode, cap_minor, task_ids: sorted(task_ids)})`。本机声明由管理入口读取操作者明确的准确策略确认后构造；不能从 Agent、来源文本或导入文档构造。没有可信手机身份认证时，应保留原声明措辞。

## 合成调用示例

以下只创建临时 SQLite，不接平台。金额为合成测试额度，不是生产策略。

```python
from pathlib import Path
from tempfile import TemporaryDirectory
from commerce_core import Core
from operating_budget import OperatingBudget, digest

with TemporaryDirectory() as state:
    core = Core(Path(state) / "synthetic.sqlite")
    budget = OperatingBudget(core)
    action = {"id": "SYN-ACTION", "kind": "purchase", "role": "sourcing",
              "input": {"sku": "SYN-SKU", "quantity": 1}}
    data = {"demo": True, "budget_actions": [action]}
    task = core.invoke("commerce_task_create", {
        "kind": "draft", "input": data, "idempotency_key": "SYN-TASK"})
    binding = {"task_id": task["id"], "action_id": action["id"],
               "task_input_sha256": digest(data),
               "action_input_sha256": digest(action["input"])}
    candidate = {"mode": "synthetic", "cap_minor": 1000, "task_ids": [task["id"]]}
    budget.policy_save("synthetic", "10.00", [task["id"]], 0, "SYN-POLICY", {
        "kind": "local_operator", "name": "synthetic-admin", "confirmed": True,
        "expected_revision": 0, "policy_sha256": digest(candidate)})
    reserved = budget.reserve("synthetic", binding, "3.50", 1, "SYN-RESERVE")
    intent = budget.transition("synthetic", reserved["record"]["id"], binding,
        "intent", 1, "SYN-INTENT", expected_policy_revision=1)
    unknown = budget.transition("synthetic", reserved["record"]["id"], binding,
        "unknown", 2, "SYN-UNKNOWN", evidence={"reason": "synthetic lost response"})
    assert unknown["usage"]["held_minor"] == 350
    assert not unknown["enforcement"]["external_execution_authorized"]
```

非 CNY 占用仍传已经折算的 amount_cny，例如 source_currency="USD"，conversion 为 `{original_amount: "1.00", rate_cny_upper: "7.201", observed_at: "2026-01-01T00:00:00+00:00", evidence_ref: "SYN-FX-QUOTE"}`，则 amount_cny 至少为 "7.21"。汇率依据由接入方核验，本模块只校验明确来源、精度和保守上界，不能将字符串引用当成实时行情认证。当前原币金额也限制两位小数。

## 主控接入要点与覆盖边界

1. 服务只需构造 `OperatingBudget(self.core)`、追加 `definitions(schema, string)` 并将这四个工具交给 `invoke`；本轮没有改共享入口或启动服务。policy_save 不在工具定义内，未知工具也会被模块拒绝。管理入口须另核实际操作者与准确策略，不把本机声明称为可信身份认证。
2. 接入方复用原 task ID，把既有准确动作映射到任务输入中的 budget_actions。缺动作合同、缺 demo 或范围不符会拒绝；不要另建任务以绕过同动作占用。一次经济义务使用同一原动作；采购计划与对应付款不能重复当作两笔已发生支出。
3. 派发器必须先核实际经营授权、预算占用与当前输入，再只提交一次 intent。已存在 INTENT / UNKNOWN 先对账；不要把重复调用返回的旧 intent 当成新的派发指令。stable_external_key 是供连接器绑定的一次性外部键建议，不保证平台支持幂等。尚无连接器时 external_execution_authorized 保持 false。
4. 写入方法自带 `core.atomic()`，不能在外层未支持复用的 atomic 中嵌套调用。派发意图与领域状态需要主控明确设计接缝；本模块不宣称跨平台分布式事务、崩溃后恰好一次执行或已保护所有执行器。
5. 已发生财务结果使用原 binding 与当前记录 revision；不因任务取消或来源变化拒绝真实账务。实际金额超过单笔预留会永久保留超支锁；调大 cap 不清锁。低于当前占用的降额允许保存，已占用不消失，新占用与意图拒绝。
6. 本轮不保存真实主库额度、不开启外部经营、不修改模型 chain_budget，也不改变原任务状态。生产策略由主控最终保存。无周期/总额重置、无超支锁解除、无分次实付、无外部无扣款后释放接口；需要这些语义时另做版本化小范围扩展。ledger 的记录分页不截断原事件，长历史接入前应由主控补事件分页/传输上限。

测试使用临时 Core 与合成任务，覆盖跨角色并发、稳定幂等、UNKNOWN、超支、重复退款、降额、输入/任务/模式隔离与精度；它们不证明真实店铺、平台付款、手机身份、MCP 接入或宿主 UI 已验收。私有验证和源哈希由主控从 `.local/agent-team/budget/latest.json` 与 `report.md` 读取。
