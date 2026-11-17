# 独立后台的资讯机会分析

此流程复用已有 ExtensionRuntime、原任务中心和持久化 interval schedule。它读取当前本机资讯档案，调用一个明确选定的本地兼容模型，再校验原始来源引用。没有第二套队列，不新增新闻采集计划，不发布、采购、付款、投放或发送消息。

## 已有基础和范围

- 主 HTTP 后台由 `local.phone-lab.commerce` LaunchAgent 保活；`server.py` 启动现有采集、autonomy、模型任务和 capability 生命周期。关闭后台网页或宿主客户端不会主动停止该服务。
- 本地用户会话和电脑保持运行是前提。Mac 睡眠、退出登录、关机不等于持续服务；LaunchAgent 也不承诺服务器级 24 小时可用性。
- 已有八个固定公开源：USGS、GDACS、WTO、Fed、ECB、EIA、HMRC、英国交通部。现有公共采集计划可独立运行；是否开启和每源最新失败应读取 `commerce_runtime_status`。`commerce_intel_sources` 的 `schedule:manual` 描述的是该接口自己的手动刷新，不能覆盖真实采集调度状态。
- `commerce_intel_search(scope="archive")` 检索本机已积累、保留期限内的档案，不是全网历史。既有标题、正文、翻译和来源 SHA 仍由原档案维护。
- 已有 Codex CLI、Harness 和 Hermes 路径仍依赖其安装、登录或运行时。此计划应固定选择 `provider=compatible`、`engine=llama_cpp`、loopback URL 的已测试本地模型；不可选自动路由或静默回退到收费上游。模型服务本身须另行确认开机保活，后端保活不等于模型服务已受监督。

## 窄接口

`commerce_intel_opportunity_packet` 输入 `{"limit":8}`，也允许 20。它只读取原资讯库，按来源均衡选取过去 24 小时发布、最近六小时采集且来源缓存有效的条目。默认八条；每标题最多 180 字、URL 最多 600 字、整个包最多 16 KB，有效期一小时。超过上限返回错误，不能截去来源后当完整结果。它不抓取正文或启动模型。

每项保留 ID、来源、原始 URL、发布时间、采集时间和原记录 SHA。源状态描述缓存，不代表最近一次采集尝试一定成功；原采集队列保留独立失败回执。无合格记录时返回空样本和需要新鲜证据，平台热度仍未知。

`commerce_intel_opportunity_validate` 输入 `{"packet":原包,"analysis":模型结果}`。它核对包 SHA、时效、已声明范围、每个当前原记录及引用；模型只能返回摘要、最多三项 `confidence=low/status=needs_evidence` 的假设、原包 evidence_ids 与下一步补证事项。陌生引用、来源变化、高置信、排名、销量、采购字段及伪造的平台热搜均被拒绝。

固定结果范围为 `news_derived_opportunity_hypotheses`，`not_platform_hot_terms=true`，`platform_hot_terms={"status":"unknown","terms":null}`。结构校验不能证明模型理解正确；文字仍是待查假设，不能当作采购、上架或投放授权。

## 导入现有任务引擎

模板在 `commerce/examples/intel-opportunities-daily.json`。它是一个包含两个可分别导入的 extension definition 和 schedule 的容器；整个文件不是单个 extension definition，不要直接把整个容器传给导入接口。

1. 确认两个新窄工具已经由共享 service/MCP 注册，并进入 ExtensionRuntime 的只读 SAFE_BUILTINS。工具的 domain validator 保持启用。
2. 读取模板 `analyst`，把 `spec.model_id` 替换为通过私有设置保存且已测试的本地模型 ID。确认其冻结 route 是 loopback compatible/llama_cpp。将这个 definition 通过原 `commerce_extension_import` 保存，按原结构测试、启用流程处理；结构测试明确不执行推理。
3. 读取 `workflow`，把第二步的 `uses.extension_id` 替换为实际 analyst ID。分别保存、测试并启用该 definition。工作流依次读原包、一次无工具模型分析、重新验证原包；样本为空时后两步跳过，原包保留缺证状态，模型调用次数为零。
4. 将 `schedule.extension_id` 替换为实际 workflow ID，再用原 `commerce_extension_schedule_save` 保存，明确确认版本后用原启用接口启用。文件本身不会启用任何任务。
5. 先以原 schedule_run 接口执行一次有界验收，并从原 run_get/task_get 读取结果。启用后由已有 capability tick 运行，不依赖对话窗口。

默认每 86400 秒一次，最多一个模型调用、八步、120 秒、64 KB 扩展输出；这些是每次计算资源限额，不代表财务预算或外部付款许可。现有 interval schedule 按 UTC epoch 时间槽运行，并非某个本地钟点的每日 Cron；没有补跑所有错过日期的承诺。

计划和模型版本由现有引擎固定。相同槽不会重复派发；原 task_id 和 extension run 负责结果留存。模型已发出但回执不确定时保留 UNKNOWN，恢复不重发同一请求。模型停用、版本变化、来源改变或超时保持可见失败，不能用零热度或完成分析替代。

## 数据缺口

现有公开新闻源不是 Ozon、TikTok、Amazon 或美客多的搜索词排行榜；社交 TOP 是本机策展批次。全平台热搜仍保留 UNKNOWN。资讯 schema 和来源校验不能证明商业判断正确；没有足够线索时应输出空机会列表，不能把“没有机会”凑成一条机会。

`ozon_search_terms.py` 另存本店商品相关搜索词，通过固定 Seller API 的 product-queries 与 details 方法读取当前新鲜库存派生的商品身份。它保留原统计周期、响应 SHA、分页、空值、币种原码和当前店铺范围；不是全市场排名，不跨词相加独立用户，不用 GMV 推算订单。刷新返回持久日任务，排队不等于读取成功；同连接同日复用原任务，失败或未知不自动重发。账户或商品身份改变时拒绝提交旧读取。

后台“情报”的本店搜索词与机会观察读取原记录；打开面板不启动模型。本店词库、公开新闻线索和后续独立需求、竞品、货源、完整成本与试销证据各有口径，最后仍进入同一商品评审流程。

## 验证边界

单次合成本机 API 请求可验证 direct compatible transport；不等于关闭宿主后的持续运行或每日真实内容质量验收。领域专项用临时 Core/Intelligence/ExtensionRuntime 验证来源绑定、原任务幂等、日槽、零样本不调用模型和 UNKNOWN 不重放。主控制器仍需完成共享接缝、完整门禁以及主实例导入/启用的实际回读。其它会话进行中的 UI、构建和 finder 测试状态不由该专项代为验收。
