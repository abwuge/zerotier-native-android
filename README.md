# ZeroTier Native for Android

English | [简体中文](README.zh-CN.md)

Native ZeroTier with automatic startup.

Supports Magisk, KernelSU, and APatch on ARM64 devices running Android 11 or later with kernel TUN/TAP support.

## Installation

1. Download the module ZIP from the [latest release](https://github.com/abwuge/zerotier-native-android/releases/latest).
2. Install the module, select interface naming with the volume keys, then reboot. Volume Up selects the `ethzt` prefix (the default after an 8-second timeout); Volume Down selects ZeroTier's default naming.
3. Join a network in a terminal:

```sh
su
zerotier-cli join NETWORK_ID
```

Replace `NETWORK_ID` with your 16-digit hexadecimal network ID. For private networks, authorize the new node in your ZeroTier controller. Run `zerotier-cli status` to find the node ID.

Installation prompts and module messages follow the Android system language: Chinese for Chinese locales, English otherwise. The module description is set at installation. Upstream `zerotier-cli` output remains in English.

## Usage

Common commands:

```sh
zerotier-cli status
zerotier-cli listnetworks
zerotier-cli peers
zerotier-cli leave NETWORK_ID
```

Joined networks reconnect automatically after a reboot. If another VPN takes over these subnets, configure exclusions in that VPN. The module connects the Android device itself; hotspot sharing and DNS require separate configuration.

If you migrate a node identity from another client, keep that client stopped to avoid running two nodes with the same identity.

## Upgrading and uninstalling

Install the new module and reboot to upgrade. Your node identity and network configuration are preserved.

Uninstalling keeps your data in `/data/adb/zerotier-native/`. You can delete this directory manually when you no longer need it.

For development, testing, and contributions, see the [contributing guide](CONTRIBUTING.md).
