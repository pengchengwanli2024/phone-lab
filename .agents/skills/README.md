# 项目搜索技能

`open-websearch` 和 `anysearch` 按 `sources.lock.json` 固定来源安装在本项目，供读取项目技能目录的 Agent 使用；没有覆盖个人技能或其它客户端配置。

Open-WebSearch 的实际 npm 运行时在私有 `.local/search/open-websearch`，版本锁定在其 package-lock 中，项目 MCP 接入模板保留于 `commerce/integrations/mcp.json`。以 stdio、request 模式运行，不启动 HTTP 监听，不下载浏览器。现有客户端需要按其正常方式重新加载该项目 MCP 配置才能发现新服务器；注册模板和本机协议验证不代表已替所有宿主连接。

AnySearch 自带 CLI，可用 Python/requests 或 Node；当前按匿名访问验证，不注册账号、不保存密钥。调用方式及当前参数以各包 `SKILL.md` 和 CLI `--help` 为准。常用本机命令：

```sh
.local/crawlers/venv/bin/python .agents/skills/anysearch/scripts/anysearch_cli.py doc
node .local/search/open-websearch/node_modules/open-websearch/build/index.js --help
```

SeaLeap 专业技能库与这些项目 Agent 技能不是同一目录/协议。下载的脚本不会自动获得 Commerce 执行权，不修改原固定来源目录或放宽执行器；工作台自动选择/执行搜索仍需按原受控扩展合同接线与验收。搜索与网页内容作为未核实来源，不能直接升级为商品事实、经营指令或上架批准。第三方 CLI 需要运行依赖；开源源码不包含本机 node_modules、运行状态或凭据。
