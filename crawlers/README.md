# 电脑端网页采集工具

独立于手机控制的 Python 采集环境。提供 Scrapy、Crawl4AI、Crawlee、Scrapling 和 Firecrawl 客户端，支持单工具与组合调用。不会修改共享 Harness、Hermes 或 Codex 配置。

## 安装与重现

从项目根目录执行，需要 `uv` 和 Python 3.12：

```sh
python3 crawlers/setup.py
.local/crawlers/venv/bin/python crawlers/benchmark.py --public
```

该默认矩阵验证四个直接运行的工具及其三种组合，共九条路线。Firecrawl 的 Docker 内网与外网模式按后面的专用命令分别验证，避免把容器回环地址误当成宿主机测试页。

安装脚本使用 `requirements.lock` 锁定的版本；仅在缺少锁定文件或显式传入 `--refresh-lock` 时重新解析依赖。虚拟环境、浏览器、缓存、抓取数据和运行记录位于被忽略的 `.local/crawlers/`；不应随源码发布。当前锁定结果见验证报告。更新依赖前保留原锁定文件和结果。

如需复用已配置的本机网络，在进程环境提供代理变量。可选的 `.local/crawlers/network-env.json` 是本机私有环境配置，不要提交或展示内容。浏览器默认使用隔离安装的 Chromium；缺少下载组件时，Crawlee 和 Scrapling 可使用系统 Chrome，Crawl4AI 可使用 Chrome channel。不要使用个人浏览器登录配置。

## 单个工具与组合

多条路线自动切换与结果核对：

```sh
.local/crawlers/venv/bin/python crawlers/collect.py \
  --config crawlers/examples/quotes.json \
  --output .local/crawlers/results/quotes-multi-route.json
.local/crawlers/venv/bin/python crawlers/collect.py \
  --config crawlers/examples/books.json \
  --output .local/crawlers/results/books-multi-route.json
.local/crawlers/venv/bin/python crawlers/check_resilience.py
```

`collect.py` 执行所有配置路线，失败后继续其它路线。至少两个不同工具家族得到完整且一致的记录，才返回 `verified`；只有一路成功返回 `unverified`，有效结果不一致返回 `conflict`，全部失败返回 `failed`。未核对或冲突时不释放最终数据，原始尝试保留在私有目录。同一个工具的 HTTP/浏览器变体计为一个家族，组合路线按调度工具归类。各工具可能共享浏览器或解析组件；结果一致不能代替独立事实核验。

配置可指定每路网址、工具、最少记录数、每路/总超时和分页上限，最多八路；例子分别覆盖公开网页、公开 JSON 接口、JS 渲染及本地服务，以及商品练习页。最少记录数应按任务明确填写，默认值无法证明抓到了来源的全部数据。比较时统一 Unicode 和空白，保留全部业务字段；任何完整候选存在差异都会报告冲突，即使另外两路一致也不自动取多数结果。

结果同时提供 `rows` 和逐条 `records`。每条 `records[].sources` 保留来源链接、发布方、来源 ID、原始发布时间（没有则为空）、实际采集时间、记录位置、载荷/记录哈希以及执行路线。记录只关联实际出现它的页面，跨页重复会保留多个位置。哈希只核对内容变化，原文网页不在当前证据包内完整归档。

```sh
.local/crawlers/venv/bin/python crawlers/worker.py \
  --engine crawl4ai+scrapling \
  --url https://quotes.toscrape.com/js/ \
  --kind quotes --max-pages 2 \
  --output .local/crawlers/results/example.json
```

