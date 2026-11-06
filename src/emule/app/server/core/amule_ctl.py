# -*- coding: utf-8 -*-
"""amuled 生命周期管理 + amule.conf 生成。

设计要点（对应 docs/CONTRACT.md §2/§5）：
  * amule.conf 内置一份完整的 aMule 2.3.3 默认模板，启动前用面板设置覆盖关键项，
    然后原子写盘（先写 .tmp 再 os.replace），避免 aMule 读到半个文件。
  * 共享目录不在 amule.conf 里，aMule 单独存 shareddir.dat（每行一个路径），一并生成。
  * 启动用 setsid（start_new_session=True），amuled 的输出重定向到 var/amuled.log。
  * 停服用 SIGTERM 等 20s（aMule 要把 partfile 落盘），超时才 SIGKILL。
  * 守护线程每 5s 检查一次，进程挂了按 3/6/12s 退避重启，每小时最多 5 次，写 panel.log。
  * 启动前检查 tcp/udp/ec 端口占用，被占用时报出具体端口，绝不盲目起进程。
"""

import hashlib
import os
import platform
import random
import signal
import socket
import subprocess
import threading
import time

try:
    from .ec import EmuleError
except ImportError:                                    # pragma: no cover - 平铺导入
    from ec import EmuleError


AMULE_VERSION = "2.3.3"

#: amuled 进程结束等待时间（秒）
STOP_TIMEOUT = 20.0
#: 启动后等 EC 端口就绪的时间（秒）
START_TIMEOUT = 40.0
#: 守护线程检查间隔（秒）
WATCH_INTERVAL = 5.0
#: 守护线程重启退避序列（秒）
BACKOFF = (3.0, 6.0, 12.0)
#: 每小时最多自动重启次数
MAX_RESTART_PER_HOUR = 5
#: amuled.log 单文件上限。引擎自己不做轮转，实测一个月能涨到 100 MB 左右，
#: 所以每次启动前查一次大小，超了就滚成 .1（只留一份，够排查即可）。
AMULED_LOG_MAX_BYTES = 8 * 1024 * 1024


#: 展开共享目录时最多走这么多层、最多收这么多条路径。
#: 目的是防住"把 / 整块共享"这类失误——那种情况下一路递归下去会把
#: shareddir.dat 撑到几十万行，aMule 启动时要逐个目录扫，直接把面板拖死。
SHARED_SCAN_MAX_DEPTH = 8
SHARED_SCAN_MAX_DIRS = 4000


def expand_shared_dirs(dirs, max_depth=SHARED_SCAN_MAX_DEPTH,
                       max_dirs=SHARED_SCAN_MAX_DIRS):
    """把共享目录展开成"该目录 + 它的全部子目录"。

    aMule 的 AddFilesFromDirectory()（SharedFileList.cpp）**只扫目录的顶层**，
    看到子目录就跳过——它从不递归。所以用户在面板里加一个装了几千个文件的
    大目录，aMule 只会把该目录顶层那几个文件算进共享，其余全部静默忽略，
    日志里最多留一句 "No shareable files found in directory"，界面上看不出问题。

    这里在写 shareddir.dat 之前把子目录一并摊平：aMule 拿到的是一串"每个目录
    都只有文件"的清单，等价于递归扫描。目录不存在 / 没权限就跳过（不能因为
    用户写错一个路径就整份配置写不进去）。符号链接不跟随，避免环形目录。
    """
    out = []
    seen = set()

    def add(path):
        key = os.path.normpath(path)
        if key in seen:
            return False
        if len(out) >= max_dirs:
            return False
        seen.add(key)
        out.append(path)
        return True

    for raw in dirs or []:
        path = str(raw or "").strip()
        if not path:
            continue
        path = os.path.normpath(path)
        if not add(path):
            continue
        if not os.path.isdir(path):
            continue
        base_depth = path.rstrip(os.sep).count(os.sep)
        try:
            for root, subdirs, _files in os.walk(path, followlinks=False):
                if len(out) >= max_dirs:
                    break
                if root.rstrip(os.sep).count(os.sep) - base_depth >= max_depth:
                    subdirs[:] = []
                subdirs.sort()
                for name in subdirs:
                    if len(out) >= max_dirs:
                        break
                    add(os.path.join(root, name))
        except OSError:
            continue
    return out


def _md5_hex(text):
    return hashlib.md5((text or "").encode("utf-8")).hexdigest()


