# fn-emule 开发契约（唯一事实来源）

> 本文件由 Lead 维护。任何实现偏离契约的地方，先改契约再改代码。

## 1. 产品与命名

| 项 | 值 |
| --- | --- |
| 产品名（工作名） | fn-emule |
| manifest appname | `fn-emule⟧ |
| display_name | `eMule⟧ |
| 桌面入口包名 | `fn-emule.Application⟧ |
| 桌面 URL | `/cgi/ThirdParty/fn-emule/index.cgi/⟧ |
| 版本 | `26.11.0⟧（年.月.序号，见 AGENTS.md 产品版本规则） |
| 制品名 | `fn-emule-26.11.0-fnos-x86.fpk⟧ |
| platform | `x86⟧（内含 amd64 二进制，不能写 all） |
| 面板端口 | 17581（冷门 5 位端口，避开 8899/8080/3000 等高频端口） |
| aMule EC 端口 | 4712（仅 127.0.0.1） |
| aMule eD2k 端口 | TCP 4662 / UDP 4672（可在设置里改） |
| 引擎 | aMule 2.3.3（Debian 12 bookworm 官方包，随 fpk 自带，不装系统包） |

UI 文案：中文为主，英文完整对照（i18n），品牌名一律 `eMule 电驴` / `eMule`。

## 2. 目录结构

仓库（D:\Workspace\DeepSeek Harness\fn-emule）：

```
fn-emule/
  docs/                    契约、开发说明、使用教程
  research/amule-ec-src/   aMule 2.3.3 EC 协议 C++ 源码（只读参考，勿改）
  reference/qbpanel-repo/  qbpanel 参考源码（只读，勿改；UI 从这里搬）
  src/emule/               fpk 源码根（fnpack build 就在这个目录跑）
  tools/                   构建/校验/取 runtime 的脚本
  output/                  最终 .fpk
  tmp/                     临时与联调脚本
