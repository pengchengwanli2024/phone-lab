# 多手机画面与本机操作

工作台顶栏的“手机”入口现在导航到独立常驻页面 /phones，而不是弹窗。页面自动发现本机连接的 Android 手机，以及已配对且 CoreDevice 传输通道已连接的 iPhone；历史配对记录不作为在线设备。每台手机一张卡片，卡片显示当前画面、型号和在线状态。点开卡片后可以单独查看；Android 和 iPhone 都可显式开始控制，iPhone 使用 WDA，延迟高于 Android。页面可收藏、固定或作为独立标签页常驻；点“返回工作台”回到 /workspace。

## 使用

1. 打开工作台顶栏的“多手机画面与控制”，或直接打开已登录的 /phones 常驻页面。页面不是弹窗，刷新或切换标签页后仍留在同一页面。
2. 手机墙每 2 秒自动刷新；插入新手机或断开手机后，卡片自动增加、消失，不需要重启工作台。
3. 点任意卡片进入单台详情；点“全部手机”返回手机墙。
4. Android 详情点“开始控制”后，手机状态栏保留本机控制提示；按钮变为“结束控制”。点击画面即点按，拖动即滑动；右侧可发送返回、主页、最近任务、回车、删除、唤醒和英文/数字文字。方向键、回车、退格也可直接操作。
5. 结束控制、返回手机墙、离开页面或 90 秒无操作都会释放这台手机的控制租约。不同手机各自独立，同一台手机仍然只允许一个控制者。
6. iPhone 详情可开始控制：点击画面点按、拖动滑动，右侧返回/主页和文字输入。iPhone 使用 WDA，首次启动较慢，控制期间 iPhone 会显示 Automation Running；只读预览不会被标成“控制中”。

## 实现

- commerce/phone_fleet.py 负责自动发现和聚合：ADB 发现 Android，CoreDevice 的 devicectl 发现已配对 iPhone；最多 12 台。
- 每台 Android 有独立的 commerce/phone_bridge.py 实例、MJPEG/快照管线和控制租约。手机墙默认只拉静态快照；进入某台 Android 详情时才建立该台的实时 MJPEG 流，避免同时拉很多路视频。
- 每台 iPhone 通过本机 devicectl 截图，截图在内存中缩成最长边 900 像素的 JPEG，临时 PNG 立即删除；开始控制时才由 commerce/phone_wda.py 启动已构建的 WDA runner 和 usbmux 8100 转发。WDA 提供点击、滑动、pressButton 主页/返回手势和文字输入，结束控制时删除 WDA 会话；WDA 进程保留供下一次控制使用。
- 控制仍复用 monitor/control.py：文件锁、15 秒心跳和 Android 静音状态栏提示。主配置里的 Android 使用原来的 android 租约键；额外 Android 使用按散列 ID 生成的独立租约键，互不抢占。
- 浏览器只看到形如 a… 或 i… 的散列设备 ID、型号和标签；真实序列号/UDID 不返回、不写日志、不进入界面。
- HTTP 路由：GET /phone/fleet/status、GET /phone/fleet/frame、GET /phone/fleet/stream、POST /phone/fleet/control、POST /phone/fleet/input。全部走现有本机 Cookie/Bearer 鉴权、Host/Origin 检查和 loopback 监听；不注册为 MCP 工具。
- 画面只保存在内存缓存，不录制、不落盘、不写数据库、不写日志。每个设备的实时流只保留最新连接；手机墙快照与详情流使用同一内存帧。
- 单机低延迟 WebCodecs/scrcpy 代码仍保留在 commerce/phone_scrcpy.py 和 workbench/src/phone-panel.tsx，但当前手机墙走快照 + MJPEG，没有把低延迟开关放进多机界面。

## 静态预览预算（2026-11-16）

手机墙快照现在共用`phone_frame_policy.py`：令牌按4次/秒补充（突发最多4次），最多3个截图同时进行，每台最多1个；不足预算时等后续页面请求，按等待先后避免前几台独占。只有画面请求才触发截图，仅发现设备不采图。Android详情的实时MJPEG仍由原桥接负责，此预算不约束其它直接调用ADB/WDA的工具。

截图失败按5、10、20、40、80、120秒退避，成功后重置。成功读入的缓存最多复用15秒，过期返回`phone_frame_unavailable`（HTTP 503），原状态会显示画面延迟；保留最后成功时间，不把旧画面冒充新截图。若系统时钟回拨造成未来时间戳，该缓存也不可复用。首次截图尚未完成时同样可能暂时503，页面后续轮询会重试。

