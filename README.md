# ZeroTier Native

在已 Root 的 Android 上运行原生 ZeroTier 守护进程，不占用 `VpnService`。

模块采用 Magisk、KernelSU 和 APatch 的模块格式，面向 ARM64 设备，要求内核支持 TUN/TAP，并提供 `/system/bin/ip`。`zerotier-cli` 通过 Root 管理器的 systemless 挂载加入系统命令；采用 metamodule 架构的 KernelSU 需要启用挂载类 metamodule。

## 安装与入网

1. 在 Root 管理器中安装 `dist/zerotier-native-0.1.3-arm64.zip`，然后重启。
2. 打开终端，取得 Root 后使用原生 ZeroTier 命令：

```sh
su
zerotier-cli join NETWORK_ID
```

将 `NETWORK_ID` 替换为 16 位十六进制网络 ID。私有网络还需在控制器中授权该节点。

查看状态或退出网络：

```sh
zerotier-cli status
zerotier-cli listnetworks
zerotier-cli peers
zerotier-cli leave NETWORK_ID
```

命令和参数沿用上游 `zerotier-cli`，例如 `zerotier-cli -j listnetworks`。数据目录由模块自动设置。服务开机自启，通过 Root 管理器启停模块并重启设备。

节点身份、入网记录及 ZeroTier 配置保存在 `/data/adb/zerotier-native/`；日志为其中的 `service.log`。模块升级和卸载会保留这些数据；要彻底移除节点身份，卸载后手动删除该目录。

## 网络行为

ZeroTier 负责创建 TAP 接口、分配地址和维护 `main` 表中的路由。模块监听内核的链路、路由和策略规则事件，将 `zt*` 接口上的路由同步到表 `19993`，使用协议标记 `199` 标识自己的路由。空闲时阻塞等待事件。

IPv4 和 IPv6 各有一条优先级为 `19500` 的 `iif lo` 查表规则，只作用于本机发起的流量；目标不匹配时继续查找系统路由。服务停止时移除自己的规则和路由，保留 ZeroTier 数据。转发和热点共享不在此规则的作用范围内。

该优先级位于 Android 常见的安全 VPN、Lockdown 和显式选网规则之后。VPN 接管的应用仍遵循 VPN 策略；需要同时访问 ZeroTier 时，应在 VPN 中配置相应的应用或网段排除。模块不会把整个 `main` 表提前，也不会修改系统 VPN、`netd`、DNS 或防火墙设置。遇到设备上的防火墙或 SELinux 拒绝时，需按实际日志处理。

## 构建

开发机需要 Python 3、curl 和正在运行的 Docker：

```sh
./build.sh
```

脚本校验并编译 ZeroTier One 1.16.2 的上游源码，关闭 SSO 和非自由控制器组件，生成静态 ARM64 二进制及模块 ZIP。构建缓存位于 `.agent/.codex/build/`，成品位于 `dist/`。下载可使用标准 `HTTP_PROXY`、`HTTPS_PROXY` 环境变量。

运行网络隔离测试需额外安装 ShellCheck：

```sh
tests/run.sh
```

测试容器只增加 `NET_ADMIN` 能力，没有外部网络；测试中的路由修改发生在容器网络空间内。

模块脚本使用 MIT 许可证；ZeroTier 及其依赖的许可证和上游源码地址随安装包附带。