def random_password(length=16):
    """生成 EC 明文口令（面板设置里存明文，写进 amule.conf 时转 MD5）。"""
    alphabet = "abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    rng = random.SystemRandom()
    return "".join(rng.choice(alphabet) for _ in range(int(length)))


#: amule.conf 模板：[(section, [(key, value), ...]), ...]
CONF_TEMPLATE = [
    ("eMule", [
        ("AppVersion", AMULE_VERSION),
        ("Nick", "http://www.aMule.org"),
        ("QueueSizePref", "50"),
        ("MaxUpload", "0"),
        ("MaxDownload", "0"),
        ("SlotAllocation", "2"),
        ("Port", "4662"),
        ("UDPPort", "4672"),
        ("UDPEnable", "1"),
        ("Address", ""),
        ("Autoconnect", "1"),
        ("MaxSourcesPerFile", "300"),
        ("MaxConnections", "500"),
        ("MaxConnectionsPerFiveSeconds", "20"),
        ("RemoveDeadServer", "1"),
        ("DeadServerRetry", "3"),
        ("ServerKeepAliveTimeout", "0"),
        ("Reconnect", "1"),
        ("Scoresystem", "1"),
        ("Serverlist", "0"),
        ("AddServerListFromServer", "0"),
        ("AddServerListFromClient", "0"),
        ("SafeServerConnect", "0"),
        ("AutoConnectStaticOnly", "0"),
        ("UPnPEnabled", "0"),
        ("UPnPTCPPort", "50000"),
        ("SmartIdCheck", "1"),
        ("ConnectToKad", "1"),
        ("ConnectToED2K", "1"),
        ("TempDir", ""),
        ("IncomingDir", ""),
        ("ICH", "1"),
        ("AICHTrust", "0"),
        ("CheckDiskspace", "0"),
        ("MinFreeDiskSpace", "1"),
        ("AddNewFilesPaused", "0"),
        ("PreviewPrio", "0"),
        ("ManualHighPrio", "0"),
        ("StartNextFile", "0"),
        ("StartNextFileSameCat", "0"),
        ("StartNextFileAlpha", "0"),
        ("FileBufferSizePref", "16"),
        ("DAPPref", "1"),
        ("UAPPref", "1"),
        ("AllocateFullFile", "0"),
        ("OSDirectory", ""),
        ("OnlineSignature", "0"),
        ("OnlineSignatureUpdate", "5"),
        ("EnableTrayIcon", "0"),
        ("MinToTray", "0"),
        ("Notifications", "0"),
        ("ConfirmExit", "0"),
        ("StartupMinimized", "1"),
        ("3DDepth", "10"),
        ("ToolTipDelay", "1"),
        ("ShowOverhead", "0"),
        ("ShowInfoOnCatTabs", "1"),
        ("VerticalToolbar", "0"),
        ("GeoIPEnabled", "0"),
        ("ShowVersionOnTitle", "0"),
        ("VideoPlayer", ""),
        ("StatGraphsInterval", "3"),
        ("statsInterval", "30"),
        ("DownloadCapacity", "300"),
        ("UploadCapacity", "100"),
        ("StatsAverageMinutes", "5"),
        ("VariousStatisticsMaxValue", "100"),
        ("SeeShare", "2"),
        ("FilterLanIPs", "1"),
        ("ParanoidFiltering", "1"),
        ("IPFilterAutoLoad", "1"),
        ("IPFilterURL", ""),
        ("FilterLevel", "127"),
        ("IPFilterSystem", "0"),
        ("FilterMessages", "1"),
        ("FilterAllMessages", "0"),
        ("MessagesFromFriendsOnly", "0"),
        ("MessageFromValidSourcesOnly", "1"),
        ("FilterWordMessages", "0"),
        ("MessageFilter", ""),
        ("ShowMessagesInLog", "1"),
        ("FilterComments", "0"),
        ("CommentFilter", ""),
        ("ShareHiddenFiles", "0"),
        ("AutoSortDownloads", "0"),
        ("NewVersionCheck", "0"),
        ("AdvancedSpamFilter", "1"),
        ("MessageUseCaptchas", "1"),
        ("Language", ""),
        ("SplitterbarPosition", "75"),
        ("YourHostname", ""),
        ("DateTimeFormat", "%A, %x, %X"),
        ("AllcatType", "0"),
        ("ShowAllNotCats", "0"),
        ("SmartIdState", "0"),
        ("DropSlowSources", "0"),
        ("KadNodesUrl", "http://upd.emule-security.org/nodes.dat"),
        ("Ed2kServersUrl", "http://upd.emule-security.org/server.met"),
        ("ShowRatesOnTitle", "0"),
        ("CreateSparseFiles", "1"),
    ]),
    ("Browser", [
        ("OpenPageInTab", "1"),
        ("CustomBrowserString", ""),
    ]),
    ("Proxy", [
        ("ProxyEnableProxy", "0"),
        ("ProxyType", "0"),
        ("ProxyName", ""),
        ("ProxyPort", "1080"),
        ("ProxyEnablePassword", "0"),
        ("ProxyUser", ""),
        ("ProxyPassword", ""),
    ]),
    ("ExternalConnect", [
        ("UseSrcSeeds", "0"),
        ("AcceptExternalConnections", "1"),
        ("ECAddress", "127.0.0.1"),
        ("ECPort", "4712"),
        ("ECPassword", ""),
        ("UPnPECEnabled", "0"),
        ("ShowProgressBar", "1"),
        ("ShowPercent", "1"),
        ("UseSecIdent", "1"),
        ("IpFilterClients", "1"),
        ("IpFilterServers", "1"),
        ("TransmitOnlyUploadingClients", "0"),
    ]),
    ("WebServer", [
        ("Enabled", "0"),
        ("Password", ""),
        ("PasswordLow", ""),
        ("Port", "4711"),
        ("WebUPnPTCPPort", "50001"),
        ("UPnPWebServerEnabled", "0"),
        ("UseGzip", "1"),
        ("UseLowRightsUser", "0"),
        ("PageRefreshTime", "120"),
        ("Template", ""),
        ("Path", "amuleweb"),
    ]),
    ("GUI", [
        ("HideOnClose", "0"),
    ]),
    ("Statistics", [
        ("MaxClientVersions", "0"),
    ]),
    ("Obfuscation", [
        ("IsClientCryptLayerSupported", "1"),
        ("IsCryptLayerRequested", "1"),
        ("IsClientCryptLayerRequired", "0"),
        ("CryptoPaddingLenght", "254"),
    ]),
    ("PowerManagement", [
        ("PreventSleepWhileDownloading", "0"),
    ]),
]


