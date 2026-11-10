# iOS 实验工具

需要兼容的 macOS/Xcode、已配对并启用开发者模式的自有设备。WebDriverAgent 的编译、签名与开发者证书信任由使用者在本机和手机上完成；本项目不附带签名身份、描述文件或设备标识。

```sh
IOS_UDID="$IPHONE_UDID" bash ios/healthcheck.sh --all
IPHONE_UDID="$IPHONE_UDID" bash ios/iphone.sh apps
```

先将 `IPHONE_UDID` 设置为自己的目标设备。健康检查会打印本机设备/证书信息，输出和截图应保留私有。`iphone.sh` 使用 PATH 上的 `xcrun`，可通过 `XCRUN` 覆盖。

`stage-prereqs.sh` 可下载固定版本的 Appium WebDriverAgent，并尝试通过 Homebrew 安装 libimobiledevice。执行前检查版本与本机工具链兼容性；它会在本机缓存与 Homebrew 目录创建文件。WebDriverAgent 是外部依赖，其源码和构建产物不在本仓库分发。

WDA 客户端默认连接本机转发端口，其他地址通过环境变量指定：

```sh
WDA_URL=http://127.0.0.1:8100 bash ios/wda.sh status
```

点击、滑动与应用启动命令会操作手机；截图默认写入被忽略的 `ios/shots/`。请使用自己的受保护连接，勿公开 WDA 端口。
