# Commerce UI · 1.1.2

以用户确认的浅色蓝白电商后台为基准。经营、运营测算、调研采集、全球情报、任务与知识界面共用本库，不为各客户端维护独立的业务界面版本。

## 单一来源与分发

- `tokens.json`：语义颜色、字体、间距、圆角、控件高度和弹窗阴影。
- `status.js`：任务状态的纯描述器；内联时在 `kit.js` 前加载，接入向导同样遵守。
- `kit.js`：`window.CommerceUI` 组件渲染与属性处理，固定版本 `1.1.2`。
- `primitives.css`：同一组基础组件的样式、焦点、禁用、错误、只读及窄屏触控状态；兼容现有的语义 class。
- `build.py`：把库与 tokens 放入既有 `web/app.js`、`style.css` 的标记区块，保留其它业务模块。`python3 commerce/ui/build.py --check` 检查漂移。构建无第三方依赖，不下载组件或连接外部服务。

Harness 和浏览器继续读取同一份内联产物，避免 opaque iframe 下额外脚本请求、宿主路由和重复框架实例的差异。现有运行窗口重新打开电商工作台后会读取最新产物；单个宿主实例的旧工具缓存按其原生机制刷新。

## 组件与状态

| 组件 | 入口 | 约定 |
| --- | --- | --- |
| 图标 | `icon(name)` | 同一组 SVG 路径，轮廓 1.6，无图标字体或远端资产 |
| 按钮 | `button({label, variant, action, attrs})` | primary / secondary / danger / quiet；标签转义；disabled 与键盘 focus |
| 输入、选择与字段 | `input(props)`, `select(props)`, `field(label, control)` | 相同边框、字号、高度；默认、focus、只读、禁用、错误；字段有名称和标签 |
| 标签 | `badge(label, tone)` | blue / gray / success / warning / danger；状态同时使用文字，避免只靠颜色 |
| 卡片 | `card({title, content})` / `.card` | 相同 surface、border 与 radius-card；布局由模块管理 |
| 表格 | `table(headers, rows)` | 相同表头、列作用域、滚动容器和空状态 |
| 页签 | `tabs(items, active)` | 同一导航结构；桌面按目录分组并显示当前组，窄屏保留完整模块选择器，二者调用相同导航方法 |
| 弹窗 | `modal({title, body, actions})` | 标题关联、关闭按钮、统一操作区；工作台负责焦点进入、Tab 限制、Esc 与关闭后恢复 |
| 提示与空状态 | `alert(message, tone)`, `empty(message)` | 消息转义，使用 status / alert；没有数据不能表达为「风险为零」 |

代码例子：

```javascript
const ui = window.CommerceUI;
ui.button({label: '检索', variant: 'primary', attrs: {type: 'submit', disabled: false}});
ui.field('国家', ui.input({name: 'country', value: '', placeholder: '例如 MEX'}));
ui.badge('等待授权', 'warning');
```

标签和属性默认转义；事件属性、外部 URL 属性不会通过组件属性白名单。`card.content`、`modal.body` 和表格 rows 仅接收本地模板产生的 HTML，来源文本必须先 `escape`。兼容旧调用的 `legacyAttributes` 只用于迁移既有模板，新代码直接传属性对象。第三方消息、笔记和新闻内容不能作为 HTML、组件定义或执行指令。

## 视觉与适配规则

默认文字 14px；品牌蓝与语义成功/警告/错误色集中定义。基础控件 38px，窄屏主要表单与按钮至少 44px；状态、图表数据和导航允许使用文档化的小尺寸变体。卡片间距使用 4px 刻度体系，业务布局可按信息层级选用 8/12/16/24/32px。新视觉需求先扩展语义 token 或现有组件变体，不在业务模块新增不明含义的品牌色。

本版支持浅色、深色、跟随系统。默认跟随系统，顶栏「外观」可切换；偏好存于同一个共享后台，页面重新打开或恢复焦点时读取。切换只更新主题变量，保留正在填写的内容，不使用 opaque iframe 中不可用的 localStorage。兼容性按当前安装的 Harness 版本和浏览器测试结果记录；微信、飞书等原生聊天卡片由各渠道适配器复用相同状态名称与业务回执，其客户端本身的外观不受本库控制。

改动组件应检查实际表单提交、弹窗焦点、可见焦点、空/失败/加载状态及 390/768/1024/1440 等受影响尺寸。真实设备、其它浏览器和未测试的宿主版本仍需单独验收。

主题通过 `commerce_ui_get_preferences` 与 `commerce_ui_set_preferences` 共享，作用域为当前本机用户；不改动店铺数据或宿主应用自身的主题设置。浅色和深色的 surface、文字、状态色、图表、地图、遮罩与前景色都在 tokens 中定义。未来组件与 token 版本必须一起更新，构建检查拒绝版本不一致。

深色基调按用户确认采用接近 DSH / Codex 的黑色与中性深灰，页面、卡片、表单和地图使用灰阶层次；蓝色用于主要操作、选中状态及数据标记。成功、警告、错误仍保留各自的语义色。浅色方案不随此项修订改变。

信息工作区的 `web/intel-ui.js` / `intel-ui.css` / `intel-land.txt` 由同一构建同步到 `COMMERCE_INTEL_*` 标记区块；业务交互与图形图层只复用现有组件和语义变量，不单独建立另一套主题。地图点位点击区按当前视口计算，窄屏仍可使用列表选择记录。

ARIA 和 data 属性的布尔值使用明确的 `true` / `false` 字符串；原生 disabled/readonly 等保留 HTML 布尔属性语义。筛选展开与记录视图切换通过相同组件输出可读状态。

状态文案与语义色由 `status.js` 的 `describe()` 提供，通过 `ui.status()` 读取；失败、中断、等待审核和完成分别展示。操作是否允许仍由各领域明确传入能力，不能仅凭标签推断。专业工作区使用单栏全宽，避免混入模拟经营侧栏。

## 模块快速查找与视觉层级

顶部“查找模块”与⌘/Ctrl+K使用同一弹窗，`moduleDirectory(items, query)`按当前导航登记生成结果，不冻结入口数量。`moduleDetails(key)`提供分组、说明及中英文关键词；新入口未补充说明时使用通用描述，不删除或假定其能力已验收。

查找支持NFKC检索归一化、空态、方向键、Home/End和Enter；Escape或关闭返回原触发位置。打开其它业务弹窗时快捷键不会替换当前弹窗；页面表单值继续保留。`button()`可选`description`仍以文本转义，沿用共享按钮及状态样式。

图像参考用于布局与层级讨论，实际界面继续使用HTML/CSS/SVG和已确认语义tokens；生成图不作为业务数据或新的按钮能力来源。筛选采用统一工具条，KPI以中性底色和克制的预警文字呈现，只有明确大于0的待处理量和预警量使用警告色。深色、浅色与跟随系统保持同一布局。


分组导航、依据驱动的下一步、专业页面来源边界及视图接续规则见[工作台导航与任务接续](../WORKSPACE_NAVIGATION.md)。`web/workspace-ui.js` / `.css` 和 `ui/next-actions.js` 经同一构建进入共享产物；新模块沿用统一目录、按钮、状态与跳转方法。
