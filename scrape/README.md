# 界面采集实验

这些脚本通过 ADB/uiautomator 或 WebDriverAgent 读取所选实验设备的界面，部分会搜索、点击和滑动。界面结构与应用版本变化可能导致失效。源码不包含任何评论、用户信息或采集结果。

Android 脚本要求 `--serial` 或本机 `ANDROID_SERIAL`：

```sh
python3 scrape/collect_douyin.py --serial "$ANDROID_SERIAL" --max 40 --out ./scrape/comments.csv
python3 scrape/douyin_scrape.py --serial "$ANDROID_SERIAL" --keyword 示例 --max 40 --out ./scrape/comments.csv
```

`collect_douyin.py` 读取当前打开的评论面板；`douyin_scrape.py` 会执行关键词搜索和界面导航。只采集自己有权处理的数据，并按平台许可及适用要求使用；不要把脚本可读取等同于数据可公开。

iOS 客户端通过 `WDA_URL` 选择自己的 WDA 地址，默认回环 `http://127.0.0.1:8100`。`tiktok_probe.py` 会输出当前界面元素，避免在私人会话或账户页面运行并公开输出。

CSV、截图及其他采集输出应保留在忽略目录，发布前检查实际文件清单。
