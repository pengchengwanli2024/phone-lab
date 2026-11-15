# 全球信息工作区

2026-11-14：沿用统一 Commerce UI，默认采用地图与主题多面板仪表盘、可返回的详情阅读，并接入中文标题与既有经营关联模块。

## 工作区与交互

- 默认显示全球地图、分页资讯及贸易／宏观／能源／物流面板；可切换独立列表。外层 AI 助手在本模块默认收起，可随时展开，其它模块的选择独立保留。地图保留缩放、拖动、键盘调整与复位。邻近点位数字只表示记录数量，不代表同一事件、风险评分或已受影响店铺。
- 点击列表或地图记录进入同一区域的详情，返回时保留筛选、页码、滚动位置与原列表、主题标题或地图点位的焦点；Escape 可返回。来源、类别、国家、时间范围和留存范围可筛选，条件可单独移除或整体重置。
- 详情展示原文标题、来源、发布时间、采集时间、原始链接、内容摘要哈希与来源响应哈希；支持收藏、标为未查看、证据 JSON 导出和共享核查任务。
- “采集最新来源”进入既有持久采集队列，显示排队、进度、成功导入、失败及明确重试；请求接受不表示采集完成。来源面板另提供明确标注的“导入已有快照”，不冒充新抓取。失败保留旧数据；后台计划仍在独立运行中心管理。
- “补全中文标题”或详情中的“生成中文标题”明确调用既有翻译模型。优先处理可见主题面板，再补本页列表，去重后最多20条；绑定内容版本、保留原文与模型回执；刷新、查询和读取不会自动调用模型。同版本相同批次复用已有运行中或成功结果，失败需明确重试。机器译文始终待校对。
- 详情可带当前记录及版本进入经营关联；不自动选择商品或配置国家。范围配置、关联凭据与核查待办复用原模块，可返回原情报详情；字段或距离匹配不等于已发生经营影响。
- 保存关注主题后可重复应用条件，显示匹配与未查看数量；最多12项。移除关注条件不删除记录或收藏。当前关注主题是保存检索，不是已经启用的消息推送。

## 正文覆盖与批次

“补齐正文”先按当前筛选预览：已有当前正文、未适配来源、路径未适配和待采集数量分别显示；每次按来源均衡选择最多30条。`commerce_intel_article_plan`只读，`batch_start/get/list/cancel/resume`复用原`intel_articles`证据，批次表只保存选定版本、子记录和进度。成功、失败、来源变化与当前版本可用分别统计；已发出的单条仍遵守45秒边界，取消停止剩余条目。重启后明确恢复，失败可整批或选择单条重试；不重抓已成功项，不自动翻译。响应未确认时可从“正文批次”找回回执。

