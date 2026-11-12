# 多平台只读连接

「多平台接入」为 TikTok Shop、Amazon、Mercado Libre 与 Temu 提供独立的多店铺配置、明确请求的读取作业和私有证据快照。原有 Ozon 连接继续使用「Ozon与飞书」，其配置和通知开关不迁入本模块。

## 使用

点击「打开私有接入向导」，在本机浏览器填写连接名称、市场、接口区域及已经取得的授权信息。授权值不经过聊天或 MCP，不放入 URL、浏览器存储或源码。编辑时凭据不回显，空白保留已有值；预期版本不符时拒绝覆盖。配置位于私有运行目录，权限限定于当前用户。

保存不调用平台。返回工作台刷新，明确选择店铺、资源和订单创建窗口，再审阅一次读取范围。订单窗口截止于提交前约三分钟，实际起止时间保存在回执中。默认最多三页，可由接口明确指定一至五页；单作业最多24次读取、单响应上限2 MiB，保留时间与响应摘要。规格及仓库展开后每作业最多5000行，规范化记录数组的 UTF-8 JSON 上限4 MiB；超限不会采用部分记录或覆盖旧快照。目录接口公开这两个结果上限。没有自动同步、授权获取或令牌续期。授权过期须在私有向导更新，不能据字段已保存认定权限有效。

| 平台 | 读取实现 | 保留的限制 |
| --- | --- | --- |
| TikTok Shop | 商品搜索、订单搜索，202309 路径；店铺 cipher 与访问令牌分开传递 | 商品数量是接口报告值，尚需核对库存口径；手工签名未完成官方 SDK 向量或真实账号对照 |
| Amazon | Orders 2026-01-01 的订单搜索，FBA Inventory 的库存摘要 | 不请求买家资料扩展；库存只覆盖 FBA；访问令牌由既有授权流程取得，本模块不自动换取或续期 |
| Mercado Libre | 授权身份核对、卖家商品与多条读取、订单搜索 | 返回卖家身份不符即拒绝；商品数量可能只是区间参考值，不作为精确可售库存；超过本轮或偏移上限保留不完整状态 |
| Temu | 指定区域路由的 `bg.order.list.v2.get` 订单列表 | 不接库存和金额；实际区域、店铺类型、应用权限和签名仍需真实授权验收 |

所有表格只保留所选资源的规范化字段，不保存买家姓名、地址、联系方式或消息。响应只留哈希作关联证据，不留原始含买家信息的响应。库存值不跨平台合并，金额不自动折汇，也不自动进入总览、采购计划或对账结论。店铺名称及市场由操作者提供，不能冒充平台独立核实。

## 失败、版本与恢复

只有完整成功读取才更新当前快照。返回总数的平台必须在所有页保持同一总数，累计实体数不能超过该总数；增加、减少或超出均视为不完整，不能把“记录数大于等于总数”当作读取成功。空列表仅在对应接口明确结束且计数一致时成立。分页未全、重页、缺页、结构变化、范围不符、限流和失败均保留旧快照；旧快照仍显示原时间与当前配置是否匹配。新配置使用新的版本，旧作业完成后不能发布到新配置。快照超过30分钟或连接停用时不标为新鲜。

相同幂等键返回原作业，不重复发请求；输入改变而复用键会拒绝。单店铺只允许一个活动作业，最多两个并行读取、八个活动请求。取消只影响本模块的作业，已经发出的读取可能已被平台处理。服务中断后到期的作业保留结果未知，不自动重发；重新读取需明确的新请求。通知与经营写入均不属于本模块。

导出含私有业务字段与读取证据，不包含授权值，不作为公开发布附件。哈希用于检测本机内容变化，不证明业务事实真实。

## 共享接口

`commerce_platform_catalog/list/status` 读取覆盖与接入状态；`sync` 明确提交店铺、资源、配置版本和幂等键；`job/cancel` 查询或停止作业；`snapshot/export` 读取或导出当前版本；`open_setup` 打开本机私有向导。配置保存仅提供同源、受鉴权的本机 HTTP 路由，不注册为 MCP 工具。

源码为 `platform_connections/`，界面规范源为 `web/platform-ui.js` / `.css`；私有向导使用 `web/platform-setup.js` 和同一 UI kit。浏览器与 Harness 仍使用原有三资源内联协议。各真实账号与区域仍须验收，合成结果不能替代授权回执。

## 官方协议依据

实现选择和授权边界依据各平台官方资料核对：

- TikTok Shop：[公共参数](https://partner.tiktokshop.com/docv2/page/common-parameters)、[商品搜索](https://partner.tiktokshop.com/docv2/page/6503081a56e2bb0289dd6d7d)、[订单搜索](https://partner.tiktokshop.com/docv2/page/get-order-list-202309)。[SDK 说明](https://partner.tiktokshop.com/docv2/page/tts-api-sdk-overview)要求按自己的应用及授权范围取得包；本轮未下载需登录的 SDK，签名页面的独立浏览器读取超时，保留未对照状态。
- Amazon：[连接授权](https://developer-docs.amazon/sp-api/docs/connecting-to-the-selling-partner-api)、[当前订单搜索](https://developer-docs.amazon/sp-api/lang-en_us/reference/searchorders)、[FBA 库存摘要](https://developer-docs.amazon/sp-api/lang-de_DE/reference/getinventorysummaries)。
- Mercado Libre：[卖家商品与数量限制](https://developers.mercadolibre.com.ar/en_us/items-and-searches)、[订单搜索](https://developers.mercadolibre.com.ar/es_ar/gestiona-ventas)。
- Temu：[区域端点](https://partner.temu.com/documentation?menu_code=38e79b35d2cb463d85619c1c786dd303&sub_menu_code=8311de2b2d434e4d805e88413ab815d8)、[签名规则](https://partner.temu.com/documentation?menu_code=38e79b35d2cb463d85619c1c786dd303&sub_menu_code=4a821c90d06442a09e061b0d4316fbf3)、[订单列表](https://partner.temu.com/documentation?sub_menu_code=554fd46b45ee49269cbdd6d4008a5dc1)。
