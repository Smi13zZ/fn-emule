# 第三方组件

本应用的 fpk 里随包分发了以下第三方二进制与数据文件。它们都由 `tools/prepare_runtime.sh⟧
从 Debian 12 (bookworm) 官方仓库的 .deb 中原样抽出，未做任何修改；x86 包取 amd64 版本，ARM 包取 arm64 版本。

| 组件 | 版本 | 许可证 | 用途 | 源码 |
|---|---|---|---|---|
| aMule（amuled） | 2.3.3-3 | GPL-2.0-or-later | eD2k / Kad 下载引擎 | https://github.com/amule-project/amule |
| wxWidgets（libwxbase3.2） | 3.2.2+dfsg-2 | wxWindows Library Licence（LGPL-2.0+ 兼容） | aMule 的基础库 | https://www.wxwidgets.org/ |
| Crypto++（libcrypto++8） | 8.7.0 | Boost Software License 1.0 | aMule 的加密/哈希 | https://www.cryptopp.com/ |
| libupnp（libupnp13 / libixml10） | 1.8.4 | BSD-3-Clause | aMule 的 UPnP 端口映射 | https://github.com/pupnp/pupnp |
| PCRE2（libpcre2-32） | 10.42 | BSD-3-Clause | aMule 的表达式匹配 | https://github.com/PCRE2Project/pcre2 |
| Vue 3 | 3.4.x（global prod build） | MIT | 前端框架 | https://github.com/vuejs/core |

## 应用图标

应用图标使用 **eMule 官方吉祥物（驴头）**，版权归 eMule 项目所有，Wikimedia Commons 标注为 GPL：

- 矢量原稿：<https://commons.wikimedia.org/wiki/File:EMule_logo.svg>
- 来源：<https://www.emule-project.net>
- 本地副本与重新生成方法：`tools/icon-src/`

## GPL 说明

aMule 以 GPL-2.0-or-later 分发。本应用的分发方式是：面板程序（MIT）通过 aMule 公开的
External Connection 协议与本机 `amuled⟧ 进程通信，`amuled⟧ 以独立进程运行、未做修改、
未与面板程序链接成单一作品。随包分发的 aMule 二进制来自 Debian 官方仓库，其完整源码可从
<https://sources.debian.org/src/amule/> 或 <https://github.com/amule-project/amule> 获取；
如需与 fpk 完全对应的源码，可用 `apt-get source amule=1:2.3.3-3⟧ 取得（Debian 12 bookworm）。

Debian 包内的版权与许可证原文随二进制一起放在 fpk 的
`app/runtime/usr/share/doc/amule-daemon/copyright⟧（构建时复制）。
