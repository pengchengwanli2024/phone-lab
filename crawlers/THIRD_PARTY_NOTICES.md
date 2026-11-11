# 第三方依赖

本目录的适配器与合成测试页为项目自写代码，通过公开包接口调用下列工具。运行依赖和上游源码仅安装在私有运行目录；本文件不是完整依赖许可审计或开源发布验收。

| 依赖 | 上游与许可证入口 |
| --- | --- |
| Scrapy | [scrapy/scrapy](https://github.com/scrapy/scrapy/blob/master/LICENSE) |
| Crawl4AI | [unclecode/crawl4ai](https://github.com/unclecode/crawl4ai/blob/main/LICENSE)；保留其适用的归属要求 |
| Crawlee Python | [apify/crawlee-python](https://github.com/apify/crawlee-python/blob/master/LICENSE) |
| Scrapling | [D4Vinci/Scrapling](https://github.com/D4Vinci/Scrapling/blob/main/LICENSE) |
| Firecrawl Python SDK / server | [firecrawl/firecrawl](https://github.com/firecrawl/firecrawl)；SDK 与自托管服务端须分别核对许可，服务端按上游 AGPL 条款处理 |
| Playwright | [microsoft/playwright-python](https://github.com/microsoft/playwright-python/blob/main/LICENSE) |
| Truststore | [sethmlarson/truststore](https://github.com/sethmlarson/truststore/blob/main/LICENSE) |

具体运行版本见 `requirements.lock`。浏览器、容器镜像和所有传递依赖须在打包发布前另行核对许可；本次没有将其作为发布附件。

## 本次源码副本范围

已按锁定安装版本的元数据及 LICENSE 文件核对七个直接依赖，许可标识和原许可文件 SHA-256 见 [DEPENDENCY_LICENSES.json](DEPENDENCY_LICENSES.json)。Scrapy/Scrapling 为 BSD-3-Clause；Crawl4AI、Crawlee、Playwright 为 Apache-2.0；Truststore 和 Firecrawl Python SDK 为 MIT。Crawl4AI 的使用归属保留在本表和文档中。

Firecrawl Python SDK 与服务端分别处理：[SDK MIT](https://github.com/firecrawl/firecrawl/blob/main/apps/python-sdk/LICENSE)、[服务端 AGPL-3.0](https://github.com/firecrawl/firecrawl/blob/main/LICENSE)。项目 MIT 声明不替代服务端许可。自托管脚本从上游取得服务端，不将 SDK/容器源码、镜像或浏览器重新打包发布；运营者须按实际分发和运行方式核对上游条款。

本次只同步自写适配器、合成测试和依赖锁定清单，不包含依赖实现、浏览器、容器、抓取正文、商品图片或用户资料。全传递依赖及二进制分发的许可验收未包含在此源码检查中。地图底图坐标来自 [Natural Earth 公有领域数据](https://www.naturalearthdata.com/about/terms-of-use/)，已保留界面归属。
