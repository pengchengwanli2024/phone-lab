# Android 实验工具

需要 ADB、已开启 USB 调试并授权本机的实验设备。部分 vivo 设备还需允许 USB 模拟输入。请自行在手机上完成解锁和授权。

```sh
adb devices -l
SERIAL="$ANDROID_SERIAL" bash android/healthcheck.sh
```

健康检查要求恰好一台在线设备；设置 `SERIAL` 可核对目标。它会读取设备信息、保存截图并发送 HOME 输入，输出在被忽略的 `.healthcheck/` 内。`--strict-input` 要求观察到输入引起的变化。

`ime.sh` 要求 `ANDROID_SERIAL`，可切换已安装的 ADBKeyboard 与部分 vivo 的百度输入法。应用包名因系统而异。

安装脚本显式接收设备序列号和本机包文件，部分会自动确认 vivo 安装对话框，仅应用于自己授权的实验设备：

```sh
bash android/install-apk.sh "$ANDROID_SERIAL" ./application.apk
bash android/install-apkm.sh "$ANDROID_SERIAL" ./application.apkm
```

`install-apk2.sh` 还需要 `timeout`；APK 元数据查询使用 Android build-tools 的 `aapt2`，可能需要按自己的 SDK 位置调整。源码不附带应用包、设备状态或截图。