```

```
src/emule/                        → 打包后 = /var/apps/fn-emule/target (TRIM_APPDEST)
  manifest  ICON.PNG  ICON_256.PNG
  config/{privilege,resource}
  cmd/{main,install_init,install_callback,upgrade_init,upgrade_callback,uninstall_init,uninstall_callback,config_init,config_callback}
  wizard/{install,config}
  app/
    ui/{index.cgi,config,images/*}
    runtime/                 ← 构建时由 tools/prepare_runtime.sh 生成（不入库）
      usr/bin/amuled
      usr/lib/x86_64-linux-gnu/*.so*
    server/
      emulepanel.py          HTTP 服务 + 路由（入口，panel-api 负责）
      core/
        ec.py                EC 协议客户端（ec-core 负责）
        amule_ctl.py         amuled 进程管理 + amule.conf 生成（ec-core 负责）
        service.py           领域门面（ec-core 负责，接口见 §4）
        bootstrap.py         server.met / nodes.dat / ipfilter 下载（ec-core 负责）
        store.py             面板设置持久化 + 历史/通知记录（panel-api 负责）
      notify.py              通知通道（panel-api 负责，从 qbpanel 改）
      netutil.py             HTTP 抓取（urllib，支持系统代理）（panel-api 负责）
    web/                    前端（web-ui 负责）
      index.html style.css
      js/{api.js,app.js,charts.js,i18n.js,util.js}
      lib/vue.global.prod.js
      images/icon.svg icon.png
```

运行时数据（持久，不进包）：

```
/var/apps/fn-emule/var/                 TRIM_PKGVAR
  settings.json                          面板设置（含 aMule 偏好、通知、备份配置）
  amule/                                 aMule 配置目录（amule.conf / server.met / nodes.dat / Temp / Incoming）
  panel.log  amuled.log
  runtime-ports.env                      BACKEND_PORT/ADMIN_TARGET_PORT/EC_PORT
  panel.pid  amuled.pid
  backups/
/var/apps/fn-emule/shares/fn-emule/     用户可见共享目录（data-share）
  Incoming/    下载完成目录（默认）
  Temp/        临时分块目录（默认）
```

## 3. HTTP API 契约

后端前缀 `./api⟧（前端一律用相对路径，兼容 CGI 挂载点）。所有响应 JSON，错误统一
`HTTP 4xx/5xx + {"error": "人类可读中文"}⟧。所有 POST 收 `application/json⟧。

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | /api/health | 存活探针 `{ok,version,amule:{running,ec}}⟧ |
| GET | /api/overview | 概览：链路状态/速度/队列/磁盘/会话流量 |
| GET | /api/transfers?type=download\|upload | 列表 + summary |
| POST | /api/transfers/add | `{links:[...], category?, paused?}⟧ → 逐个结果 |
| GET | /api/transfers/{hash} | 详情：来源列表 + 分块图 + 文件信息 |
| POST | /api/transfers/{hash}/action | `{action:pause\|resume\|cancel\|priority, priority?}⟧ |
| POST | /api/transfers/apply | 批量 `{hashes:[...], action}⟧ |
| GET | /api/servers | 服务器列表 + 当前连接 |
| POST | /api/servers/connect | `{ip,port}⟧ |
| POST | /api/servers/add, /remove, /priority | 增删改优先级 |
| POST | /api/servers/update | 面板自己下载 server.met → 导入 → EC reload |
| GET | /api/kad | Kad 状态 + 节点数 + 引导信息 |
| POST | /api/kad/bootstrap | 下载 nodes.dat 并重连 Kad |
| GET | /api/shared | 共享文件列表 |
| POST | /api/shared/reload | 重新扫描共享目录 |
| POST | /api/search/start | `{q, kind: server\|kad\|global, method: name}⟧ → `{search_id}⟧ |
| GET | /api/search/{id} | `{progress, done, results:[...]}⟧ |
| POST | /api/search/{id}/stop | 停止搜索 |
| POST | /api/search/{id}/download | `{hash}⟧ 取回结果下载 |
| GET | /api/stats | 统计树（扁平 `[{group,name,value}]⟧） |
| GET | /api/log?limit= | aMule 日志行 |
| GET/POST | /api/settings | 面板 + 引擎设置读写 |
| GET | /api/prefs | 从 aMule 读真实偏好（端口/限速/目录） |
| POST | /api/core/{start\|stop\|restart} | 引擎控制 |
| GET | /api/core/status | 引擎进程 + EC |
| GET | /api/notify | 通知通道与记录 |
| POST | /api/notify/settings, /channel, /test | 通知配置 |
| GET | /api/backup/status · POST /api/backup/run, /restore | 配置备份 |
| GET | /api/update/check · POST /api/update/install | GitHub Release 更新（未发布时优雅返回 no_release） |

核心载荷（前端按此渲染，字段不得随意改名）：

```json
// GET /api/overview
{
  "engine": {"running": true, "ec": true, "version": "2.3.3", "pid": 1234},
  "ed2k": {"connected": true, "low_id": true, "server": {"name":"ed2k-rust","ip":"85.17.116.222","port":6082}},
  "kad": {"connected": true, "firewalled": true, "nodes": 812, "users": 1200000, "files": 45000000},
  "speed": {"down": 1234567, "up": 23456, "down_limit": 0, "up_limit": 0, "max_down": 5120000},
  "session": {"down": 987654321, "up": 12345678, "down_total": 0, "up_total": 0},
  "counters": {"downloads": 12, "downloads_active": 3, "downloads_paused": 5, "downloads_waiting": 4,
               "uploads": 2, "queue": 12, "sources": 340, "connections": 88},
  "disk": {"free": 123456789012, "total": 999999999999, "path": "/vol1/..."},
  "history": [{"t": 1730000000, "down": 0, "up": 0}]
}

// GET /api/transfers?type=download → {items:[...], summary:{count,active,paused,waiting,complete,down,up}, total}
// item:
{"hash":"A1B2...","name":"Ubuntu.iso","size":70866960384,"done":12345678,"percent":0.017,
 "speed":123456,"eta":36000,"status":"downloading|paused|waiting|hashing|error|completing",
 "priority":"low|normal|high|auto","category":"","partfile":true,"added":1730000000,
 "sources":{"total":120,"transferring":3,"asked":40,"found":80,"a4af":2},
 "progress":{"completed":12345678},"shared":false,"uploading":false}

// GET /api/transfers/{hash} → {"file":{...同上},"sources":[{ip,port,client,version,userhash,speed,state,queue_rank,queue_wait}],
//   "chunks":[{"start":0,"end":184320,"state":"done|pending|missing"}]}

// GET /api/servers → {"items":[{ip,port,name,desc,users,maxusers,files,priority,ping,failed,failed_count}],
//   "current":{"ip","port","name"},"ed2k_connected":true,"total":20,"working":15}

// GET /api/search/{id} → {"search_id":"...","progress":100,"done":true,
//   "results":[{hash,name,size,sources,type,ext,percent,already}],"started_at":...}
```

## 4. core/service.py 接口（ec-core ⇄ panel-api 的边界）

panel-api 只依赖这个门面，不直接碰 EC/进程。所有方法同步、线程安全，失败抛
`EmuleError(msg)⟧（继承 Exception）；引擎未启动时抛 `EmuleOffline⟧。

```python
class EmuleService:
    def __init__(self, settings_provider) -> None   # settings_provider() 返回 dict（§5）
    def prepare(self) -> None        # 幂等：建目录、生成 amule.conf、下载 bootstrap（首次）
    def start(self) -> None          # 起 amuled（在运行则 no-op）
    def stop(self) -> None
    def restart(self) -> None
    def process_status(self) -> dict  # {"running","pid","ec","uptime"}
    def overview(self) -> dict
    def transfers(self, kind: str) -> dict      # kind = "download" | "upload"
    def transfer_detail(self, file_hash: str) -> dict
    def transfer_action(self, file_hash: str, action: str, priority: str|None = None) -> dict
    def transfer_apply(self, hashes, action: str) -> dict
    def add_links(self, links, category: str = "", paused: bool = False) -> list
    def servers(self) -> dict
    def server_connect(self, ip, port) -> dict
    def server_add(self, ip, port, name: str = "") -> dict
    def server_remove(self, ip, port) -> dict
    def server_priority(self, ip, port, priority: str) -> dict
    def servers_update(self) -> dict
    def kad_status(self) -> dict
    def kad_bootstrap(self) -> dict
    def shared(self) -> dict
    def shared_reload(self) -> dict
    def search_start(self, q, kind, method) -> dict
    def search_state(self, search_id) -> dict
    def search_stop(self, search_id) -> dict
    def search_download(self, search_id, file_hash) -> dict
    def stats(self) -> dict
    def logs(self, limit: int = 200) -> list    # [{"t": ts, "level": "...", "text": "..."}]
    def prefs(self) -> dict
    def apply_prefs(self, patch: dict) -> dict
    def shutdown(self) -> None
```

约定：
- `hash⟧ 一律大写十六进制 32 位字符串，前端展示时截断。
- 时间戳一律 Unix 秒（int）。字节一律 int。百分比 `percent⟧ 是 0..1 浮点。
- `status⟧ 词表固定为 §3 中那几个值，中文文案由前端 i18n 映射。
- EC 请求失败降级为 `EmuleOffline⟧，不裸 500。

## 5. settings.json

```json
{
  "panel": {"port": 17581, "theme": "auto", "lang": "zh"},
  "engine": {
    "ec_port": 4712, "ec_password": "<随机 16 位>",
    "tcp_port": 4662, "udp_port": 4672,
    "nick": "fnOS@eMule",
    "incoming_dir": "/var/apps/fn-emule/shares/fn-emule/Incoming",
    "temp_dir": "/var/apps/fn-emule/shares/fn-emule/Temp",
    "shared_dirs": ["/var/apps/fn-emule/shares/fn-emule/Incoming"],
    "max_download": 0, "max_upload": 0, "max_connections": 500, "max_sources": 300,
    "autoconnect": true, "connect_ed2k": true, "connect_kad": true,
    "add_paused": false, "ich": true, "aich": true, "upnp": false,
    "ipfilter": true
  },
  "bootstrap": {"server_met_url": "https://upd.emule-security.org/server.met",
                "nodes_dat_url": "https://upd.emule-security.org/nodes.dat",
                "auto_hours": 24, "last_update": 0},
  "notify": {"enabled": false, "channels": [], "events": {"complete": true, "error": true}},
  "backup": {"auto": false, "keep": 7, "last": 0},
  "update": {"repo": "Smi13zZ/fn-emule", "check": true, "last": 0, "latest": ""}
}
```

## 6. 构建与联调（测试机 192.168.1.13，用户 ranger，免密 sudo）

- 上传源码：tar 打包 src/emule → /tmp/emule-build；可执行位修正：cmd/* 与 app/ui/index.cgi 755，其余 644
- 取 runtime（首次）：NAS 上跑 tools/prepare_runtime.sh（apt-get download + dpkg-deb -x，仅保留非基础库）
- 打包：cd /tmp/emule-build && fnpack build → fn-emule.fpk
- 校验：python3 tools/verify_fpk.py <fpk>
- 安装：测试机已有 appcenter-cli，命令行直接装（比网页快）：
    sudo appcenter-cli install-fpk /tmp/fn-emule.fpk -e /tmp/fn-emule.env -v 1
    sudo appcenter-cli list / status --appname fn-emule / start|stop --appname fn-emule
    （-e 传 wizard 环境变量文件，格式 KEY=VALUE 每行一个；升级直接再 install-fpk 同 appname）
- 基础环境已确认：/usr/bin/python3 = Python 3.11.2（fnOS 自带，面板纯标准库，无需依赖商店 Python 应用）
- 联调 amuled：sudo $AMULE --config-dir=$VAR/amule -o，再用 amulecmd 对比数据

测试机上既有实验环境（可复用，勿删）：
- /tmp/amusrc/aMule-2.3.3/：aMule 源码（EC 协议参考）
- /tmp/emtest/：可用的 amuled 测试实例（EC 密码 test123，带 server.met/nodes.dat）
- 系统已装 amule-daemon/amule-utils（仅供对比，最终包不依赖它们）

## 6.1 打包踩坑记录（已实测，别再踩）

1. **每个 cmd/* 脚本必须有 shebang**（`#!/bin/bash`）。缺 shebang 时 appcenter 会报
   `10237: fork/exec .../cmd/install_init: exec format error` 并回滚安装。
2. **图标尺寸**：`ICON.PNG` 必须 64x64，`ICON_256.PNG` 必须 256x256（照 qbpanel 的实际产物）。
3. **必须是 Linux 上 fnpack 打的包**：Windows 打的包会丢可执行位 → `10111`。
   构建统一走 `python tools/build_fpk.py`（tar → NAS → chmod → fnpack build → 取回 → 校验）。
4. **安装/升级用 appcenter-cli**（测试机已装）：
   ```
   printf 'wizard_backend_port=17581\nwizard_tcp_port=4662\nwizard_udp_port=4672\n' > /tmp/fn-emule.env
   sudo appcenter-cli install-fpk /tmp/fn-emule.fpk -e /tmp/fn-emule.env -v 1
   sudo appcenter-cli list            # 看状态
   sudo appcenter-cli start fn-emule  # / stop fn-emule / uninstall fn-emule
   ```
   安装失败先看 `/var/log/trim_app_center/error.log`（grep fn-emule），再来 slog 看 TRIMEVENT。
5. **装好后的真实路径**（实测 fnOS 1.2.0800）：
   ```
   /var/apps/fn-emule/target  -> /usr/local/apps/@appcenter/fn-emule     (TRIM_APPDEST)
   /var/apps/fn-emule/var     -> /usr/local/apps/@appdata/fn-emule       (TRIM_PKGVAR)
   /var/apps/fn-emule/etc     -> /usr/local/apps/@appconf/fn-emule
   /var/apps/fn-emule/home    -> /usr/local/apps/@apphome/fn-emule
   /var/apps/fn-emule/meta    -> /vol1/@appmeta/fn-emule
   /var/apps/fn-emule/shares/fn-emule       -> /vol1/@appshare/fn-emule
   /var/apps/fn-emule/shares/Incoming       -> /vol1/@appshare/fn-emule/Incoming
   /var/apps/fn-emule/shares/Temp           -> /vol1/@appshare/fn-emule/Temp
   ```
6. `fnpack build` 产物名取自 manifest 的 appname（`fn-emule.fpk`），不是目录名。
7. **运行时二进制打包位置**：`app/runtime/usr/bin/amuled` + `app/runtime/usr/lib/x86_64-linux-gnu/*.so*`
   （由 `tools/prepare_runtime.sh` 从 Debian .deb 抽出，12MB 解包 / 4MB 压缩，已自检只靠随包库可运行）。

## 7. 协作纪律

- 文件所有权见 §2 注释；只改自己名下文件。需要改别人文件 → 发消息给 Lead。
- 不碰 research/ 与 reference/（只读）。
- 所有面向用户的文案中文为主、英文补全；不写"待实现/占位"字样到 UI。
- 提交前必须 python3 -m py_compile / node --check 通过。


## 3.1 /api/diagnostics 契约（v26.11.1 新增）

一次请求跑完全部检查，最多 12 秒；失败项不抛错，而是写进 `checks[].level = "warn"|"error"⟧。

```json
{
  "ok": true,
  "checked_at": 1793650000,
  "version": "26.11.1",
  "summary": {
    "grade": "ok | warn | error",
    "high_id": false,
    "kad_open": false,
    "title": "Low ID · Kad 受限",
    "detail": "公网无法主动连到本机，来源与速度会受影响。"
  },
  "engine": {
    "running": true, "ec": true, "ed2k_connected": true, "low_id": true,
    "server": {"name": "eMule Sunrise", "ip": "176.123.5.89", "port": 4725},
    "kad": {"connected": true, "firewalled": true, "nodes": 440},
    "inbound_connections": 0, "tcp_port": 4662, "udp_port": 4672
  },
  "host": {
    "lan_ip": "192.168.1.13", "gateway": "192.168.1.1", "iface": "eth0",
    "public_ip": "1.2.3.4", "public_ip_error": "",
    "private_ip": true, "cgnat_suspect": false
  },
  "ports": {
    "tcp_listening": true, "udp_bound": true,
    "firewall": "unknown | open | blocked", "firewall_detail": "iptables 未发现拦截规则"
  },
  "checks": [
    {"id": "engine", "level": "ok", "title": "引擎运行中", "detail": "aMule 2.3.3", "action": ""},
    {"id": "high_id", "level": "warn", "title": "eD2k 为 Low ID（受限）", "detail": "服务器反连 TCP 4662 失败", "action": "路由器把 TCP 4662 转发到 192.168.1.13"},
    {"id": "kad", "level": "warn", "title": "Kad 受限（firewalled）", "detail": "外部节点无法主动连入 UDP 4672", "action": "路由器把 UDP 4672 转发到 192.168.1.13"}
  ],
  "suggestions": ["路由器转发 TCP 4662 → 192.168.1.13", "路由器转发 UDP 4672 → 192.168.1.13", "改完在「设置 → 网络」保存并重启引擎"]
}
```

规则：
- `checks[].id⟧ 词表固定：engine / ed2k_connect / high_id / kad / tcp_listen / udp_bind / firewall / public_ip / cgnat / inbound。
- `level⟧ 只用 ok / warn / error；前端按这个着色，不要新增。
- 所有 `title/detail/action⟧ 都是**中文人类可读**（ENG 由前端 i18n 处理不了就原样显示，允许中文）。
- 不允许因为某项探测失败就让整个接口 5xx；最差返回 `grade:"error"⟧ + 对应 check。
