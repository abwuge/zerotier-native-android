# 贡献指南

欢迎通过 Issue 报告问题，或提交 Pull Request。

报告问题时，请提供 Android 版本、设备架构、Root 管理器及其版本、复现步骤，以及相关错误输出。服务日志位于 `/data/adb/zerotier-native/service.log`。不要上传 `identity.secret`、`authtoken.secret` 或其他凭据。

## 本地构建与测试

推荐在 ARM64 Linux 或 Apple Silicon macOS 上开发。需要 Python 3、curl、Docker 和 ShellCheck 0.11.0，构建前启动 Docker。

```sh
./build.sh
tests/run.sh
```

构建脚本下载并校验上游源码，生成静态 ARM64 守护进程和模块 ZIP。临时文件与编译缓存位于 `.agent/.codex/build/`，安装包输出到 `dist/`。下载使用标准 `HTTP_PROXY`、`HTTPS_PROXY` 环境变量。

测试直接从生成的 ZIP 解包运行。容器没有外部网络，仅授予 `NET_ADMIN`；路由修改发生在容器的网络命名空间。Linux 容器测试通过后，还应在 Android 上验证安装、重启后的自动启动、原生命令入口和实际通信。

## 代码结构与边界

- `module/`：安装、服务生命周期、Android 路由适配和 `zerotier-cli` 入口。
- `adapter/`：向 Android 网络管理服务注册 ZeroTier 网卡。
- `tools/`：上游构建、许可证收集和模块打包。
- `tests/`：ShellCheck 及隔离网络环境中的集成测试。
- `.github/workflows/`：持续集成和版本发布。

ZeroTier 负责 TAP 接口、地址和 `main` 表中的路由。模块监听内核事件，通过上游 `devicemap` 按安装时选择为已加入的网络使用 `ethzt` 前缀或上游默认命名，并将 ZeroTier 接口上的路由同步到表 `19993`，以协议 `199` 标识自身路由；IPv4 和 IPv6 使用优先级 `19500` 的 `iif lo` 规则，只处理本机发起的流量。

`service.sh` 统一管理守护进程和框架适配进程的启动、停止与异常重启。框架适配进程通过 `NetworkAgent` 将每张已配置的 ZeroTier 网卡注册为以太网。接口地址、MTU 和路由来自系统快照，内核事件触发更新；接口关闭或删除时撤销注册。网络不声明互联网能力，现有默认网络保持不变。

保留系统 VPN 与显式选网规则的优先级。修改路由时确认所有权，停止服务和卸载时仅移除自身状态。节点身份与入网数据保存在模块安装目录之外，升级和卸载应予以保留。

KernelSU 通过其 Root PATH 中已有的工具目录提供命令入口，Magisk 和 APatch 使用 systemless 挂载。保持上游 `zerotier-cli` 的命令和参数，不另设面向用户的管理命令。保持上游 ZeroTier 源码不变，平台适配放在模块内。

README 面向使用者，介绍安装、使用、升级卸载和实际限制。构建、测试、架构及维护流程写在本指南中；开发进度和验证记录不写进用户文档。

## 提交改动

提交前运行与改动相关的检查。说明解决的问题、行为变化和验证方法，将独立改动拆成独立提交。

提交信息采用 `type: description`，例如 `fix: preserve foreign routing rules`。贡献的模块代码沿用 MIT 许可证；上游及第三方代码保留原有许可证。

## 发布版本

维护者先更新 `module/module.prop` 中的 `version` 和递增的 `versionCode`，提交并推送到 `main`。然后创建带发布说明的版本标签：

```sh
version=$(sed -n 's/^version=//p' module/module.prop)
git tag -a "v$version" -m '填写面向用户的版本说明'
git push origin "v$version"
```

CI 会检查标签与模块版本是否一致，在 ARM64 runner 上构建并测试，再使用标签说明创建 GitHub Release 并附上安装包。`main` 分支推送和 Pull Request 执行构建与测试，安装包保存在对应 Actions 运行的 artifacts 中。
