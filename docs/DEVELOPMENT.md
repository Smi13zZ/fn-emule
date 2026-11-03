# 开发说明

## 架构

```
┌──────────────────────────── 浏览器 ────────────────────────────┐
│  Vue 3 单页（app/web）  →  相对路径 ./api/*                     │
└───────────────┬────────────────────────────────────────────────┘
                │ fnOS CGI 代理（app/ui/index.cgi → 127.0.0.1:17581）
┌───────────────▼────────────────────────────────────────────────┐
│  面板服务 app/server/emulepanel.py  (Python 3 stdlib)           │
│    ├─ store.py      设置/历史/备份（var/settings.json 等）      │
│    ├─ notify.py     通知渠道与投递记录                          │
│    ├─ netutil.py    HTTP 抓取（server.met / nodes.dat / 更新）  │
│    └─ core/service.py  EmuleService 门面                        │
│         ├─ core/ec.py        aMule EC 二进制协议客户端           │
│         ├─ core/amule_ctl.py amuled 进程与 amule.conf 生成       │
│         └─ core/bootstrap.py server.met / nodes.dat 下载         │
└───────────────┬────────────────────────────────────────────────┘
                │ EC over 127.0.0.1:4712（二进制协议，单连接串行）
┌───────────────▼────────────────────────────────────────────────┐
│  amuled（随包自带 app/runtime/usr/bin/amuled）                  │
│    eD2k TCP 4662 / UDP 4672 · Kad UDP 4672                      │
└─────────────────────────────────────────────────────────────────┘
⟧⟧⟧

设计上的几条硬约束：

1. **面板进程是唯一入口**。`cmd/main⟧ 只负责起 `emulepanel.py⟧；面板再负责生成
   `amule.conf⟧、拉起/守护 `amuled⟧、退出时优雅停引擎。这样配置与进程状态不会各说各话。
2. **不让 aMule 自己发 HTTP 请求**。aMule 2.3.3 的 wxHTTP 客户端在代理网络下会触发
   wxWidgets 断言直接崩溃（`socketiohandler.cpp:Install_Callback⟧），所以 server.met 与
   nodes.dat 一律由面板用 Python 下载后写进配置目录，`amule.conf⟧ 里关掉自动版本检查。
3. **EC 端口只监听 127.0.0.1**，密码随机生成；浏览器永远拿不到引擎凭据。
4. **零第三方依赖**：后端只用标准库；前端 Vue 3 是随包的本地文件。

## EC 协议

EC（External Connection）是 aMule 给外部控制器用的二进制协议，源码在
`research/amule-ec-src/⟧（来自 aMule 2.3.3 的 `src/libs/ec/cpp⟧ 与 `src/ExternalConn.cpp⟧）。

- 帧：`0xE3 | opcode(1B) | payload_length(4B LE) | payload⟧
- 鉴权：发 `EC_AUTHENTICATION⟧ + `EC_TAG_PASSWD_HASH⟧（MD5 16 字节），回包给 `EC_TAG_AUTH_OK⟧
- 负载：一串 tag。tag 头 = 1 字节类型 + 1 字节名字（名字 ≥0x80 时为 2 字节），
  按类型读值（uint8/16/32/64、字符串、hash 16 字节、IP 4 字节等）
- 请求-响应串行：一条连接上一个请求对应一个回包；搜索是例外，结果由服务端异步推送，
  按 `EC_TAG_ECID⟧ 分发到对应搜索会话

`core/ec.py⟧ 里 `ECClient.request(opcode, tags)⟧ 是一次同步往返；`ECSession⟧ 负责鉴权、
重连与读超时。要看某个 opcode 的请求/回包结构，直接查 `ExternalConn.cpp⟧ 中
`EC_OP_*⟧ 对应的 case。

## 构建

```bash
python tools/build_fpk.py              # 完整构建
python tools/build_fpk.py --install    # 打完直接装到测试机
python tools/make_icons.py             # 重新生成图标
python tools/prepare_runtime.sh        # 仅重取 aMule 运行时（在 Linux 上跑）
⟧⟧⟧

构建流程（`build_fpk.py⟧）：