| engine | 实际分工 |
| --- | --- |
| `scrapy` | Scrapy 请求、队列和分页，Parsel 提取 |
| `crawl4ai` | 浏览器渲染、Markdown 生成，Parsel 提取 |
| `crawlee-http` | Crawlee HTTP 请求和队列，BeautifulSoup 解析页面后提取 |
| `crawlee-browser` | Crawlee Playwright 浏览器与队列，Parsel 提取 |
| `scrapling-http` | Scrapling HTTP Fetcher 与 Selector 提取 |
| `scrapling-browser` | Scrapling StealthySession 浏览器与 Selector 提取；未启用验证码处理 |
| `firecrawl` | Firecrawl 服务获取 HTML/Markdown，客户端提取字段 |
| `scrapy+crawl4ai` | Scrapy 调度；当前页面没有目标记录时调用 Crawl4AI 渲染 |
| `crawl4ai+scrapling` | Crawl4AI 渲染及 Markdown，Scrapling 解析字段 |
| `crawlee+scrapling` | Crawlee 浏览器与队列，Scrapling 解析字段 |
| `json-http` | 使用系统信任库的 HTTPS 客户端读取已定义的公开 JSON 结构 |
| `feed-http` | 使用系统信任库读取 RSS/Atom，保留原始发布时间和原文链接 |
| `feed-scrapling` | Scrapling HTTP 客户端读取相同订阅源 |
| `feed-native` | 系统原生 curl 读取订阅源，保留 TLS 证书校验 |

当前实现四种明确结构：合成商品 `products`、公开练习网站 `quotes`、图书商品练习页 `books` 和 RSS/Atom 元数据 `news`。通用网站需要另外定义字段与选择器；此入口不是任意网站的零配置提取器。每路最多 10 页，网页分页仅跟随同源链接；订阅源每路最多取 20 条元数据。缺失内容、HTTP 错误或浏览器不可用会明确返回失败或阻塞。单个 `scrapy+crawl4ai` 工具的内置回退条件仍是没有目标记录；外层 `collect.py` 还检查字段缺失和最少记录数，并继续其它工具。

## 信息来源

注册表位于 `sources.json`。新增美联储、ECB、EIA，并将已有 WTO 纳入统一来源和逐条证据结构。源的覆盖范围由注册表声明，当前抓取的是订阅标题、发布时间与原文链接，不是文章全文或实时费率。抓取状态在私有运行结果中维护，不把历史成功写成永久在线保证。

```sh
.local/crawlers/venv/bin/python crawlers/sources.py --list
.local/crawlers/venv/bin/python crawlers/sources.py --status
.local/crawlers/venv/bin/python crawlers/sources.py
.local/crawlers/venv/bin/python crawlers/sources.py --source ecb-press
```

每个源使用标准库、Scrapling 和系统 curl 三条路径尝试读取。ECB 在当前电脑的 Scrapling 路线上存在证书链错误，标准库通过 `truststore.SSLContext` 使用操作系统信任库，并与原生 curl 核对；没有关闭证书验证或全局注入 SSL 设置。各来源分别核对，不把不同发布方的不同新闻当成同一事实合并。[来源与本轮验证](SOURCES.md) 列出实测状态和剩余边界。

采集结果会按来源原子写入私有 `published/` 缓存：最近一次尝试与最近成功快照分开保存，失败不会覆盖成功数据，晚返回的旧结果不会覆盖较新的结果。`source-validation.json` 现在是四个来源的汇总索引，单源采集不再丢失其它来源状态；每批原始结果仍保留独立目录。

美联储、ECB、EIA 的成功快照已接入共享工作台/MCP；来源面板的“导入最近快照”仅同步本机采集结果，保留原始采集时间。操作流程与验证见 [接入及可靠性完善](integration.md)。WTO 继续使用已有共享读取器。

## Firecrawl 本地服务

