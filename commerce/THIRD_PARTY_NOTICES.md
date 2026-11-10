# Source adaptations

The following MIT-licensed projects informed this implementation. Full license
texts are retained alongside this notice. No account data, credentials, current
marketplace tariffs, external skill catalogs or storefront assets were imported.

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