1. 把 `src/emule⟧ 打 tar（排除 `app/runtime⟧、`__pycache__⟧、`*.fpk⟧）
2. scp 到测试机 `/tmp/emule-build⟧ 解开
3. 首次构建时在设备上跑 `prepare_runtime.sh⟧ 从 Debian .deb 抽出 aMule + 依赖库到
   `app/runtime/usr/{bin,lib}⟧（会自检 `ldd⟧ 无 missing，且 `amuled --version⟧ 能跑）
4. `chmod⟧ 修正（目录 755、文件 644、`cmd/*⟧ 与 `app/ui/index.cgi⟧ 755）
5. `fnpack build⟧ → `fn-emule.fpk⟧ → 取回 `output/⟧
6. 用 `tools/verify_fpk.py⟧ 校验结构与可执行位

### 打包时必须注意

- **每个 `cmd/*⟧ 必须有 shebang**，否则 appcenter 报 `10237 exec format error⟧ 并回滚
- **`ICON.PNG⟧ 64×64、`ICON_256.PNG⟧ 256×256**
- 只能在 Linux 上打（Windows 打出来的包会丢可执行位 → `10111⟧）

## 多架构（单包通吃 x86 + ARM）

只发**一个** fpk（`-fnos-all.fpk`，manifest 里 `platform = all`），和 qbpanel 的做法一致：

```
app/runtime/amd64/usr/bin/amuled   + usr/lib/x86_64-linux-gnu/*.so*
app/runtime/arm64/usr/bin/amuled   + usr/lib/aarch64-linux-gnu/*.so*
```

- 面板启动时按 `platform.machine()` 选子目录（`x86_64→amd64`、`aarch64→arm64`），
  再把该目录的 `usr/lib/*-linux-gnu*` 加进 `LD_LIBRARY_PATH`；
- 两套引擎都由 `tools/prepare_runtime.sh --arch amd64|arm64` 从 Debian 12 官方包抽出：
  amd64 用本机 `ldd` + `amuled --version` 真跑自检，arm64 用 `tools/resolve_libs.py`
  静态解析 ELF `DT_NEEDED` 闭包（构建机是 x86，arm64 二进制跑不起来）；
- `tools/build_runtime_full.sh` 把两套合成一个 `amule-runtime-full.tar.gz`（约 7.8 MB，解包 23 MB）；
- `tools/verify_fpk.py` 会分别校验两个 `amuled` 的 ELF machine（amd64=62 / arm64=183）
  以及每套的库文件是否齐全；
- 打包产物约 8.4 MB。装到任意架构后，未被使用的那套引擎只是占一点磁盘，不影响运行。

## 验收

```bash
python3 tools/verify_fpk.py output/fn-emule-26.11.0-fnos-x86.fpk
python3 tools/smoke_test.py --base http://127.0.0.1:17581      # 在设备上跑
⟧⟧⟧

`smoke_test.py⟧ 覆盖 20 项：健康检查、概览、引擎进程、下载/上传列表、服务器、Kad、共享、
统计、日志、设置、偏好、通知、备份、更新检查、静态页与前端资源、加 ed2k 任务、任务出现在
列表、任务详情、暂停、取消、eD2k 搜索。

## 前端

- 零构建：`index.html⟧ 直接引 `lib/vue.global.prod.js⟧，视图切换靠 `view⟧ 状态，无路由
- 样式：`style.css⟧ 用 CSS 变量做深浅主题，栅格与卡片体系沿用 qBpanel
- 文案：`js/i18n.js⟧ 一份 `zh-CN⟧ + 一份 `en-US⟧ 字典，模板里不写死中文
- 本地联调：`python tools/mock_api.py --port 17581⟧ 会按接口契约造假数据并伺服静态页

## 目录约定

| 路径 | 说明 |
|---|---|
| `src/emule/manifest⟧ | 应用元信息（appname / version / display_name / 端口） |
| `src/emule/cmd/main⟧ | 生命周期：start / stop / status / restart |
| `src/emule/cmd/*_init⟧ `*_callback⟧ | 安装/升级/卸载/配置变更钩子 |
| `src/emule/config/privilege⟧ | 以 root 运行 |
| `src/emule/config/resource⟧ | data-share：fn-emule / Incoming / Temp |
| `src/emule/app/ui/⟧ | fnOS 桌面入口（CGI 代理 + 图标 + `config⟧） |
| `src/emule/app/server/⟧ | 面板后端 |
| `src/emule/app/web/⟧ | 前端 |
| `src/emule/app/runtime/⟧ | 构建时生成的内置引擎（不入库） |