六类固定发布方保持HTTPS域名和路径约束。ECB来源链接中的双斜杠只在实际请求时规范化，原来源和抓取地址分别保留；HMRC补充官方guidance及内部手册路径。EIA补充当前正文容器，WTO使用声明的字符编码及当前正文容器。完整正文上限为6万字符，超限明确失败，不静默截断；检索与译文边界同步。适配依据包括[HMRC进口指南](https://www.gov.uk/guidance/pay-for-imports-declared-using-the-customs-declaration-service)、[EIA文章页面](https://www.eia.gov/todayinenergy/detail.php?id=68445)、[ECB发布](https://www.ecb.europa.eu/press/key/date/2026/html/ecb.sp261113~3883f1f187.en.html)和[WTO发布](https://www.wto.org/english/news_e/pres26_e/pr998_551_e.htm)。实际失败、网络超时或双路不一致保留回执，不绕过登录或验证码。

## 检索、留存与状态

八个固定公开来源为 USGS、GDACS、WTO、美联储、ECB、EIA、HMRC 与英国交通部门；采集标题与元数据。详情可明确抓取已适配的六类发布方正文、生成中文并追加修订，USGS/GDACS 没有正文适配。附件不在抓取范围。

「当前快照」代表每个来源最近一次成功读取的结果。「本机积累」代表实际在本机采集过的资料；不能检索开始采集之前未取得的历史，也不等于全网或历史全文检索。旧缓存会无损导入本机积累，来源采集替换快照时保留已收集内容。

检索支持多关键词、中英运营/灾害词匹配与重音字符归一化。英文词与国家别名按词边界匹配，`rus` 不匹配 `trust`，`usa` 不匹配 `usage`；中文仍支持词组匹配。ISO3 国家筛选只匹配来源代码，国家名称筛选支持来源国家字段的中文展示名，不从标题推断。自由关键词同时检索原始标题、元数据、已绑定当前来源版本的中文标题，以及最新正文与当前中文修订（无修订时使用原始机器译文）。多关键词可分布在不同字段；命中结果显示限长片段及具体内容哈希。过期来源、失败的新抓取、哈希不一致的正文或译文不参与当前命中，不静默退回旧译文。搜索、收藏和关注计数不启动抓取、翻译或核查任务；已查看与内容核验分别保留。正文和中文版本变化会使相关分页游标过期。没有全文倒排索引、向量、全网或通用语义搜索；仅对本机已取得的内容作确定性扫描，缺少正文的记录仍只查标题与字段。

分页游标绑定条件、页大小与内容快照；数据变化后旧游标失效，界面从第一页重新检索，避免混页。工具默认不带地图点位；可选 `map_layers` 在250项截取前筛选，返回 `map_stats` 的实际数量和截断状态。`include_panels` 从同一份匹配记录投影各主题的数量与三条预览。`bounds` 配合 `link_map=true` 同步筛选资讯和面板，只包含有来源坐标的记录；未开启时，图层和视野只控制地图。联动分页游标同时绑定图层与视野。

已查看状态绑定内容版本，来源内容变化后重新显示为未查看。收藏跟随同一记录。成功采集时清理留存：未收藏且已离开当前快照的资料按最近留存时间保留90天；未收藏记录最多20000项，当前快照与收藏优先保留。每条记录最多保留20个不同内容版本，详情展示当前内容及近期留存的最多5个；任务内的证据快照独立保留，不随资料清理而改写。

哈希用于内容与采集响应的一致性检查，不证明内容真实。已查看与收藏也不代表事实已核实。

## 共用工具

浏览器与 Harness 读取同一份界面产物；Codex、Hermes、Harness 共用相同 MCP/HTTP 领域方法与 SQLite 状态。已有会话可重新加载 MCP 工具表，或用新会话发现新增方法。

| 工具 | 范围 |
| --- | --- |
| `commerce_intel_sources` | 来源覆盖、刷新结果、快照与积累统计 |
| `commerce_intel_refresh` | 手动读取固定 HTTPS 来源，90秒限频 |
| `commerce_intel_search` | 分页查询、图层/视野联动、同一结果集的面板投影 |
| `commerce_intel_dashboard_get` / `update` | 共用图层、时间、区域、语言、面板布局；更新需 `expected_revision`，冲突不会覆盖 |
| `commerce_intel_live_get` / `refresh` | 位置与行情共享快照／有界刷新；读取不访问上游，视野与呼号筛选在600项截取前执行 |
| `commerce_intel_item_get` | 读取单条来源、留存版本与核查任务状态；不自动标为查看 |
| `commerce_intel_item_update` | 收藏或版本绑定的已查看/未查看状态 |
| `commerce_intel_review_create` | 用已展示的内容版本建立共享核查任务；同版本重复调用复用任务 |
| `commerce_intel_watch_save` / `list` / `remove` | 共用关注检索条件和匹配统计 |
| `commerce_intel_reading_start` / `get` | 明确版本的中文标题任务、回执与待校对译文；读取不重发 |
| `commerce_worldmonitor_status` | 官方工具表发现与准备状态，不调用认证数据 |

搜索示例：

```json
{"query":"墨西哥洪水","scope":"archive","view":"all","limit":"20","include_map":false}
```

标记查看或创建核查任务时传入 `item_id` 和已展示的 `record_sha256`。陈旧版本不能被静默替换成未经用户看到的新版本任务。同一内容版本只建立一个核查任务；默认排队。可明确请求本地 `intel_review` 操作，生成冻结证据及待追问事项，结果不代表独立核实或经营执行。请求与中断恢复见 [独立运行](RUNNING.md)。

## 组件与来源

聚合源码在 `web/intel-ui.js`、`web/intel-dashboard-ui.js`、`web/intel-live-ui.js`、`web/intel-ui.css`，地图公有领域几何在 `web/intel-land.txt`。统一构建内联到既有 app.js/style.css，保持原来的三资源宿主路由，不引入 iframe 额外脚本请求或新的框架实例。新布局只使用共享语义变量，浅色、深色与跟随系统保持一致。

本次直接研读 [World Monitor](https://github.com/koala73/worldmonitor/tree/5acbc30fac075f44f00941e801b2237c1c2c2231) 的公开源码，当前交互代码在原项目架构中独立实现，没有引入其运行时、品牌或付费服务。近似地理参考点依据公开坐标整理，并保留对应来源链接；它们不提供实时航运、拥堵或关闭观测。World Monitor 的正式认证数据仍未连接。

| 参考实现 | 已落地机制 |
| --- | --- |
| World Monitor `map-layer-definitions.ts` / `MapContainer.ts` | 单一图层目录，区分发布方事件、来源状态与静态地理参考；统一时间及区域选择 |
| World Monitor `Panel.ts` / `panel-layout-actions.ts` | 稳定面板 ID，保存后更新界面，收起、排序、加宽、隐藏与放大；放大为业务区内阅读视图 |
| World Monitor `mission-presets.ts` | 综合观察、贸易物流、自然事件三个可恢复布局；保留当前检索条件 |
| World Monitor `panel-freshness-display.ts` / `i18n.ts` | 单独展示来源新鲜度、错误、结构化中文和待校对机器译文 |
| [OSIRIS `MapControls.tsx`](https://github.com/simplifaisoul/osiris/blob/master/src/components/MapControls.tsx) | 地图控件与相机状态分离；保留键盘平移、缩放和窄屏操作 |
| [kepler.gl `setFilterUpdater`](https://github.com/keplergl/kepler.gl/blob/master/src/reducers/src/vis-state-updaters.ts) | 一份筛选状态投影地图、资讯与面板；过期响应不能覆盖新选择 |

图层当前包括地震、洪水、风暴与气旋、森林火灾、干旱、火山、海啸和其它灾害，以及航运通道／港口位置两类地理参考。具体类别按来源的字面字段归类，不自行判断预警级别或经营影响。时间可选1／6／24／48小时、7天和快照内全部。

布局和阅读偏好保存于共享 SQLite 的独立 `intel_dashboard_preferences`，本机不同宿主共用，版本冲突需重新操作。默认入口始终为地图仪表盘，独立列表仅为当前会话的明确切换，不保存为默认。

中文优先使用已绑定版本的模型译文；没有译文时，结构化灾害按来源字段整理，国家显示名来自 ECMA-402 `Intl.DisplayNames` 的 Unicode CLDR 数据。未知地名保留原文，不推断来源未给出的国家。可切换来源原文，查询不会自动启动翻译。

## 位置与行情监测

2026-11-14新增地图旁监测区与行情速览；下方保留资讯及四主题面板。压缩顶部工具区域并移除空标题占位，不把列表保存为默认。主题标题可拖动排序，键盘可用面板选项或Alt+左右方向键；布局仍经共享版本校验保存。

- 航空器采用[OpenSky状态向量接口](https://github.com/openskynetwork/opensky-api/blob/master/docs/free/rest.rst)，显示来源位置、呼号、注册国家、气压高度、地速、航迹角及观测时间；不推断航班时刻、航线或目的地。[最新条款](https://opensky-network.org/about/terms-of-use)要求商业机构或持续运营REST API取得书面许可，OAuth不等于许可。默认仅保留已取得的评估快照并暂停刷新；用户确认已有供应商许可后，才设置私有`OPENSKY_LICENSE_CONFIRMED=true`启用。获准后的匿名全球请求按15分钟限频（全球请求4积分，匿名400积分/日），配置OAuth后按2分钟。位置超过30分钟从地图排除；视野与呼号筛选先于600项截取。地面状态不表示停航或异常。
- 航运采用[AISStream服务器端WebSocket](https://aisstream.io/documentation/)。必须提供API Key，未配置时明确显示待配置，不用港口参考点冒充船舶。每分钟至多连接采样18秒，按MMSI保留最近10分钟位置，最多5000条；响应视野截取最多600条。沿海接收站及采样窗口存在覆盖缺口，不等于全球卫星AIS或完整船流统计。macOS优先复用既有HTTPS代理（显式WSS和代理绕过选择保留），无须额外SOCKS依赖。失败按指数退避并加入抖动，保留具体安全错误码；握手成功不当作收到位置，窗口内已有位置后断开会标为部分采样。
- 行情使用World Monitor公开源码中的Yahoo日线与CoinPaprika逐币报价机制，独立适配现有服务；涵盖标普、纳斯达克、恒生、上证、黄金期货、布伦特期货、美元/人民币、BTC和ETH。每5分钟更新，显示发布方观测时间、币种及来源；Yahoo可能延迟，休市价格保留最近时段。涨跌基准分别为上一交易日或24小时，不将月初收盘价当作昨收。日线走势仅在来源实际提供时展示。

快照保存在独立`intel_live_snapshots`。GET只读，不联系上游；刷新由有界后台线程执行、跨客户端共享限频，429延长冷却，失败保留最近成功记录及错误状态。页面可见时才自动请求刷新；编辑字段、拖动或打开图层选择时暂停轮询。资讯时间/主题检索与位置观测采用各自来源语义，位置另外支持当前视野和呼号检索。

凭据仅从运行服务环境或私有`$COMMERCE_STATE/intel-live.json`读取（默认`.commerce-state/intel-live.json`）：

```json
{"AISSTREAM_API_KEY":"","OPENSKY_CLIENT_ID":"","OPENSKY_CLIENT_SECRET":"","OPENSKY_USE_CASE":"local_development","OPENSKY_LICENSE_CONFIRMED":false}
```

不要将真实值写入源码、日志或聊天。按当前需要填写字段；不需要Yahoo/CoinPaprika密钥，凭据文件修改后下次刷新重新读取。AIS客户端复用本机已有`websockets.sync.client`；标准库服务通过stdin密钥管道调用项目已有隔离环境，密钥不进入进程参数。环境缺失时报告客户端不可用，不假装已连接。未接入World Monitor托管认证数据，也未复制其AGPL运行时代码。

用户已明确当前用途为个人本地开发测试。依照[OpenSky官方FAQ对个人、非营利及数据质量评估用途的说明](https://opensky-network.org/about/faq)，私有配置`OPENSKY_USE_CASE=local_development`启用手动测试入口：点击“读取测试样本”或显式调用`refresh(source="flights", evaluation=true)`。不保存为已取得运营许可；常规读取和未启动会话的自动刷新不会发起航班请求，仍遵守同一15分钟/2分钟冷却。可点击“连续测试60分钟”或调用`refresh(source="flights", evaluation_session="start", minutes=60)`开始5–60分钟本地测试；保持页面可见才按冷却读取，`evaluation_session="stop"`停止后续读取（已发出的请求可能完成），到期或服务重启自动结束，重复开始不延长当前会话。来源返回`evaluation_session`和`availability`，明确区分过期、筛选无匹配、从未收到与来源空结果；过期位置详情会关闭。监测面板支持独立放大，返回恢复原布局。未填写密钥的字段保留空字符串，不用看似真实的占位密钥触发外部请求。

陆地轮廓来自 Natural Earth `ne_110m_land.geojson`，按其[公有领域说明](https://www.naturalearthdata.com/about/terms-of-use/)使用。固定源说明：[USGS GeoJSON](https://earthquake.usgs.gov/earthquakes/feed/v1.0/geojson.php)、[GDACS](https://www.gdacs.org/)、[WTO RSS 与署名](https://www.wto.org/english/res_e/webcas_e/rss_e.htm)。

仍待完成：经授权的更多来源与 World Monitor 正式数据、全网/历史全文或向量检索、独立事实核验、状态推送与经营执行。经营关联已有明确范围配置与保守字段/距离线索，仍不判断实际中断或损失。飞书授权继续暂缓；不能把模块入口或公开工具发现称为整个系统已经完成。
