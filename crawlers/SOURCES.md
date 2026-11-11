# 信息来源与多路抓取验证

日期：2026-11-11。测试在当前电脑运行；实际抓取记录、日志和连接参数均保存在 `.local/crawlers/` 私有目录。本页只记录技术汇总，不含订阅正文、个人资料或连接凭据，也不表示整个项目已完成开源发布检查。

## 已补充的信息来源

| 发布方 | 信息类型和官方入口 | 本轮取得记录 | 路径状态 |
| --- | --- | --- | --- |
| Federal Reserve Board | [美联储官方新闻订阅](https://www.federalreserve.gov/feeds/feeds.htm)；宏观及货币政策发布 | 20 | 标准库、Scrapling、系统 curl 三路一致 |
| European Central Bank | [ECB 官方 press RSS](https://www.ecb.europa.eu/rss/press.html)；欧洲央行发布 | 15 | 使用系统信任库的标准库与原生 curl 两路一致；Scrapling 报证书链错误 |
| US Energy Information Administration | [EIA Today in Energy 订阅入口](https://www.eia.gov/tools/rssfeeds/)；能源背景资料 | 20 | 三路一致 |
| World Trade Organization | [WTO news 官方订阅](https://www.wto.org/english/res_e/webcas_e/rss_e.htm)；贸易政策新闻 | 10 | 三路一致 |

共 65 条订阅元数据。美联储、ECB、EIA 是本次补充；WTO 原来已有读取器，本次纳入新的来源注册表、逐条出处和多路核对。每路最多读取订阅中的前 20 条，数量随发布方更新变化，不能作为完整历史覆盖或文章全文抓取验收。

宏观、能源、贸易新闻可作为调研背景；当前未把它们自动转成店铺影响、平台费率、运费、汇率或生效税则。已有 USGS/GDACS 读取器未在本次改写。美联储、ECB、EIA 的多路成功快照现已接入电商情报界面和共享 MCP；界面刷新仅导入本机最近快照，重新联网采集仍由 CLI 完成。详见 [后续接入与可靠性验证](integration.md)。

ECB 的异常保留为真实失败路径；使用[Truststore 的独立 SSLContext](https://truststore.readthedocs.io/en/latest/) 和系统原生客户端读取成功，全程保留 TLS 验证。没有通过关闭校验隐藏故障。

## 每条结果保留的出处

- 发布方、来源 ID、订阅或网页链接，以及新闻条目的原文链接。
- 原始发布时间；来源未提供时保留未知，不用采集时间代替。
- 实际采集时间、页面/接口记录位置、载荷哈希和记录哈希。
- 具体抓取工具、全部尝试、失败原因及各路线核对状态。

原始记录和来源信息分别保存在 `records[].data` 和 `records[].sources`；商品跨页重复时关联每个实际出现位置。原文和哈希保留在私有结果中，哈希不证明发布方陈述真实，也不等于网页全文已归档。当前没有给新增订阅自动补译。

## 多种方式的实际验证

| 场景 | 实际执行路线 | 结果 |
| --- | --- | --- |
| Quotes 静态网页、公开 API 和 JS 网页 | Scrapy、标准库 JSON 客户端、Crawl4AI、本地 Firecrawl | 四路均取得 10 条，全部字段一致 |
| Books 商品练习页 | Scrapy、Scrapling HTTP、Crawlee Browser | 三路均取得 20 条，商品标识、标题、价格、币种、库存状态一致 |
| 官方 RSS/Atom 订阅 | 标准库、Scrapling、系统 curl | 四个发布方均至少两路取得一致结果，65 条元数据 |

上面前两项为[公开抓取练习站](https://books.toscrape.com/)与[公开练习 API](https://quotes.toscrape.com/api/quotes?page=1)，不是真实店铺。读取路线和发布方分别计数；四种工具访问同一发布方不能作为四个独立事实来源。

## 自动切换与故障控制

使用真实子进程和合成 HTTP 服务验证十二种情况：动态页 HTTP 无记录、HTTP 503、字段缺失、记录截断、后端不可用、单路超时、有效结果发生冲突、仅一路成功、同一工具的两种模式、所有路径失败、空白归一化后的出处关联、总时间预算耗尽。

通过规则是按任务最少记录数和完整字段核对，至少两个不同工具家族得到相同内容。所有配置路线都会尝试；有效结果有差异即返回 `conflict`，仅一路返回 `unverified`。这两种状态及全部失败时不释放最终数据，原始尝试保留供检查。超时未执行的路线也会明确标出。

验证入口：`check_resilience.py`。私有证据：`results/resilience-validation.json`、`results/quotes-multi-route.json`、`results/books-multi-route.json` 和 `results/source-validation.json`，均相对于 `.local/crawlers/`。原先五工具/三组合的安装矩阵仍保留在 `VALIDATION.md`，本页补充多路路由和来源验证，不覆盖旧快照。

当前结论只覆盖已定义的数据结构、配置路线和本轮站点。新网站仍需定义字段和最少覆盖要求；登录、验证码、访问授权、来源改变和外部服务故障会留下明确失败，不能承诺所有网站始终可抓。

## 业务来源扩展

新增 [HMRC 官方活动 Atom](https://www.gov.uk/government/organisations/hm-revenue-customs.atom) 与 [英国交通部官方活动 Atom](https://www.gov.uk/government/organisations/department-for-transport.atom)。两者各取当前 feed 前 20 条，通过标准 HTTP、Scrapling、系统 curl 三路一致性核对；后台提供宏观、能源、贸易、交通物流分类。HMRC 内容混合税务与海关活动，交通部内容是官方发布，不提供实际运价、包裹跟踪或自动生效税率。来源发布时间缺失时保留未知。

真实商品页示例：`examples/adafruit-product.json`。解析页面内 JSON-LD Product/Offer，保留 SKU、标题、原币报价、页面库存声明和商品 URL；每条记录保留采集时间、页面与记录哈希、字段集合对应的定位。多报价/变体歧义、缺币种或库存声明时拒绝通过，禁止将页面零售价当作供应成本。示例只读取公开页面，不登录、加购或下单。

实测 CBP newsroom RSS 返回 403，未加入已验收来源。该失败不能用其它网站的成功替代。新增来源的共同页面解析器不会独立核实发布方陈述。