按[官方自托管文档](https://docs.firecrawl.dev/contributing/self-host)使用 `v2.11.162` 的服务配置，默认使用本次解析并固定 SHA-256 摘要的官方发布镜像（`firecrawl-images.json`）；镜像与该源码标签不能视为同一构建。`--source-build` 可改用该标签源码构建，但本次源码构建受容器依赖下载限制。需要可用的 Docker Desktop/Engine；运行以下命令准备、启动：

```sh
.local/crawlers/venv/bin/python crawlers/firecrawl_local.py prepare
.local/crawlers/venv/bin/python crawlers/firecrawl_local.py start
FIRECRAWL_API_URL=http://127.0.0.1:13002 \
FIRECRAWL_FIXTURE_ORIGIN=http://fixture.test:8877 \
  .local/crawlers/venv/bin/python crawlers/benchmark.py --engines firecrawl \
  --cases static dynamic http-error \
  --report .local/crawlers/results/firecrawl-local-validation.json
```

API 仅绑定本机回环地址。数据库随机口令、Compose 与上游源码保存在私有运行目录。合成测试页在 Docker 网络内部提供，无对外发布端口；为访问该测试页，测试部署启用了 `ALLOW_LOCAL_WEBHOOKS`，因此此配置只用于本机验证。部署脚本复用官方服务，移除了可选 FoundationDB，使用 PostgreSQL 队列；未配置模型、付费抓取引擎或店铺凭据。

如果本机网络需要现有代理，公开网页测试使用以下模式。该模式只复用私有网络配置或进程环境中已有的代理，不修改系统代理；代理出口不能解析内部 `fixture.test`，所以内外网测试分开进行：

```sh
.local/crawlers/venv/bin/python crawlers/firecrawl_local.py start --public-proxy
FIRECRAWL_API_URL=http://127.0.0.1:13002 \
  .local/crawlers/venv/bin/python crawlers/benchmark.py --engines firecrawl --public \
  --cases public-static public-dynamic \
  --report .local/crawlers/results/firecrawl-public-validation.json
```

如需重新运行合成测试，再以不带 `--public-proxy` 的 `start` 恢复直接访问模式。服务的浏览器组件直接执行官方镜像中已经构建的 `node dist/api.js`，避免默认 pnpm 入口在启动时临时联网下载包管理器。抓取请求禁用服务端页面缓存，避免把旧结果误当成新抓取。客户端的 `rendered_pages` 对 Firecrawl 为 null，服务内渲染次数没有单独计量。

```sh
.local/crawlers/venv/bin/python crawlers/firecrawl_local.py status
.local/crawlers/venv/bin/python crawlers/firecrawl_local.py stop
```

服务启动、健康检查和真实抓取是不同的检查。客户端安装并不代表服务端已经可用；以 `VALIDATION.md` 中的实际记录为准。

## 验证范围

合成站点包含三页、六种商品、八条原始记录、五个精确文本字段，覆盖中文、日文、俄文、HTML 字符、零价格及零库存。静态与 JavaScript 延迟加载页面使用相同数据；检查完整字段、分页、去重，以及 503 是否被报告为失败。公共网络检查只请求 [Quotes to Scrape](https://quotes.toscrape.com/) 的静态/JS 练习页面，保留正文于私有结果中；报告仅包含计数与质量指标。

耗时是本机单轮观察，包含工具导入、浏览器启动和网络等待，不是吞吐量排行。合成验证和练习网站成功不能证明真实电商网站的覆盖率、登录可用性或长期稳定性。通用网页抓取仍通过 CLI 调用；官方来源快照已能在工作台/MCP 导入，但新来源的网络采集仍需运行本地采集命令。

上游使用说明：[Scrapy](https://docs.scrapy.org/en/latest/intro/install.html)、[Crawl4AI](https://docs.crawl4ai.com/core/installation/)、[Crawlee Python](https://crawlee.dev/python/docs/quick-start)、[Scrapling](https://github.com/D4Vinci/Scrapling)、[Firecrawl Python](https://docs.firecrawl.dev/sdks/python)。

### 工作台与证据

采集任务、业务来源、正文中文与运行保护的接口和边界见 [integration.md](integration.md)。固定来源见 [sources.json](sources.json) 和 [SOURCES.md](SOURCES.md)。真实页面适配示例见 [examples/adafruit-product.json](examples/adafruit-product.json)。所有原始数据、运行日志和截图只在私有目录；不作为项目源码或公开附件分发。
