# Source adaptations

The global-intelligence land outline (`web/intel-land.txt`, inlined in `web/app.js`) is converted from
Natural Earth `ne_110m_land.geojson` (the `nvkelso/natural-earth-vector` repository).
Natural Earth publishes this data in the public domain:
https://www.naturalearthdata.com/about/terms-of-use/ . Made with Natural Earth.
World Monitor was a product/protocol reference only; none of its AGPL source,
asset catalog or branding is copied into this implementation.

The following MIT-licensed projects informed this implementation. Full license
texts are retained alongside this notice. No account data, credentials, current
marketplace tariffs or storefront assets were imported by those earlier adaptations.

| Source snapshot | Adapted material | Local implementation |
| --- | --- | --- |
| [ozon-ops @ 2121d98d9c34b62dc6580adf93f0e7943e29832e](https://github.com/tiantangcao1980-web/ozon-ops/tree/2121d98d9c34b62dc6580adf93f0e7943e29832e) | Cost decomposition and missing-data states from `src/rules/economics.mjs`, `src/ops/margin.mjs`; stock-cover and pack rounding from `src/ops/restock.mjs` | `operations_analysis.py` and synthetic acceptance tests |
| [kjds @ 806fe6887dceec47501a3d36925ef27cead53eb2](https://github.com/tiantangcao1980-web/kjds/tree/806fe6887dceec47501a3d36925ef27cead53eb2) | CJK query terms, bilingual synonyms, capped occurrences, IDF and concept coverage from `plugin-src/lib/text.js`, `plugin-src/lib/search.js`; priority vocabulary from `ops-core/src/alerts.mjs` | `knowledge_ranking.py` and draft restock priorities |

The adapted Python code changes source behavior: no implicit zero costs or
marketplace fee tables; no fixed 30-day divisor; no early velocity rounding;
missing or unobserved demand does not become a zero purchase recommendation.
Synonym variants are scored as alternatives within a concept, and authorized
note scope remains enforced by the existing service.

## ozon-ops license

MIT License

Copyright (c) 2026 tiantangcao1980-web and ozon-ops contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## kjds license

MIT License

Copyright (c) 2026 KJDS contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

## SeaLeap capability library

The pinned SeaLeap skill catalogue and offline script bridges are indexed from
[sealeap-ecommerce-skills](https://github.com/xjli360/sealeap-ecommerce-skills/tree/914f920b368fd73f867e3d03af7e48b9ab1e18ed)
and [sealeap-amazon-skills](https://github.com/xjli360/sealeap-amazon-skills/tree/1283764556e61cbe56c600bbe504b8731b2254cb).
Copyright (c) 2026 SeaLeap. MIT license texts, source notices and applicable
third-party notices are retained in `sealeap/`. Original repository snapshots
remain private local dependencies. Logos and original third-party course/media
assets are not displayed in the product UI. An optional private offline installation
candidate retains the two pinned repository trees, including their original
licenses, notices and three logo files; these files remain upstream assets and
are not product branding. See `sealeap/README.md` for validation boundaries.


## React 工作台与受控 Surface

`commerce/workbench/package-lock.json` 固定本地构建依赖：React/React DOM（MIT）、CopilotKit 开源组件与 AG-UI 客户端（MIT）、Zod（MIT）、RxJS（Apache-2.0）。运行页面不从 CDN 加载依赖，不使用 CopilotKit Enterprise 的自管智能体功能。打包产物保留上游法律注释；许可证以各固定依赖包为准。

实际进入工作台 bundle 的依赖许可证和 NOTICE 原文保留在 [workbench/licenses/THIRD_PARTY_LICENSES.txt](workbench/licenses/THIRD_PARTY_LICENSES.txt)。其中 `@bufbuild/protobuf` 同时保留 Apache-2.0 及 varint 实现的 BSD-3-Clause 声明；版本以锁文件为准。

`commerce/a2ui/spec/` 保留 A2UI 官方固定版本的四份 JSON Schema、Apache-2.0 许可证与 `provenance.json` 中的来源和哈希。Catalog 与领域实现经当前共享核心整合，独立于现有助手的 0.8 子集。Python 可选校验依赖见 `a2ui/requirements.txt`；未安装时标准计算接口仍可用，动态入口明确失败。
