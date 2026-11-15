# Hermes 原生电商工作台

本适配器只增加 Hermes 侧栏和命令面板入口，读取现有 commerce 服务生成的同一份内联 HTML，通过原 `commerce:call`/`commerce:result` 与草稿 CAS 消息协议调用原后台。不另建业务库、不注册额外模型工具、不自动请求模型或执行经营动作。

## 安装

从项目根目录运行，两个路径参数替换为实际私有位置：

```bash
python3 commerce/hermes/install.py --hermes-home "$HOME/.hermes" --project-root "$PWD"
hermes plugins enable commerce-workbench
```

桌面半边单独安装到该 home 的 `desktop-plugins/commerce-workbench/plugin.js`，后端位于 `plugins/commerce-workbench/dashboard/`。安装器不写其它 profile；后台启用由 Hermes 原生 CLI 管理。桌面一般自动发现；必要时在命令面板运行 `Reload desktop plugins`，然后点击侧栏「电商工作台」或搜索「打开电商工作台」。新插件后端支持运行时首次请求挂载的 Hermes 版本无需重启网关；旧版须单独安排，不得擅自重启现有会话。

## 设计与安全边界

- 视觉复用原已确认的业务界面；外层入口与状态使用 Hermes 原生组件、字体和主题 token，不注入全局样式。
- 服务凭据只在后端从既有私有状态读取，固定访问 `127.0.0.1`；禁用环境 HTTP 代理和重定向。不把 bearer、票据或私有配置放进 HTML、URL、前端存储或日志。
- iframe 不启用 `allow-same-origin`、顶层导航或弹窗；CSP 禁止网络连接，只通过限定消息桥。校验窗口来源、随机 nonce、工具命名空间、对象参数和大小；原业务后端继续执行权限、版本与幂等校验。
- 未发送的对话输入仅保存在插件私有存储中，保持原范围和 CAS 冲突语义，不复制浏览器原草稿。页面卸载不会停止共享后台。
- 手机镜像的直连流和私有授权向导本轮不做嵌入适配，使用页头「在浏览器打开」。不得将页面加载通过宣称为手机控制、真实店铺写操作或原生 A2UI 渲染验收通过。
- 接入不开放公网，不修改原后台 CSP，不重启 commerce/Hermes/其它网关，不公开发布。

## 验证

```bash
hermes --run-module unittest discover -s commerce/hermes/tests -v
node --experimental-vm-modules --test commerce/hermes/tests/bridge.test.mjs
node --check commerce/hermes/desktop/plugin.js
```

单元测试使用隔离配置与合成响应；日常验收另需在真实 Hermes 中打开入口并确认原页面、导航、后台只读结果及未发送输入保留。不得用浏览器截图替代 Hermes 原生证据。

## 撤销

先在 Hermes 的插件设置禁用桌面入口，再执行 `hermes plugins disable commerce-workbench`。确认不再使用后可删除本插件的两个安装目录；保留原 `commerce` MCP、业务服务与 `.commerce-state`。不要用整份旧配置覆盖当前配置。
