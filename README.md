# ZeroTier Native for Android

原生 ZeroTier 模块，开机自动连接。

支持 Magisk、KernelSU 和 APatch，适用于 Android 11 及以上、内核支持 TUN/TAP 的 ARM64 设备。

## 安装

1. 从 [最新 Release](https://github.com/abwuge/zerotier-native-android/releases/latest) 下载模块 ZIP。
2. 安装模块，然后重启手机。
3. 在终端加入网络：

```sh
su
zerotier-cli join NETWORK_ID
```

将 `NETWORK_ID` 替换为 16 位十六进制网络 ID。私有网络需要在 ZeroTier 控制器中授权新节点；`zerotier-cli status` 可以查看节点 ID。

## 使用

常用命令：

```sh
zerotier-cli status
zerotier-cli listnetworks
zerotier-cli peers
zerotier-cli leave NETWORK_ID
```

重启手机后会自动恢复已加入的网络。若其他 VPN 接管了这些网段，请在对应 VPN 中配置排除规则。模块提供本机网络连接，热点共享和 DNS 需要另外配置。

如果从其他客户端迁移了节点身份，请保持原客户端关闭，避免同时运行两个使用相同身份的节点。

## 升级与卸载

安装新版模块并重启即可升级，原有节点身份和网络配置会保留。

卸载后，数据保留在 `/data/adb/zerotier-native/`；如果不再使用，可手动删除该目录。

开发、测试和提交贡献请参阅 [贡献指南](CONTRIBUTING.md)。
