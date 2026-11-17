# Windows 本地部署

部署范围是电商后台、Web工作台、独立数据库与素材目录。现有后台使用POSIX文件锁，选择WSL2运行；手机驱动、Mac语音、Xcode/iOS及宿主插件需要各自适配，不随后台启动宣称可用。

Windows的实际SSH/WSL/显卡/ComfyUI环境仍须现场核验。以下工具不复制Mac业务库、凭据、模型账号、私有素材或任务计划，也不改Mac服务。

## 准备源码包

在项目根目录执行，输出路径必须不存在：

```sh
python3 scripts/windows/bundle.py --output /path/to/phone-lab-wsl.zip
python3 scripts/windows/probe.py --host windows-ssh-alias --output /path/to/windows-inventory.json
```

打包先检查现有生成资源是否同步，再选择运行源码与资源，记录逐文件SHA256；排除隐藏目录、QA、node_modules、客户端连接文件、业务状态和环境文件。若其它会话正在修改界面，应在独占源码副本中构建并用 `--root` 指向该副本。它是私有测试部署包，不等于整个项目已完成公开发布审查。不要用整个工作目录的ZIP代替它。

将ZIP与 `scripts/windows/` 一起复制到Windows的同一暂存目录，保留打包命令输出的SHA256。

## Windows/WSL前置条件

1. 通过现有密钥SSH登录Windows，先运行 `Probe-Windows.ps1`。SSH连接超时发生在认证前，需先恢复sshd或其网络通路，换密钥不能打开TCP端口。
2. 需要WSL2及Python 3.12+，建议Ubuntu 24.04。用 `wsl --list --verbose` 检查。若尚未安装，可在Windows管理员PowerShell运行 `wsl --install -d Ubuntu-24.04`；系统要求重启或首次用户初始化时由操作者完成，不自动重启Windows或终止已有WSL任务。
3. 在PowerShell执行：

```powershell
.\Deploy-PhoneLab.ps1 -Bundle .\phone-lab-wsl.zip -ExpectedSha256 <打包回执SHA256> -Distribution Ubuntu-24.04 -InstallDependencies -Activate
```

`-InstallDependencies` 安装Python虚拟环境支持、FFmpeg和字体；不升级系统或显卡驱动。安装器在WSL Linux文件系统的 `~/phone-lab-windows/releases/<内容版本>/` 解包，虚拟环境属于该发布；实际状态保存在 `~/phone-lab-windows/state/`。已有不同配置不会被覆盖；先完成单独升级/空闲检查。

启动前先用临时空数据库实际检查HTTP认证、内联工作台、媒体服务目录与SQLite完整性。`-Activate` 仅在这些检查通过后启动Windows自己的新后台。默认监听 `127.0.0.1:38731`；未配置Windows开机自动启动，WSL关闭或电脑重启后的恢复另验。

Windows浏览器通过localhost访问WSL应用；Mac访问使用SSH本地端口转发，不把后台绑定到公网。每个独立安装保留自己的认证凭据；不得直接同步或覆盖在线SQLite文件。

## ComfyUI与素材归属

- 优先复用Windows现有ComfyUI、节点和权重，实际读取 `/system_stats`、`/object_info` 后才选模型与工作流。候选是Qwen Image Edit图片链路、Wan图生视频链路；显存、速度和质量待实机验收。
- WSL2 mirrored网络下可以通过127.0.0.1连接Windows服务；默认NAT不能假设同一localhost。先检测实际连通性，再选择ComfyUI运行位置或受控转发；不为连接而关闭防火墙或直接开放0.0.0.0。
- 主图、实物已有视角、细节、场景分别制作。未知背面、接口、尺寸需要补充实物依据；视频先确认关键帧再生成短镜头，按实际帧数/帧率验收时长。
- ComfyUI必须使用保存输出的节点，原文件留在生成端。已有 `media_providers` 通过 `/view` 下载真实字节，FFmpeg解码核验，之后 `CreativeStudio.register` 将本地文件登记到调用端数据库，保留来源/任务/模型/哈希；数据库保存元数据和文件关联，不直接跨机共享在线库。
- 当前共享ComfyUI适配只绑定一张输入图；多人、多元素独立参考绑定需要后续扩展并验证，不能把单图接口称为多图支持。
- HTTP探测和入队都不等于生图/视频完成。实际图片、动作视频、音轨、字幕、商品一致性与UGC人物表达分别验收；结果保持待审阅。

技术依据：[WSL安装](https://learn.microsoft.com/en-us/windows/wsl/install)、[WSL网络](https://learn.microsoft.com/en-us/windows/wsl/networking)、[ComfyUI路由](https://docs.comfy.org/development/comfyui-server/comms_routes)、[Qwen Image Edit](https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511)、[Wan视频](https://docs.comfy.org/tutorials/video/wan/wan2_2)。