def _as_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _as_int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


class AmuleCtl(object):
    """amuled 的启动、停止、配置生成与看护。"""

    def __init__(self, settings_provider, var_dir, config_dir=None, runtime_dir=None,
                 logger=None):
        self._settings_provider = settings_provider
        self.var_dir = os.path.abspath(var_dir)
        self.config_dir = os.path.abspath(config_dir or os.path.join(self.var_dir, "amule"))
        self.runtime_dir = os.path.abspath(runtime_dir) if runtime_dir else None
        self.log_file = os.path.join(self.var_dir, "amuled.log")
        self.panel_log = os.path.join(self.var_dir, "panel.log")
        self.pid_file = os.path.join(self.var_dir, "amuled.pid")
        self._logger = logger
        self._lock = threading.RLock()
        self._watch_thread = None
        self._watch_stop = threading.Event()
        self._want_running = False
        self._restarts = []          # 最近一小时的重启时间戳
        self._last_error = ""
        # 设置里没给 EC 口令时用它兜底；同一进程内必须稳定，否则面板与 amule.conf 会对不上
        self._fallback_password = random_password()

    # -- 设置 ---------------------------------------------------------
    def settings(self):
        """读取面板设置里的 engine 段并补全默认值。"""
        data = self._settings_provider() if self._settings_provider else {}
        engine = dict(data.get("engine") or {})
        bootstrap = dict(data.get("bootstrap") or {})
        defaults = {
            "ec_port": 4712,
            "ec_password": "",
            "tcp_port": 4662,
            "udp_port": 4672,
            "nick": "fnOS@eMule",
            "max_download": 0,
            "max_upload": 0,
            "max_connections": 500,
            "max_sources": 300,
            "autoconnect": True,
            "connect_ed2k": True,
            "connect_kad": True,
            "add_paused": False,
            "ich": True,
            "aich": True,
            "upnp": False,
            "ipfilter": True,
        }
        merged = dict(defaults)
        merged.update(engine)
        merged["incoming_dir"] = engine.get("incoming_dir") or \
            os.path.join(os.path.dirname(self.var_dir), "shares", "fn-emule", "Incoming")
        merged["temp_dir"] = engine.get("temp_dir") or \
            os.path.join(os.path.dirname(self.var_dir), "shares", "fn-emule", "Temp")
        merged["shared_dirs"] = engine.get("shared_dirs") or [merged["incoming_dir"]]
        merged["server_met_url"] = bootstrap.get("server_met_url") or \
            "https://upd.emule-security.org/server.met"
        merged["nodes_dat_url"] = bootstrap.get("nodes_dat_url") or \
            "https://upd.emule-security.org/nodes.dat"
        if not merged.get("ec_password"):
            merged["ec_password"] = self._fallback_password
        return merged

    # -- 目录 ---------------------------------------------------------
    def ensure_dirs(self, settings=None):
        settings = settings or self.settings()
        for path in (self.var_dir, self.config_dir,
                     os.path.join(self.var_dir, "home"),
                     os.path.join(self.config_dir, "Temp"),
                     os.path.join(self.config_dir, "Incoming"),
                     settings["incoming_dir"], settings["temp_dir"]):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError:
                pass
        for shared in settings.get("shared_dirs") or []:
            try:
                os.makedirs(shared, exist_ok=True)
            except OSError:
                pass

    # -- 配置生成 -----------------------------------------------------
    def conf_text(self, settings=None, shared_dirs=None):
        """按模板 + 面板设置渲染 amule.conf 内容。"""
        settings = settings or self.settings()
        overrides = {
            ("eMule", "Nick"): settings["nick"],
            ("eMule", "Port"): str(_as_int(settings["tcp_port"], 4662)),
            ("eMule", "UDPPort"): str(_as_int(settings["udp_port"], 4672)),
            ("eMule", "UDPEnable"): "1",
            ("eMule", "Autoconnect"): "1" if _as_bool(settings.get("autoconnect"), True) else "0",
            ("eMule", "ConnectToED2K"): "1" if _as_bool(settings.get("connect_ed2k"), True) else "0",
            ("eMule", "ConnectToKad"): "1" if _as_bool(settings.get("connect_kad"), True) else "0",
            ("eMule", "MaxDownload"): str(max(0, _as_int(settings.get("max_download")))),
            ("eMule", "MaxUpload"): str(max(0, _as_int(settings.get("max_upload")))),
            ("eMule", "MaxConnections"): str(max(1, _as_int(settings.get("max_connections"), 500))),
            ("eMule", "MaxSourcesPerFile"): str(max(1, _as_int(settings.get("max_sources"), 300))),
            ("eMule", "TempDir"): settings["temp_dir"],
            ("eMule", "IncomingDir"): settings["incoming_dir"],
            ("eMule", "OSDirectory"): self.config_dir + os.sep,
            ("eMule", "ICH"): "1" if _as_bool(settings.get("ich"), True) else "0",
            ("eMule", "AICHTrust"): "0" if _as_bool(settings.get("aich"), True) else "1",
            ("eMule", "AddNewFilesPaused"): "1" if _as_bool(settings.get("add_paused")) else "0",
            ("eMule", "UPnPEnabled"): "1" if _as_bool(settings.get("upnp")) else "0",
            # 关键：绝不让 aMule 自己下载（自带 HTTP 客户端在代理网络下会触发 wx 断言崩溃）
            ("eMule", "NewVersionCheck"): "0",
            ("eMule", "OnlineSignature"): "0",
            ("eMule", "IPFilterAutoLoad"): "1" if _as_bool(settings.get("ipfilter"), True) else "0",
            ("eMule", "KadNodesUrl"): settings.get("nodes_dat_url") or "",
            ("eMule", "Ed2kServersUrl"): settings.get("server_met_url") or "",
            # 面板以 root 跑，amuled 也是；ConfirmExit 关掉以免 daemon 出现交互等待
            ("eMule", "ConfirmExit"): "0",
            ("eMule", "CreateSparseFiles"): "1",
            ("eMule", "CheckDiskspace"): "0",
            ("ExternalConnect", "AcceptExternalConnections"): "1",
            ("ExternalConnect", "ECAddress"): "127.0.0.1",
            ("ExternalConnect", "ECPort"): str(_as_int(settings["ec_port"], 4712)),
            ("ExternalConnect", "ECPassword"): _md5_hex(settings["ec_password"]),
            ("ExternalConnect", "UPnPECEnabled"): "0",
            # 关掉它才能从 EC 拿到未在传输的下载来源，详情页要用
            ("ExternalConnect", "TransmitOnlyUploadingClients"): "0",
            ("WebServer", "Enabled"): "0",
            ("Obfuscation", "IsClientCryptLayerSupported"): "1",
            ("Obfuscation", "IsCryptLayerRequested"): "1",
        }
        lines = []
        for section, entries in CONF_TEMPLATE:
            lines.append("[%s]" % section)
            for key, value in entries:
                override = overrides.get((section, key))
                lines.append("%s=%s" % (key, override if override is not None else value))
            lines.append("")
        text = "\n".join(lines).rstrip("\n") + "\n"
        return text

    def write_conf(self, settings=None):
        """原子写 amule.conf + shareddir.dat，返回配置路径。"""
        settings = settings or self.settings()
        self.ensure_dirs(settings)
        target = os.path.join(self.config_dir, "amule.conf")
        text = self.conf_text(settings)
        tmp = target + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
        self.write_shareddir(settings)
        return target

    def write_shareddir(self, settings=None):
        """写 shareddir.dat：每行一个待扫目录，子目录已摊平。

        aMule 只扫每个目录的顶层（见 expand_shared_dirs），所以这份清单每次都要
        重新展开 —— 用户的目录树是会变的，光靠"amule.conf 没变就不写"会漏掉
        新增的子目录。prepare() 每次启动都会无条件调这个方法。
        """
        settings = settings or self.settings()
        shared_path = os.path.join(self.config_dir, "shareddir.dat")
        shared = expand_shared_dirs(settings.get("shared_dirs") or [])
        body = "\n".join(shared) + ("\n" if shared else "")
        try:
            with open(shared_path, "r", encoding="utf-8") as handle:
                if handle.read() == body:
                    return shared_path          # 没变化就别动文件，省掉一次落盘
        except OSError:
            pass
        tmp_shared = shared_path + ".tmp"
        with open(tmp_shared, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_shared, shared_path)
        return shared_path

    # -- 可执行文件 ---------------------------------------------------
    def runtime_binary(self):
        """返回 (amuled 路径, 需要追加的 LD_LIBRARY_PATH 或 None)。"""
        if self.runtime_dir:
            # 一个包里同时带 x86 与 ARM 两套引擎（runtime/amd64、runtime/arm64），
            # 按本机 CPU 选；找不到再退回"单架构平铺"布局（runtime/usr/bin/amuled）。
            bases = []
            sub = _runtime_arch_subdir()
            if sub:
                bases.append(os.path.join(self.runtime_dir, sub))
            bases.append(self.runtime_dir)
            for base in bases:
                candidate = os.path.join(base, "usr", "bin", "amuled")
                if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                    return candidate, _runtime_libdir(base)
        for path in ("/usr/bin/amuled", "/usr/local/bin/amuled", "/usr/sbin/amuled"):
            if os.path.isfile(path) and os.access(path, os.X_OK):
                return path, None
        raise EmuleError("找不到 amuled 可执行文件：运行时不完整（app/runtime/usr/bin/amuled），"
                         "系统里也没有 /usr/bin/amuled")

    def env(self):
        env = dict(os.environ)
        env["HOME"] = os.path.join(self.var_dir, "home")
        env["LC_ALL"] = "C.UTF-8"
        env["LANG"] = "C.UTF-8"
        binary, libdir = self.runtime_binary()
        if libdir:
            old = env.get("LD_LIBRARY_PATH") or ""
            env["LD_LIBRARY_PATH"] = (libdir + (":" + old if old else ""))
        return env

    # -- 端口检查 -----------------------------------------------------
    @staticmethod
    def _port_free(port, socktype, host="0.0.0.0"):
        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socktype)
            if socktype == socket.SOCK_STREAM:
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, int(port)))
            return True
        except OSError:
            return False
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

    def check_ports(self, settings=None):
        """启动前检查三个端口；被占用时抛 EmuleError 指明端口。"""
        settings = settings or self.settings()
        conflicts = []
        tcp_port = _as_int(settings["tcp_port"], 4662)
        udp_port = _as_int(settings["udp_port"], 4672)
        ec_port = _as_int(settings["ec_port"], 4712)
        if not self._port_free(tcp_port, socket.SOCK_STREAM):
            conflicts.append("TCP %d（eD2k 下载端口）" % tcp_port)
        if not self._port_free(udp_port, socket.SOCK_DGRAM):
            conflicts.append("UDP %d（eD2k 网络端口）" % udp_port)
        if not self._port_free(ec_port, socket.SOCK_STREAM, host="127.0.0.1"):
            conflicts.append("TCP %d（EC 控制端口）" % ec_port)
        if conflicts:
            raise EmuleError("端口已被占用，无法启动引擎：%s。请在设置里换端口，"
                             "或先停掉占用进程。" % "、".join(conflicts))

    # -- 进程发现 -----------------------------------------------------
    def find_pid(self):
        """找到当前配置目录对应的 amuled 进程（优先 pid 文件，其次扫 /proc）。"""
        try:
            with open(self.pid_file, "r", encoding="utf-8") as handle:
                pid = int((handle.read() or "0").strip() or 0)
        except (OSError, ValueError):
            pid = 0
        if pid and self._pid_matches(pid):
            return pid
        return self._scan_proc()

    def _pid_matches(self, pid):
        if self._proc_state(pid) in (None, "Z"):
            return False
        try:
            with open("/proc/%d/cmdline" % pid, "rb") as handle:
                cmdline = handle.read()
        except OSError:
            return False
        if b"amuled" not in cmdline:
            return False
        return self.config_dir.encode("utf-8") in cmdline

    def _scan_proc(self):
        try:
            entries = os.listdir("/proc")
        except OSError:
            return 0
        for entry in entries:
            if not entry.isdigit():
                continue
            if self._pid_matches(int(entry)):
                return int(entry)
        return 0

    def _uptime(self, pid):
        """进程已运行秒数（读 /proc/<pid>/stat 的 starttime）。"""
        try:
            with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as handle:
                fields = handle.read().rsplit(")", 1)[1].split()
            start_ticks = float(fields[19])
            with open("/proc/uptime", "r", encoding="utf-8") as handle:
                system_uptime = float(handle.read().split()[0])
            hz = float(os.sysconf("SC_CLK_TCK")) or 100.0
            return max(0, int(system_uptime - start_ticks / hz))
        except (OSError, IndexError, ValueError):
            return 0

    def status(self):
        pid = self.find_pid()
        return {
            "running": bool(pid),
            "pid": pid,
            "uptime": self._uptime(pid) if pid else 0,
        }

    # -- 启动/停止 ----------------------------------------------------
    def wait_ec(self, port=None, timeout=START_TIMEOUT):
        """等 EC 端口可以 connect；返回是否就绪。"""
        settings = self.settings()
        port = int(port or _as_int(settings["ec_port"], 4712))
        deadline = time.time() + timeout
        while time.time() < deadline:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1.0)
            try:
                sock.connect(("127.0.0.1", port))
                return True
            except OSError:
                time.sleep(0.3)
            finally:
                try:
                    sock.close()
                except OSError:
                    pass
        return False

    def start(self, timeout=START_TIMEOUT):
        """启动 amuled；已在运行则 no-op。返回状态字典。"""
        with self._lock:
            self._want_running = True
            pid = self.find_pid()
            if pid:
                return {"started": False, "running": True, "pid": pid, "uptime": self._uptime(pid)}
            settings = self.settings()
            self.write_conf(settings)
            self.check_ports(settings)
            binary, _libdir = self.runtime_binary()
            env = self.env()
            # 轮转必须赶在 Popen 之前：此刻磁盘上没有任何进程持有 amuled.log 的 fd，
            # os.replace 是安全的。失败只影响日志大小，绝不能因此让引擎起不来。
            if self.rotate_log_if_needed():
                self._log("info", "amuled.log 超过 %d MB，已轮转为 %s.1"
                          % (AMULED_LOG_MAX_BYTES // (1024 * 1024), self.log_file))
            try:
                log_handle = open(self.log_file, "ab", buffering=0)
            except OSError as exc:
                raise EmuleError("无法写入引擎日志 %s：%s" % (self.log_file, exc))
            try:
                log_handle.write(("\n===== %s 启动 amuled (%s) =====\n"
                                  % (time.strftime("%Y-%m-%d %H:%M:%S"), binary)).encode("utf-8"))
                process = subprocess.Popen(
                    [binary, "-c", self.config_dir, "-o"],
                    cwd=self.config_dir,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=log_handle,
                    stderr=log_handle,
                    start_new_session=True,
                )
            except OSError as exc:
                raise EmuleError("启动 amuled 失败：%s" % exc)
            finally:
                try:
                    log_handle.close()
                except OSError:
                    pass
            pid = process.pid
            try:
                with open(self.pid_file, "w", encoding="utf-8") as handle:
                    handle.write("%d\n" % pid)
            except OSError:
                pass
            # 等 EC 端口就绪；进程提前退出就报错（附日志尾巴）
            ec_port = _as_int(settings["ec_port"], 4712)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if process.poll() is not None:
                    self._log("error", "amuled 启动后立即退出（exit=%s）" % process.returncode)
                    raise EmuleError("amuled 启动后立即退出（exit=%s），请查看 %s"
                                     % (process.returncode, self.log_file))
                if self.wait_ec(ec_port, timeout=1.0):
                    self._log("info", "amuled 已启动，pid=%d，EC 端口 %d 就绪" % (pid, ec_port))
                    return {"started": True, "running": True, "pid": pid, "uptime": 0}
            self._log("error", "amuled 启动超时：EC 端口 %d 未就绪" % ec_port)
            raise EmuleError("amuled 启动超时：%.0f 秒内 EC 端口 %d 未就绪，请查看 %s"
                             % (timeout, ec_port, self.log_file))

    def stop(self, timeout=STOP_TIMEOUT):
        """SIGTERM → 等 timeout → SIGKILL。"""
        with self._lock:
            self._want_running = False
            pid = self.find_pid()
            if not pid:
                self._remove_pid_file()
                return {"stopped": False, "running": False, "pid": 0}
            self._log("info", "正在停止 amuled，pid=%d" % pid)
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError as exc:
                self._log("warn", "向 amuled 发送 SIGTERM 失败：%s" % exc)
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not self._pid_alive(pid):
                    self._remove_pid_file()
                    self._log("info", "amuled 已退出")
                    return {"stopped": True, "running": False, "pid": pid}
                time.sleep(0.25)
            self._log("warn", "amuled 未在 %.0f 秒内退出，强制 SIGKILL" % timeout)
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
            for _ in range(40):
                if not self._pid_alive(pid):
                    break
                time.sleep(0.1)
            self._remove_pid_file()
            return {"stopped": True, "running": self._pid_alive(pid), "pid": pid, "killed": True}

    def restart(self, timeout=START_TIMEOUT):
        self.stop()
        return self.start(timeout=timeout)

    @staticmethod
    def _proc_state(pid):
        """返回 /proc/<pid>/stat 的状态字符（R/S/D/Z…）；进程不存在返回 None。"""
        try:
            with open("/proc/%d/stat" % pid, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read().rsplit(")", 1)[1].split()[0]
        except (OSError, IndexError):
            return None

    def _pid_alive(self, pid):
        """进程还活着吗？僵尸进程算已退出（顺手回收，避免 stop 白等 20 秒）。"""
        state = self._proc_state(pid)
        if state is None or state == "Z":
            try:
                os.waitpid(pid, os.WNOHANG)
            except OSError:
                pass
            return False
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def _remove_pid_file(self):
        try:
            os.unlink(self.pid_file)
        except OSError:
            pass

    # -- 日志 ---------------------------------------------------------
    def clear_log(self, include_backup=True):
        """清空引擎日志。返回 {removed:[...], freed:字节}。

        引擎正在跑的时候**不能 unlink amuled.log**：aMule 用 open("ab") 拿到的
        fd 一直指着旧 inode，删掉目录项之后磁盘空间不释放，用户看到的就是
        "清了但没变小"。所以运行中改成 truncate（把文件截成 0 字节），
        同一个 inode 继续被写，日志从头开始、空间立刻回收。

        没在跑就直接删文件（顺带删 .1），少一个空文件。
        """
        removed = []
        freed = 0
        paths = [self.log_file]
        if include_backup:
            paths.append(self.log_file + ".1")
        running = bool(self.find_pid())
        for path in paths:
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            try:
                if running and path == self.log_file:
                    # 运行中：截断而不是删除，保住 inode
                    with open(path, "wb"):
                        pass
                else:
                    os.remove(path)
                removed.append(os.path.basename(path))
                freed += size
            except OSError as exc:
                self._log("warn", "清理引擎日志失败（%s）：%s" % (os.path.basename(path), exc))
        if removed:
            self._log("info", "清理引擎日志：%s（回收 %.1f MB）"
                      % ("，".join(removed), freed / 1024.0 / 1024.0))
        return {"removed": removed, "count": len(removed), "freed": freed}

    def rotate_log_if_needed(self):
        """amuled.log 超过 AMULED_LOG_MAX_BYTES 就滚成 .1；返回是否真的滚了。

        只能在 amuled **没在跑**的时候调用（start() 里已经确认过没有 pid）。
        aMule 启动时自己 open("ab") 拿到 fd，之后一直写到进程退出；运行期间从外部
        os.replace 只是把目录项换掉，旧 inode 仍被它的 fd 引用着，磁盘空间不释放，
        排查起来反而更乱。

        amuled.log 是引擎唯一的日志出口，轮转写坏了就等于引擎没有日志，所以这里
        任何 OSError（文件不存在、权限不足、被占用）都只是「这次不轮转」，
        绝不向调用方抛异常。
        """
        try:
            if os.path.getsize(self.log_file) <= AMULED_LOG_MAX_BYTES:
                return False
            os.replace(self.log_file, self.log_file + ".1")
            return True
        except OSError:
            return False

    def _log(self, level, message):
        line = "%s [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, message)
        try:
            with open(self.panel_log, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass
        if self._logger is not None:
            try:
                self._logger(level, message)
            except Exception:                          # noqa: BLE001
                pass
        return line

    # -- 看护 ---------------------------------------------------------
    def start_watchdog(self):
        """启动守护线程（幂等）。"""
        with self._lock:
            if self._watch_thread is not None and self._watch_thread.is_alive():
                return False
            self._watch_stop.clear()
            self._watch_thread = threading.Thread(target=self._watch_loop, name="amuled-watchdog",
                                                  daemon=True)
            self._watch_thread.start()
            return True

    def stop_watchdog(self):
        with self._lock:
            self._watch_stop.set()
            thread, self._watch_thread = self._watch_thread, None
        if thread is not None:
            thread.join(timeout=3.0)

    def _watch_loop(self):
        attempt = 0
        while not self._watch_stop.wait(WATCH_INTERVAL):
            if not self._want_running:
                continue
            if self.find_pid():
                attempt = 0
                continue
            now = time.time()
            self._restarts = [stamp for stamp in self._restarts if now - stamp < 3600]
            if len(self._restarts) >= MAX_RESTART_PER_HOUR:
                if attempt == 0:
                    self._log("error", "一小时内的自动重启已达 %d 次上限，停止重启，请手工排查"
                              % MAX_RESTART_PER_HOUR)
                attempt = 99
                continue
            delay = BACKOFF[min(attempt, len(BACKOFF) - 1)]
            if attempt < 99:
                self._log("warn", "检测到 amuled 已退出，%.0f 秒后第 %d 次自动重启"
                          % (delay, attempt + 1))
            if self._watch_stop.wait(delay):
                return
            if self.find_pid():
                continue
            self._restarts.append(time.time())
            try:
                self.start()
                attempt = min(attempt + 1, len(BACKOFF))
            except EmuleError as exc:
                self._last_error = str(exc)
                attempt = min(attempt + 1, len(BACKOFF))
                if attempt >= 99:
                    attempt = 0


def _runtime_arch_subdir():
    """本机 CPU 对应的运行时子目录名：amd64 / arm64；无法识别返回空串。"""
    try:
        machine = platform.machine().lower()
    except Exception:  # noqa: BLE001 - 极端环境下拿不到也不该炸
        return ""
    mapping = {
        "x86_64": "amd64", "amd64": "amd64", "i386": "amd64", "i686": "amd64",
        "aarch64": "arm64", "arm64": "arm64", "armv8l": "arm64", "armv7l": "arm64",
    }
    return mapping.get(machine, "")


def _runtime_libdir(base):
    """在给定运行时根下找共享库目录（x86_64-linux-gnu / aarch64-linux-gnu）。"""
    libroot = os.path.join(base, "usr", "lib")
    if os.path.isdir(libroot):
        for name in sorted(os.listdir(libroot)):
            cand = os.path.join(libroot, name)
            if os.path.isdir(cand) and ("-linux-gnu" in name):
                return cand
    return os.path.join(libroot, "x86_64-linux-gnu")
