# 手机控制状态与观察

电脑预览在画面外显示一个小点和短标签；原始截图不叠加文字。只有本工具的控制心跳有效时显示“本任务控制中”，否则显示“只读预览”。这不是所有外部控制工具的全局状态检测器。

Android 本机用静音、低重要性的前台服务通知，在状态栏显示小图标，不申请悬浮窗权限、不遮挡应用正文。控制结束会停止服务；心跳中断后最长 90 秒自行移除。首次安装后须在目标系统上确认通知没有被禁用，状态栏图标是否可见取决于系统设置。

iPhone 本机的 `Automation Running` 来自 XCTest。当前没有找到受支持的隐藏、缩小、移动或自定义替换接口；本工具未移除该系统提示。它不进入 WDA 截图，电脑预览和截图 OCR 可使用干净画面。[Appium 官方限制说明](https://appium.github.io/appium-xcuitest-driver/latest/troubleshooting/)。退出 WDA 的 HTTP session 不等于结束 XCTest，不能据此宣称系统文字已消失。

## 本机使用

依赖 Python 3、ADB、已运行的 WDA；构建 Android 提示组件还需 Android SDK 和 JDK 17 以上。设置 `ANDROID_SDK_ROOT` 和 `JAVA_HOME`，然后执行：

```sh
python3 monitor/build_indicator.py
adb -s "$PHONE_LAB_ANDROID_SERIAL" install -r .local/control-indicator/control-indicator.apk
```

签名密钥、随机签名口令和 APK 只留在 `.local/`。APK 仅供本机实验，非发布包。后续构建复用该本机密钥；若已有旧密钥缺少私有口令文件，构建会拒绝覆盖，可用 `--build-dir .local/control-indicator-fresh` 选择新的私有构建目录。不同签名的 APK 不能直接覆盖安装。

把明确选择的设备配置写入 `.local/control-monitor/config.json`，该目录应为 0700、文件为 0600。字段为 `android_serial` 和 `wda_url`；真实值不能进入源码或公开附件。WDA 地址限私网/回环 IP 的 HTTP 地址。

```sh
python3 monitor/preview.py --config .local/control-monitor/config.json
```

打开终端打印的本机链接；只读预览默认运行 30 分钟，Ctrl-C 可提前结束。

iPhone 在 WDA 不可用时，可加 `--ios-udid <UDID>` 走 devicectl 只读截图；需要本机 Xcode/CoreDevice，且仍不支持点击。UDID 只放在本机命令或私有配置，不写入源码。

将已授权操作包在提示生命周期里：

```sh
python3 monitor/control.py --device android --serial "$PHONE_LAB_ANDROID_SERIAL" -- adb -s "$PHONE_LAB_ANDROID_SERIAL" shell input keyevent KEYCODE_HOME
python3 monitor/control.py --device ios -- python3 your_authorized_ios_task.py
```

也可在 Python 任务中使用 `with Lease("android", explicit_serial): ...` 或 `with Lease("ios"): ...`。这些租约只能协调使用本工具的调用者，不能拦截其他进程直接发出的 ADB/WDA 命令。不得把预览在线状态解释成正在控制，也不得把旧截图当作实时画面。
