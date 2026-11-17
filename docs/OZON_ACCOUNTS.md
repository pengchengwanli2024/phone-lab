# Ozon 账号管理：单个活动店铺

`OzonAccounts` 保存多家店铺的私有连接配置，复用现有 `LiveConnections` 作为一个活动连接。后台只同步当前店铺；该增量没有提供多 Ozon 店同时同步、租户权限系统、采购/发货/广告写权限。

## 接入契约

服务初始化时构造 `OzonAccounts(live)`。它不读取外部 env 文件、不发起网络或定时任务；原私有向导的保存必须经过本模块，不能另行覆盖活动配置。

```python
accounts = OzonAccounts(live)
accounts.listing()                         # 安全只读目录
accounts.status(account_id=None)           # 安全只读目录或单账号
accounts.configure(values, expected_revision=None, idempotency_key=None)
accounts.activate(account_id, expected_revision, idempotency_key)
accounts.recover()                         # 明确恢复中断的本地事务
```

`configure`、`activate` 和 `recover` 只供受认证私有 HTTP/服务内部使用，不将凭据接入 MCP。公开工具只暴露 `listing/status`。`configure` 保留旧向导参数格式；不传 registry revision 时在独占锁内归档。新调用建议附当前 revision 与幂等键。`activate` 必须指定准确 account ID、当前 revision、幂等键。

保存/激活返回原 `live.status()` 字段，附加 `accounts`（安全 revision、活动账号 ID、是否重放、原请求结果）；因此旧向导仍可读取原字段。账号目录含不透明 ID、标签、是否活动、connection ID、保存快照数量等，不返回 Client ID 或 API Key。标签由操作者提供，目录不会将其视作已验证卖家身份。

## 保存与切换

- 旧店首次进入模块时不立即修改磁盘。只读目录可显示 legacy 活动店；下次正式保存前先归档旧店完整私有配置，保留原 connection ID。
- 不同 Client ID 建立不同账号，同名标签不合并。新账号从默认配置构建，空 API Key 不能继承上一家的密钥，飞书目标和收件确认也不从上一家继承。再次录入已存账号可复用其自身配置。
- 同 Client ID 轮转密钥保持同一个账号与 connection ID，不删除历史快照；关闭同步/通知并撤回订单、库存和收件确认，要求重新读取和核对授权范围。
- 切换恢复目标账号自己的 connection ID 和快照归属，强制关闭同步/通知、撤回订单/库存口径与收件确认。选中当前活动账号是无切换操作，不额外清除已有审阅。配置/切换本身不同步、不发送消息、不修改店铺。
- 当前同步锁、数据库运行作业或发送中的 outbox 任一忙碌即拒绝变更。未知消息或旧账号队列不重发、不改收件渠道。
- registry 文件锁、进程内配置锁、活动同步锁防止本入口并发覆盖。CAS 过期或幂等键请求体冲突均拒绝；重放旧请求不会把当前活动店偷偷切回。

## 私有文件与恢复

账号目录为私有 state 下 `ozon-accounts/`（0700），`accounts.json` 及事务 intent 使用 0600 原子写入；私有文件和锁路径软链接被拒绝。配置材料仍是本机私有明文文件，应随原 state 一同保护和备份，不进入公开发布附件。

活动配置和账号 registry 是两个文件，因此先写 intent，再更新活动配置，最后准备完整 after-state 并提交 registry。校验/写入错误会回滚；异常中断留下 intent。只读目录遇到 intent 返回 `ozon_accounts_recovery_required`，不自行写回。服务应在确定空闲后明确调用 `recover()`：完整 after-state 已准备时完成该精确提交，否则恢复 before-state；不会因此启动同步或远端动作。损坏 intent 或 registry 失败关闭，不清空重建。

只通过本模块的保存才能保证旧店已归档。旁路直接调用 `live.configure`、手改配置或其它进程绕过该 registry 的行为不在完整事务保证内。接缝 owner 应统一旧 `/v1/connections/save` 与新账号激活路径，并在初始化和恢复后验证只读目录。

## 验证

`commerce/qa/test_ozon_accounts.py` 使用临时真实 Core/LiveConnections，覆盖两个账号、同名不合并、原快照恢复、密钥轮转、禁用/撤回审阅、陈旧 revision、幂等重放、忙碌、验证回滚、写盘故障、两种 intent 恢复、敏感输出、权限与损坏/软链接。未使用真实凭据、env 文件或上游 API。

```sh
python -m unittest commerce/qa/test_ozon_accounts.py commerce/qa/test_live_connections.py commerce/qa/test_store_scopes.py -v
```

此模块通过测试不代表正式店铺已导入、OGL 订单范围已核实、周期同步已启用或并行运营已交付；各自以真实领域回执为准。
