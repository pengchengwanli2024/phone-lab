# 同一业务后台的客户端接入

这些配置是本机单用户MCP stdio入口。各宿主使用同一项目路径、COMMERCE_STATE与COMMERCE_PORT，不各建一份数据库。client参数用于记录调用来源，不是权限或身份验证。

## Codex

使用[配置模板](codex.toml.example)，将项目位置占位符改为本机实际源码位置，并在原有MCP配置中增量加入commerce；保留其它MCP、模型及账号设置。新工具缓存按当前客户端机制刷新，不覆盖整个配置文件。

## Hermes Agent

使用[配置模板](hermes.yaml.example)，合并到独立项目profile的mcp_servers。保留原有模型、渠道和其它项目网关；配置MCP不等于启动手机机器人。项目内助手的模型由服务端私有配置选择，可用Codex CLI或既有Hermes入口，与调用MCP的宿主分开。本机已直接复用Codex登录完成真实推理；未配置私有选择时保留原Hermes路线，依赖不可用会返回接入错误，不自动重试。配置与实际验收版本见[助手说明](../ASSISTANT.md)。

## DeepSeek Harness

复用现有 `commerce/harness/` 插件，其owner-only Connection Fetch与受限iframe读取相同内联产物。安装或更新前核对当前宿主版本与任务归属。原生面板需要后台加载新增工具，但不能通过重启其它会话的服务或网关来代替核对。

## 验证边界

真实stdio MCP验收已覆盖三个client名称读取同一个会话、发送、追问与恢复；这不等于这些宿主所有版本的原生界面兼容。当前安装的Harness0.2.2-rc.1在隔离profile中另有实际原生桥接验收；Codex/Hermes当前原生版本仍需各自复验。支持浏览器面板，不承诺原生聊天自动渲染A2UI。

本地服务继续仅监听回环地址。跨机器、TLS、用户身份或多租户部署是独立接入任务，不直接把本机鉴权令牌暴露公网。