断开、重连或停止会隔离旧截图结果。已启动的只读截图仍等原ADB/CoreDevice超时退出，不以丢弃结果宣称底层进程已停止。调度和回归测试使用合成设备及隔离HTTP。

同日用户授权后的加载已完成：在线备份完整性通过，99张受保护业务表的原有行、配置及其它网关核对一致；52项手机回归通过。实际Harness手机入口打开Chrome、本机手机页刷新/空态、浏览器返回工作台及再次进入通过；真实服务的未鉴权401、异常Origin 403、未知设备画面503及已鉴权状态200已核对。现场ADB无设备，CoreDevice仅历史配对且传输不可用；本轮已修复其误显示在线的问题。用户随后明确暂缓连接手机，因此没有真机截图/控制/多机负载验收，也不把当前0台空态算作这些能力通过。原生其它模块及模型执行不在这次手机入口验收范围。

## 依赖与配置

- .local/control-monitor/config.json：android_serial 和 wda_url；目录 0700、文件 0600。真实值不能进入源码或公开附件。
- ADB（platform-tools）与 ffmpeg。launchd 服务的 PATH 很窄，模块会回退查找 /opt/homebrew/share/android-commandlinetools/platform-tools/adb 和 /opt/homebrew/bin/ffmpeg。
- iPhone 预览需要本机 Xcode/CoreDevice 和 devicectl；控制需要 USB 连接、已配对/信任和私有 ios/.build WDA runner。WDA 由服务按需启动，不在源码中分发。首次启动可能需要数秒到数十秒。
- Android 提示组件 org.phonelab.indicator 必须已安装；缺失时控制会失败关闭，不会无提示操作手机。

## 限制

- iPhone 控制不是 Apple 原生镜像，WDA/XCTest 延迟明显高于 Android，不适合连续拖拽/60fps；控制期间有 Automation Running。当前只验证一台 iPhone，多个 iPhone 共用 8100 端口的并发控制未验收。
- 当前真机验证了 1 台 Android + 1 台 iPhone；另用 Android 35 模拟器作为第二台 Android，实际验证了 3 台同屏、独立桥接、独立租约和控制。尚未在两台物理 Android 上验收。
- 中文文字输入尚未支持；adb input text 只接受 ASCII。双指缩放和多点手势未实现。
- 部分 vivo 系统会吞掉 input tap；当前点击使用零距离 input swipe 兼容。
- 手机墙是快照刷新（约 2.5 秒），不是每台都持续视频；选中 Android 后才有实时 MJPEG。低延迟模式没有进入多机界面。
- 只在本机回环地址验证；未做公网、跨机器或多人并发控制。页面刷新或断电后可能等待最长 90 秒租约自动释放。
- /legacy 旧界面没有该入口；入口位于 React 工作台（/workspace）。

## 2026-11-13 本机验收

- 自动发现 vivo NEX 3 5G（ADB，1080×2256）、Android 35 模拟器（ADB，540×1200）和 iPhone 15 Pro Max（CoreDevice，900×1950 预览）；手机墙同时显示三张卡片。
- /phones 独立常驻页：直接打开 200，顶栏“多手机画面与控制”导航进入，页面不是弹窗；页面内开始/结束控制和租约通过。
- Android 详情：开始/结束控制、主页键、画面点按、控制租约 active/inactive 和控制提示生命周期均实际通过；输入请求返回 200。
- Android 模拟器作为第二台 Android 独立开始/结束控制、主页键和租约文件 android-a04ab…json 通过，未影响物理 Android 的 android 租约。
- iPhone 详情：实际完成开始/结束控制、主页、返回、点按、滑动和文字输入（WDA），租约文件 ios-…json active/inactive；首次启动 WDA 成功，结束控制后会话删除。iPhone 控制延迟高于 Android，属于功能级自动化而不是原生镜像。
- 关闭模拟器后，手机墙在下一轮发现中自动回到 2 台，没有残留卡片。
- 多台 Android 的独立桥接、散列 ID、重名标签消歧和租约键单元测试通过。
- 前端 TypeScript、共享 UI 构建与 --check、80 项前端测试通过；手机/协议/手机墙测试 14 项通过；服务生命周期测试通过。
- 多手机接口不返回真实序列号/UDID；临时截图只在本机私有临时目录，读取后删除。

私有截图和原始记录保留在 .local/ 或私有验收目录，不随源码提交。上述验收不代表 Apple 原生镜像手感、多个 iPhone 并发、其它宿主、Safari、公网或真实经营写操作已通过。
