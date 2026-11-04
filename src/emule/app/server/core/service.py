# -*- coding: utf-8 -*-
"""EmuleService —— eMule 引擎领域门面（docs/CONTRACT.md §4）。

panel-api 只依赖本模块，不直接碰 EC 协议或 amuled 进程：
  * 所有方法同步、线程安全；
  * 失败抛 EmuleError(中文原因)，引擎没起来抛 EmuleOffline；
  * 字段名与 CONTRACT §3 的 JSON 完全一致（hash 大写 32 位、时间 Unix 秒、percent 0..1）。
"""

import collections
import os
import re
import shutil
import threading
import time
import uuid

try:                                                  # 打包运行：core/ 作为包
    from .ec import (
        ECClient, EmuleError, EmuleOffline, EmuleTimeout, Op, Tag, Detail, SearchType, Prefs,
        PARTSIZE, partfile_record, client_record, server_record, search_record,
        sharedfile_record, connstate_record, uint32_to_ip,
        tag_string, tag_uint, tag_node,
    )
    from .amule_ctl import AmuleCtl, random_password
    from . import bootstrap
except ImportError:                                    # 开发/自测：core/ 直接进 sys.path
    from ec import (                                   # type: ignore
        ECClient, EmuleError, EmuleOffline, EmuleTimeout, Op, Tag, Detail, SearchType, Prefs,
        PARTSIZE, partfile_record, client_record, server_record, search_record,
        sharedfile_record, connstate_record, uint32_to_ip,
        tag_string, tag_uint, tag_node,
    )
    from amule_ctl import AmuleCtl, random_password     # type: ignore
    import bootstrap                                    # type: ignore


# ---------------------------------------------------------------- 常量映射

#: aMule EPartFileStatus（Constants.h PS_*）
PS_READY = 0
PS_EMPTY = 1
PS_WAITINGFORHASH = 2
PS_HASHING = 3
PS_ERROR = 4
PS_INSUFFICIENT = 5
PS_UNKNOWN = 6
PS_PAUSED = 7
PS_COMPLETING = 8
PS_COMPLETE = 9
PS_ALLOCATING = 10

#: 下载优先级（Constants.h PR_*）
PR_LOW = 0
PR_NORMAL = 1
PR_HIGH = 2
PR_VERYHIGH = 3
PR_VERYLOW = 4
PR_AUTO = 5

#: EC 里 partfile 的 PRIO 字段：自动优先级会被加上 10（ECSpecialCoreTags.cpp）
PRIO_AUTO_OFFSET = 10

#: 服务器优先级（Server.h SRV_PR_*）
SRV_PR_NORMAL = 0
SRV_PR_HIGH = 1
SRV_PR_LOW = 2

#: 下载状态词表（CONTRACT §3 固定）
_STATUS_BY_CODE = {
    PS_READY: "waiting",
    PS_EMPTY: "waiting",
    PS_WAITINGFORHASH: "hashing",
    PS_HASHING: "hashing",
    PS_ERROR: "error",
    PS_INSUFFICIENT: "error",
    PS_UNKNOWN: "waiting",
    PS_PAUSED: "paused",
    PS_COMPLETING: "completing",
    PS_COMPLETE: "complete",
    PS_ALLOCATING: "waiting",
}

#: PRIO 字段 → 面板优先级
_PRIORITY_BY_CODE = {
    0: "low",        # PR_LOW
    1: "normal",     # PR_NORMAL
    2: "high",       # PR_HIGH
    3: "high",       # PR_VERYHIGH
    4: "low",        # PR_VERYLOW
    5: "auto",       # PR_AUTO
}

_PRIORITY_RAW = {
    "low": PR_LOW,
    "normal": PR_NORMAL,
    "high": PR_HIGH,
    "veryhigh": PR_VERYHIGH,
    "verylow": PR_VERYLOW,
    "auto": PR_AUTO,
}

_SERVER_PRIORITY = {SRV_PR_NORMAL: "normal", SRV_PR_HIGH: "high", SRV_PR_LOW: "low"}
_SERVER_PRIORITY_RAW = {"normal": SRV_PR_NORMAL, "high": SRV_PR_HIGH, "low": SRV_PR_LOW}

#: 客户端下载/上传状态（updownclient.h EDownloadState / EUploadState）
_CLIENT_DOWNLOAD_STATE = {
    0: "none", 1: "connecting", 2: "transferring", 3: "queued", 4: "waiting",
    5: "idle", 6: "no_needed_parts", 7: "pending", 8: "banned", 9: "error",
    10: "too_many_connections", 11: "connecting", 12: "requesting",
}
_CLIENT_UPLOAD_STATE = {
    0: "none", 1: "waiting", 2: "uploading", 3: "pending", 4: "getting_hash",
    5: "uploading", 6: "banned", 7: "error", 8: "queued", 9: "too_many",
}

#: CONTRACT 的 method → aMule 搜索的文件类型筛选（空 = 不限类型，按文件名搜）
_SEARCH_METHOD = {
    "name": "",
    "any": "",
    "audio": "Audio",
    "video": "Video",
    "pro": "Pro",
    "program": "Pro",
    "doc": "Doc",
    "document": "Doc",
    "image": "Image",
    "arc": "Arc",
    "archive": "Arc",
}

#: 搜索类型映射（CONTRACT 的 kind → EC_SEARCH_TYPE）
_SEARCH_KIND = {
    "server": SearchType.LOCAL,
    "local": SearchType.LOCAL,
    "global": SearchType.GLOBAL,
    "kad": SearchType.KAD,
}

#: 搜索结果按扩展名分类（前端筛选用）
_EXT_TYPE = {
    "audio": ("mp3", "flac", "wav", "ape", "aac", "ogg", "wma", "m4a", "mpc", "ra"),
    "video": ("avi", "mpg", "mpeg", "mkv", "mp4", "m4v", "mov", "wmv", "rm", "rmvb",
              "ts", "vob", "flv", "webm", "ogm"),
    "image": ("jpg", "jpeg", "png", "gif", "bmp", "tif", "tiff", "psd", "webp"),
    "archive": ("zip", "rar", "7z", "tar", "gz", "bz2", "xz", "iso", "cab", "ace"),
    "document": ("pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx", "txt", "epub",
                 "mobi", "chm", "djvu", "rtf", "odt"),
    "program": ("exe", "msi", "deb", "rpm", "apk", "dmg", "bin", "img", "run", "appimage"),
}


def _ext_of(name):
    base = os.path.basename(name or "")
    if "." not in base:
        return ""
    return base.rsplit(".", 1)[1].lower()


def _type_of(name):
    ext = _ext_of(name)
    for group, extensions in _EXT_TYPE.items():
        if ext in extensions:
            return group
    return "other"


def _file_ext(name):
    return _ext_of(name)


def _clamp(value, low, high):
    return max(low, min(high, value))


# ---------------------------------------------------------------- 删除任务
#: aMule 在 Temp 下的分片数据文件名：NNN.part / .part.met / .part.met.bak / .part.met.seeds
_PART_FILE_RE = re.compile(r"^\d{3,6}\.part(\.met(\.bak|\.seeds)?)?$")

#: 32 位大写十六进制文件哈希
_HASH_RE = re.compile(r"^[0-9A-F]{32}$")

#: delete_data=False 时保留数据的子目录名（<var_dir>/deleted/<HASH>/）
DELETED_DIRNAME = "deleted"

#: PAUSE+STOP 之后等 aMule 释放文件句柄的时长（秒）
PARTFILE_STOP_WAIT = 0.15


def _within_root(path, root):
    """path 是否落在 root 之内（都应是 realpath 过的绝对路径）。"""
    if not path or not root:
        return False
    root = root.rstrip(os.sep) or os.sep
    return path == root or path.startswith(root + os.sep)


# aMule 的日志行形如 " 2026-11-03 01:30:19: 文本"，重要行前面还会加 "!"
# ---------------------------------------------------------------- 统计项文案
# aMule 的统计节点名字是 printf 格式串（"Uptime: %s"、"Total: %i Known: %i"、
# "Server Occupation: %.2f%%"），原样展示会带 %s。这里统一清洗成干净标签，
# 再给一层中文名（未命中留空串，由前端回退英文，绝不瞎翻）。

#: printf 格式符（含字面 %%）
_STAT_FORMAT_SPEC = re.compile(r"%[-+ 0#]*\d*(?:\.\d+)?(?:ll|l|hh|h|z|j|t)?[diouxXeEfFgGaAcsp%]")

#: 少数 aMule 原始标签的格式符组合太怪，直接给一个干净的英文名（避免清洗出怪串）
_STATS_LABEL_OVERRIDE = {
    "LowID: %u (%.2f%% Total %.2f%% Known)": "Low ID (Total / Known)",
    "SecIdent On/Off: %u (%.2f%%) : %u (%.2f%%)": "SecIdent On/Off",
}

#: 统计项中文名；键是清洗后的英文标签（按 aMule 2.3.3 Statistics.cpp 的 47 个
#: 统计标签 + 实测 52 项归纳，覆盖所有可能出现的项）
_STATS_NAME_ZH = {
    "Uptime": "运行时长",
    "Session UL:DL Ratio (Total)": "本次上传/下载比",
    "Uploaded Data (Session (Total))": "上传数据（本次会话）",
    "Downloaded Data (Session (Total))": "下载数据（本次会话）",
    "Total Overhead (Packets)": "总协议开销（数据包）",
    "File Request Overhead (Packets)": "文件请求开销（数据包）",
    "Source Exchange Overhead (Packets)": "源交换开销（数据包）",
    "Server Overhead (Packets)": "服务器开销（数据包）",
    "Kad Overhead (Packets)": "Kad 开销（数据包）",
    "Crypt overhead (UDP)": "加密开销（UDP）",
    "Active Uploads": "活跃上传",
    "Waiting Uploads": "等待上传",
    "Total successful upload sessions": "累计成功上传会话",
    "Total failed upload sessions": "累计失败上传会话",
    "Found Sources": "已发现来源",
    "Active Downloads (chunks)": "活跃下载（分块）",
    "Average download rate (Session)": "平均下载速率（本次会话）",
    "Average upload rate (Session)": "平均上传速率（本次会话）",
    "Max download rate (Session)": "最大下载速率（本次会话）",
    "Max upload rate (Session)": "最大上传速率（本次会话）",
    "Reconnects": "重连次数",
    "Time Since First Transfer": "距首次传输时长",
    "Connected To Server Since": "当前服务器连接时长",
    "Active Connections (estimate)": "活跃连接数（估算）",
    "Max Connection Limit Reached": "连接数上限触达次数",
    "Average Connections (estimate)": "平均连接数（估算）",
    "Peak Connections (estimate)": "峰值连接数（估算）",
    "Total / Known": "总计 / 已知",
    "Unknown": "未知",
    "Filtered": "已过滤",
    "Banned": "已封禁",
    "Working Servers": "可用服务器",
    "Failed Servers": "失效服务器",
    "Total": "总计",
    "Deleted Servers": "已删除服务器",
    "Filtered Servers": "已过滤服务器",
    "Users on Working Servers": "可用服务器在线用户",
    "Files on Working Servers": "可用服务器共享文件",
    "Total Users": "用户总数",
    "Total Files": "文件总数",
    "Server Occupation": "服务器占用率",
    "Number of Shared Files": "共享文件数量",
    "Total size of Shared Files": "共享文件总大小",
    "Average file size": "平均文件大小",
    "Average upload time": "平均上传时长",
    "Low ID (Total / Known)": "低 ID（总计 / 已知）",
    "SecIdent On/Off": "安全身份验证 开/关",
}

#: 统计分组路径中文化（未知段原样保留）
_STATS_GROUP_ZH = {
    "Statistics": "统计",
    "Transfer": "传输",
    "Uploads": "上传",
    "Downloads": "下载",
    "Connection": "连接",
    "Clients": "客户端",
    "Servers": "服务器",
    "Shared Files": "共享文件",
    "Kad": "Kad",
    "Version": "版本",
    "Operating System": "操作系统",
    "Unknown": "未知",
    "Not Received": "未获取",
}


def clean_stat_label(text, value=""):
    """把 aMule 的 printf 格式串标签清洗成干净名称。

    * 单个格式符在尾部（"Uptime: %s"、"Server Occupation: %.2f%%"）→ 直接去掉；
    * 单个格式符在开头/中间 → 用真实 value 代入（保留标签本来的语义）；
    * 多个格式符（"Total: %i Known: %i"）→ 拆成片段用 " / " 连接，得到
      "Total / Known" 这类干净标签，绝不把格式符漏给前端。
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    if raw in _STATS_LABEL_OVERRIDE:
        return _STATS_LABEL_OVERRIDE[raw]
    specs = list(_STAT_FORMAT_SPEC.finditer(raw))
    if not specs:
        return raw
    trim_chars = " :：,，/|-"
    if len(specs) == 1:
        spec = specs[0]
        prefix, suffix = raw[:spec.start()], raw[spec.end():]
        if not suffix.strip(trim_chars):
            label = prefix.strip(trim_chars).strip()
            return label or raw
        if not prefix.strip(trim_chars):
            return " ".join(piece for piece in (str(value).strip(), suffix.strip(trim_chars))
                            if piece)
        if not suffix.strip(trim_chars):
            return " ".join(piece for piece in (prefix.strip(trim_chars), str(value).strip())
                            if piece)
        return " ".join(piece for piece in (prefix.strip(trim_chars), str(value).strip(),
                                            suffix.strip(trim_chars)) if piece)
    parts, last = [], 0
    for spec in specs:
        parts.append(raw[last:spec.start()])
        last = spec.end()
    parts.append(raw[last:])
    fragments = [part.strip(trim_chars).strip() for part in parts]
    fragments = [fragment for fragment in fragments if fragment]
    if not fragments:
        return raw
    return " / ".join(fragments)


def stat_name_zh(clean_name):
    """统计项中文名；未命中返回空串（前端回退英文）。"""
    return _STATS_NAME_ZH.get((clean_name or "").strip(), "")


def stat_group_zh(group):
    """统计分组路径中文化，逐段翻译，未知段保留原文。"""
    if not group:
        return ""
    segments = []
    for segment in group.split("/"):
        cleaned = clean_stat_label(segment)
        if not cleaned:
            continue
        segments.append(_STATS_GROUP_ZH.get(cleaned, cleaned))
    return " / ".join(segments)


#: 统计 value 里会出现的固定英文短语（aMule 用 CFormat 直接输出的占位文案）。
#: 只做整条精确匹配替换，数值/单位/Kad 状态字符串等一律不动。
_STATS_VALUE_ZH = {
    "Not available": "暂无数据",
    "Never": "从未",
    "Unknown": "未知",
    "Disabled": "已禁用",
    "Enabled": "已启用",
}


def stat_value_zh(value):
    """把整条固定英文短语的 value 换成中文；其它原样返回（不改数值格式化）。"""
    if not isinstance(value, str):
        return value
    stripped = value.strip()
    replacement = _STATS_VALUE_ZH.get(stripped)
    if replacement is None:
        return value
    return replacement


def _env_path(*names):
    """按顺序取第一个非空环境变量值（用于 fpk 运行时路径解析）。"""
    for name in names:
        value = os.environ.get(name)
        if value:
            return os.path.abspath(os.path.expanduser(value))
    return ""


def default_var_dir():
    """持久数据目录。

    优先级：EMULE_VAR / FNEMULE_VAR 环境变量 → fnOS 包变量 TRIM_PKGVAR →
    默认 /var/apps/fn-emule/var。cmd/main 可以用 EMULE_VAR 覆盖。
    """
    explicit = _env_path("EMULE_VAR", "FNEMULE_VAR", "TRIM_PKGVAR")
    if explicit:
        return explicit
    # 没被包框架拉起时的兜底：fnOS 实际把 TRIM_PKGVAR 放在 /usr/local/apps/@appdata 下
    for fallback in ("/var/apps/fn-emule/var", "/usr/local/apps/@appdata/fn-emule"):
        if os.path.isdir(fallback):
            return fallback
    return "/var/apps/fn-emule/var"


def default_runtime_dir(module_dir):
    """内置 amuled 运行时目录（含 usr/bin/amuled）。

    优先级：EMULE_APP_HOME / TRIM_APPDEST 环境变量下的 app/runtime（或 runtime）→
    否则按本文件位置回推 ../../runtime（打包后即 target/app/runtime）。
    """
    def _has_amuled(path):
        return os.path.isfile(os.path.join(path, "usr", "bin", "amuled"))

    root = _env_path("EMULE_APP_HOME", "TRIM_APPDEST")
    if root:
        candidates = [os.path.join(root, relative)
                      for relative in ("app/runtime", "runtime", "target/app/runtime")]
        for candidate in candidates:
            if os.path.isdir(candidate) and _has_amuled(candidate):
                return candidate
        for candidate in candidates:
            if os.path.isdir(candidate):
                return candidate
        return candidates[0]
    # 没设环境变量时按本文件位置回推：
    #   仓库布局   src/emule/app/server/core → src/emule/app/runtime
    #   装包布局   <APPDEST>/server/core     → <APPDEST>/runtime
    for ups in (2, 3, 4):
        candidate = os.path.abspath(os.path.join(module_dir, *([os.pardir] * ups), "runtime"))
        if _has_amuled(candidate):
            return candidate
    return os.path.abspath(os.path.join(module_dir, os.pardir, os.pardir, "runtime"))


_LOG_LINE = re.compile(r"^[\s!]*(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}):\s?(.*)$")
_LOG_LEVEL_PREFIX = re.compile(r"^(error|warning|warn|critical|严重错误|错误|警告)\s*[:：]\s*(.*)$",
                               re.IGNORECASE)
_ERROR_WORDS = ("error", "failed", "failure", "fatal", "critical", "错误", "失败", "异常")
_WARN_WORDS = ("warn", "警告", "警告：", "deprecated")


class EmuleService(object):
    """引擎门面：进程控制 + EC 数据读写 + 面板需要的所有领域视图。"""

    def __init__(self, settings_provider, var_dir=None, runtime_dir=None, config_dir=None,
                 client=None):
        self._settings_provider = settings_provider or (lambda: {})
        self.module_dir = os.path.dirname(os.path.abspath(__file__))
        self.var_dir = os.path.abspath(var_dir) if var_dir else default_var_dir()
        self.config_dir = os.path.abspath(config_dir or os.path.join(self.var_dir, "amule"))
        self.runtime_dir = (os.path.abspath(runtime_dir) if runtime_dir
                           else default_runtime_dir(self.module_dir))
        self._ctl = AmuleCtl(self._settings_provider, self.var_dir, self.config_dir,
                             self.runtime_dir)
        self._lock = threading.RLock()
        self._ec = client
        self._searches = collections.OrderedDict()
        self._search_seq = 0
        self._history = collections.deque(maxlen=240)
        self._last_history_ts = 0
        self._prepared = False
        self._last_ec_error = ""
        # 会话流量基线：{pid, down, up}，用来把累计字节换算成“本次引擎会话”的字节
        self._session_base = None
        # 后台补齐引导文件的线程与结果说明
        self._bg_thread = None
        self._bg_notes = []

    # ------------------------------------------------------------ 设置
    def _settings(self):
        try:
            data = self._settings_provider() or {}
        except Exception:                               # noqa: BLE001 - 设置读坏了也要能干活
            data = {}
        if not isinstance(data, dict):
            data = {}
        return data

    def _engine_settings(self):
        return self._ctl.settings()


    # ------------------------------------------------------------ 连接
    def _ec_client(self):
        engine = self._engine_settings()
        with self._lock:
            if self._ec is None:
                self._ec = ECClient(host="127.0.0.1", port=engine["ec_port"],
                                    password=engine["ec_password"])
            else:
                self._ec.configure(host="127.0.0.1", port=engine["ec_port"],
                                   password=engine["ec_password"])
            return self._ec

    def _online_client(self):
        """返回已连接（或可连接）的 EC 客户端；引擎没起来直接抛 EmuleOffline。"""
        if not self._ctl.find_pid():
            raise EmuleOffline("eMule 引擎未运行，请先在“引擎”里启动")
        client = self._ec_client()
        try:
            client.connect()
        except EmuleTimeout:
            # 超时类型要原样上抛，面板据此回 504 而不是 503
            raise
        except EmuleOffline as exc:
            self._last_ec_error = str(exc)
            raise EmuleOffline(str(exc))
        except EmuleError as exc:
            self._last_ec_error = str(exc)
            raise EmuleOffline("EC 连接不可用：%s" % exc)
        return client

    # ------------------------------------------------------------ 生命周期
    def prepare(self):
        """幂等：建目录、生成 amule.conf、首次下载 bootstrap 文件。"""
        with self._lock:
            engine = self._engine_settings()
            self._ctl.ensure_dirs(engine)
            conf_path = os.path.join(self.config_dir, "amule.conf")
            wanted = self._ctl.conf_text(engine)
            current = None
            try:
                with open(conf_path, "r", encoding="utf-8", errors="replace") as handle:
                    current = handle.read()
            except OSError:
                current = None
            if current != wanted:
                self._ctl.write_conf(engine)
            status = bootstrap.artifact_status(self.config_dir)
            # aMule 退出时会用内存列表覆盖 server.met；列表为空时它会写回 0 条的文件，
            # 所以这里不能只看文件是否存在，还要看条数。
            need_server_met = (not status["server_met"]["exists"]
                               or status["server_met"]["count"] <= 0)
            need_nodes_dat = (not status["nodes_dat"]["exists"]
                              or status["nodes_dat"]["count"] <= 0)
            # 首次准备只同步下 server.met / nodes.dat（各约 1KB~6KB，超时 6 秒）：
            # 这两个必须在 amuled 启动前就位，否则它读不到服务器列表。
            # ipfilter（11.7MB）和缺失补全都放到 start() 的后台线程，避免安装后
            # 首次启动被网络拖到应用中心超时。
            if need_server_met or need_nodes_dat:
                try:
                    bootstrap.ensure_files(
                        self.config_dir,
                        {"server_met_url": engine["server_met_url"],
                         "nodes_dat_url": engine["nodes_dat_url"]},
                        force_server_met=need_server_met,
                        force_nodes_dat=need_nodes_dat,
                        timeout=6.0)
                except EmuleError:
                    pass
            self._prepared = True
        return None

    def start(self):
        """启动 amuled（已在运行则只确保守护线程在跑）。"""
        self.prepare()
        if not self._ctl.find_pid():
            self._ctl.start()
            with self._lock:
                self._ec = None                        # 新进程要新建连接
        self._ctl.start_watchdog()
        self.start_background_bootstrap()
        return None

    def start_background_bootstrap(self):
        """后台补齐引导文件（幂等）。启动路径不等待它。"""
        with self._lock:
            if self._bg_thread is not None and self._bg_thread.is_alive():
                return False
            self._bg_thread = threading.Thread(target=self._background_bootstrap,
                                               name="emule-bootstrap", daemon=True)
            self._bg_thread.start()
            return True

    def _background_bootstrap(self):
        """引擎起来之后补齐 server.met / nodes.dat / ipfilter，用完再 EC reload。

        这样 prepare() 不会因为下载 11.7MB 的 ipfilter 把安装后首次启动拖过应用中心
        的启动超时；缺什么补什么，失败只记在 panel.log 里，不影响引擎。
        """
        engine = self._engine_settings()
        status = bootstrap.artifact_status(self.config_dir)
        notes = []
        try:
            if status["server_met"]["count"] <= 0:
                try:
                    result = self.servers_update()
                    notes.append("server.met 已后台补齐（%d 条）" % len(
                        bootstrap.load_server_met(self.config_dir)))
                except EmuleError as exc:
                    notes.append("server.met 后台补齐失败：%s" % exc)
            if status["nodes_dat"]["count"] <= 0:
                try:
                    result = self.kad_bootstrap()
                    notes.append("nodes.dat 已后台补齐（%d 个联系人）"
                                 % int(result.get("nodes") or 0))
                except EmuleError as exc:
                    notes.append("nodes.dat 后台补齐失败：%s" % exc)
            # aMule 启动时会写一个 182 字节的空 ipfilter.dat，所以要按“有没有真实条目”判断
            if engine.get("ipfilter") and not status["ipfilter"].get("usable"):
                result = bootstrap.download_ipfilter(self.config_dir, timeout=60.0)
                if result.get("ok"):
                    try:
                        self._ec_client().ipfilter_reload()
                        notes.append("ipfilter 已下载并重载（%d 字节）"
                                     % int(result.get("size") or 0))
                    except EmuleError as exc:
                        notes.append("ipfilter 已下载，重载失败：%s" % exc)
                else:
                    notes.append("ipfilter 下载失败：%s" % (result.get("error") or ""))
        finally:
            self._bg_notes = notes
            for note in notes:
                try:
                    self._ctl._log("info", note)      # noqa: SLF001 - 同模块内部日志
                except Exception:                     # noqa: BLE001
                    pass

    def stop(self):
        self._ctl.stop_watchdog()
        with self._lock:
            if self._ec is not None:
                try:
                    self._ec.close()
                except Exception:                      # noqa: BLE001
                    pass
                self._ec = None
        self._ctl.stop()
        return None

    def restart(self):
        self.stop()
        time.sleep(0.5)
        self.start()
        return None

    def shutdown(self):
        """面板退出时调用：断开 EC、停守护、优雅停引擎。"""
        self.stop()
        return None

    def process_status(self):
        status = self._ctl.status()
        ec_online = False
        version = ""
        if status["running"]:
            try:
                info = self._ec_client().connect()
                ec_online = True
                version = info.get("version") or ""
                self._last_ec_error = ""
            except EmuleError as exc:
                self._last_ec_error = str(exc)
        return {
            "running": status["running"],
            "pid": status["pid"],
            "ec": ec_online,
            "uptime": status["uptime"],
            "version": version,
            "error": self._last_ec_error,
            "bootstrap_notes": list(self._bg_notes),
        }

    # ------------------------------------------------------------ 概览
    def _session_traffic(self, pid, total_down, total_up):
        """把 aMule 的累计收发字节换算成本次引擎会话的收发字节。"""
        base = self._session_base
        if base is None or base.get("pid") != pid:
            self._session_base = {"pid": pid, "down": total_down, "up": total_up}
            base = self._session_base
        return (max(0, total_down - int(base["down"])),
                max(0, total_up - int(base["up"])))

    def _sample_history(self, down, up):
        now = int(time.time())
        if now - self._last_history_ts >= 5:
            self._last_history_ts = now
            self._history.append({"t": now, "down": int(down), "up": int(up)})

    def _disk(self, path):
        try:
            usage = shutil.disk_usage(path)
            return {"free": int(usage.free), "total": int(usage.total), "path": path}
        except OSError:
            return {"free": 0, "total": 0, "path": path}

    def overview(self):
        client = self._online_client()
        stats = client.stat_request()
        state = stats.get("connstate") or {}
        downloads = client.download_queue()
        uploads = client.upload_queue()

        items = [self._download_item(record) for record in downloads]
        active = sum(1 for item in items if item["status"] == "downloading")
        paused = sum(1 for item in items if item["status"] == "paused")
        waiting = sum(1 for item in items if item["status"] in ("waiting", "hashing"))
        complete = sum(1 for item in items if item["status"] == "complete")
        transferring_sources = sum(item["sources"]["transferring"] for item in items)

        engine = self._engine_settings()
        down_speed = int(stats.get("down_speed") or 0)
        up_speed = int(stats.get("up_speed") or 0)
        self._sample_history(down_speed, up_speed)
        status = self.process_status()
        total_down = int(stats.get("total_received") or 0)
        total_up = int(stats.get("total_sent") or 0)
        session_down, session_up = self._session_traffic(status["pid"], total_down, total_up)

        return {
            "engine": {
                "running": status["running"],
                "ec": status["ec"],
                "version": status["version"] or "",
                "pid": status["pid"],
            },
            "ed2k": {
                "connected": bool(state.get("ed2k_connected")),
                "connecting": bool(state.get("ed2k_connecting")),
                "low_id": bool(state.get("low_id")),
                "id": int(state.get("ed2k_id") or 0),
                "server": state.get("server") or {},
            },
            "kad": {
                "connected": bool(state.get("kad_connected")),
                "running": bool(state.get("kad_running")),
                "firewalled": bool(state.get("kad_firewalled")),
                "nodes": int(stats.get("kad_nodes") or 0),
                "users": int(stats.get("kad_users") or 0),
                "files": int(stats.get("kad_files") or 0),
            },
            "speed": {
                "down": down_speed,
                "up": up_speed,
                "down_limit": int(stats.get("down_limit") or 0),
                "up_limit": int(stats.get("up_limit") or 0),
                "max_down": int(stats.get("down_limit") or 0),
                "overhead_down": int(stats.get("down_overhead") or 0),
                "overhead_up": int(stats.get("up_overhead") or 0),
            },
            "session": {
                "down": session_down,
                "up": session_up,
                "down_total": total_down,
                "up_total": total_up,
            },
            "counters": {
                "downloads": len(items),
                "downloads_active": active,
                "downloads_paused": paused,
                "downloads_waiting": waiting,
                "downloads_complete": complete,
                "uploads": len(uploads),
                "queue": int(stats.get("ul_queue_len") or 0),
                "sources": int(stats.get("sources") or 0),
                "connections": len(uploads) + transferring_sources,
                "shared": int(stats.get("shared_files") or 0),
                "ed2k_users": int(stats.get("ed2k_users") or 0),
                "ed2k_files": int(stats.get("ed2k_files") or 0),
                "banned": int(stats.get("banned") or 0),
            },
            "disk": self._disk(engine["incoming_dir"]),
            "history": list(self._history),
        }

    # ------------------------------------------------------------ 传输列表
    @staticmethod
    def _priority_name(raw):
        if raw >= PRIO_AUTO_OFFSET:
            return "auto"
        return _PRIORITY_BY_CODE.get(raw, "normal")

    def _download_item(self, record):
        """EC partfile 记录 → CONTRACT §3 的下载 item。"""
        size = int(record.get("size") or 0)
        done = int(record.get("done") or 0)
        speed = int(record.get("speed") or 0)
        status = _STATUS_BY_CODE.get(int(record.get("status") or 0), "waiting")
        if status == "waiting" and int(record.get("source_xfer") or 0) > 0:
            status = "downloading"
        if status == "waiting" and speed > 0:
            status = "downloading"
        remaining = max(0, size - done)
        eta = int(remaining / speed) if speed > 0 and remaining > 0 else 0
        percent = (float(done) / size) if size else 0.0
        return {
            "hash": record.get("hash") or "",
            "name": record.get("name") or "",
            "size": size,
            "done": done,
            "percent": round(_clamp(percent, 0.0, 1.0), 6),
            "speed": speed,
            "eta": eta,
            "status": status,
            "priority": self._priority_name(int(record.get("prio_raw") or 0)),
            "category": str(record.get("category") or ""),
            "partfile": True,
            "added": int(record.get("last_recv") or 0),
            "sources": {
                "total": int(record.get("source_total") or 0),
                "transferring": int(record.get("source_xfer") or 0),
                "asked": int(record.get("source_not_current") or 0),
                "found": int(record.get("source_total") or 0),
                "a4af": int(record.get("source_a4af") or 0),
            },
            "progress": {"completed": done},
            "shared": bool(record.get("shared")),
            "uploading": False,
            "available_parts": int(record.get("available_parts") or 0),
            "ed2k_link": record.get("ed2k_link") or "",
            "_ecid": int(record.get("ecid") or 0),
        }

    def _upload_item(self, record):
        """EC client 记录 → 上传 item（沿用下载 item 的字段名，另加 client 段）。"""
        speed = int(record.get("up_speed") or 0)
        uploaded = int(record.get("uploaded_total") or 0)
        state = _CLIENT_UPLOAD_STATE.get(int(record.get("upload_state") or 0), "queued")
        status = "uploading" if state == "uploading" else "waiting"
        return {
            "hash": record.get("hash") or "",
            "name": record.get("upload_file_name") or record.get("remote_filename") or "",
            "size": 0,
            "done": uploaded,
            "percent": 0.0,
            "speed": speed,
            "eta": 0,
            "status": status,
            "priority": "normal",
            "category": "",
            "partfile": False,
            "added": 0,
            "sources": {"total": 0, "transferring": 0, "asked": 0, "found": 0, "a4af": 0},
            "progress": {"completed": uploaded},
            "shared": True,
            "uploading": True,
            "uploaded": uploaded,
            "uploaded_session": int(record.get("upload_session") or 0),
            "queue_rank": int(record.get("queue_rank") or 0),
            "waiting_position": int(record.get("waiting_position") or 0),
            "client": {
                "name": record.get("name") or "",
                "software": record.get("soft_ver") or "",
                "version": int(record.get("soft_ver_num") or 0),
                "mod": record.get("mod_version") or "",
                "ip": record.get("ip_str") or "",
                "port": int(record.get("port") or 0),
                "userhash": record.get("hash") or "",
                "score": int(record.get("score") or 0),
                "ident": int(record.get("ident_state") or 0),
                "obfuscation": int(record.get("obfuscation") or 0),
                "friend_slot": bool(record.get("friend_slot")),
                "upload_state": state,
                "download_state": _CLIENT_DOWNLOAD_STATE.get(
                    int(record.get("download_state") or 0), "none"),
                "kad_port": int(record.get("kad_port") or 0),
            },
            "_ecid": int(record.get("ecid") or 0),
        }

    def transfers(self, kind):
        if kind not in ("download", "upload"):
            raise EmuleError("不支持的传输类型：%s（只支持 download / upload）" % kind)
        client = self._online_client()
        if kind == "download":
            records = client.download_queue()
            items = [self._download_item(record) for record in records]
            summary = {
                "count": len(items),
                "active": sum(1 for item in items if item["status"] == "downloading"),
                "paused": sum(1 for item in items if item["status"] == "paused"),
                "waiting": sum(1 for item in items
                               if item["status"] in ("waiting", "hashing")),
                "complete": sum(1 for item in items if item["status"] == "complete"),
                "down": sum(item["speed"] for item in items),
                "up": 0,
            }
        else:
            records = client.upload_queue()
            items = [self._upload_item(record) for record in records]
            summary = {
                "count": len(items),
                "active": sum(1 for item in items if item["status"] == "uploading"),
                "paused": 0,
                "waiting": sum(1 for item in items if item["status"] == "waiting"),
                "complete": 0,
                "down": 0,
                "up": sum(item["speed"] for item in items),
            }
        return {"items": items, "summary": summary, "total": len(items)}

    # ------------------------------------------------------------ 传输详情
    @staticmethod
    def build_chunks(size, gaps):
        """缺口区间 → 按 9.28MB 分块对齐的 [{start,end,state}]。

        aMule 的 gap list 是“还没下载到的字节区间”，所以没被任何 gap 覆盖的块 = done，
        完全落在 gap 里的块 = missing，跨 gap 边界的块 = pending（部分完成）。
        gaps 已由 ec.decode_gaps 统一成左闭右开区间。
        """
        size = int(size or 0)
        if size <= 0:
            return []
        chunks = []
        ordered = sorted((int(start), int(end)) for start, end in (gaps or []))
        part_count = (size + PARTSIZE - 1) // PARTSIZE
        index = 0
        for part in range(part_count):
            start = part * PARTSIZE
            end = min(size, start + PARTSIZE)
            missing = 0
            # 跳过完全在块前面的 gap
            while index < len(ordered) and ordered[index][1] <= start:
                index += 1
            scan = index
            while scan < len(ordered) and ordered[scan][0] < end:
                gap_start, gap_end = ordered[scan]
                missing += min(end, gap_end) - max(start, gap_start)
                scan += 1
            if missing <= 0:
                state = "done"
            elif missing >= (end - start):
                state = "missing"
            else:
                state = "pending"
            chunks.append({"start": start, "end": end, "state": state})
        return chunks

    def transfer_detail(self, file_hash):
        file_hash = (file_hash or "").strip().upper()
        if len(file_hash) != 32:
            raise EmuleError("文件哈希必须是 32 位十六进制：%s" % file_hash)
        client = self._online_client()
        records = client.download_queue()
        target = None
        for record in records:
            if (record.get("hash") or "").upper() == file_hash:
                target = record
                break
        if target is None:
            raise EmuleError("下载列表里没有该文件：%s" % file_hash)
        item = self._download_item(target)
        ecid = int(target.get("ecid") or 0)
        sources = []
        try:
            update = client.get_update()
        except EmuleError:
            update = {"clients": []}
        for record in update.get("clients") or []:
            if int(record.get("request_file_ecid") or 0) != ecid:
                continue
            down_speed = float(record.get("down_speed") or 0.0)
            sources.append({
                "ip": record.get("ip_str") or "",
                "port": int(record.get("port") or 0),
                "client": record.get("name") or "",
                "version": record.get("soft_ver") or record.get("mod_version") or "",
                "userhash": record.get("hash") or "",
                "speed": int(down_speed * 1024),
                "state": _CLIENT_DOWNLOAD_STATE.get(
                    int(record.get("download_state") or 0), "none"),
                "queue_rank": int(record.get("queue_rank") or 0),
                "queue_wait": 0,
                "available_parts": int(record.get("available_parts") or 0),
                "score": int(record.get("score") or 0),
                "ident": int(record.get("ident_state") or 0),
                "obfuscation": int(record.get("obfuscation") or 0),
            })
        sources.sort(key=lambda entry: (-entry["speed"], entry["ip"]))
        chunks = self.build_chunks(item["size"], target.get("gaps") or [])
        return {"file": item, "sources": sources, "chunks": chunks}

    # ------------------------------------------------------------ 传输操作
    def _partfile_hashes(self, hashes):
        if isinstance(hashes, str):
            hashes = [hashes]
        cleaned = []
        for value in hashes or []:
            text = (value or "").strip().upper()
            if len(text) != 32:
                raise EmuleError("文件哈希必须是 32 位十六进制：%s" % value)
            cleaned.append(text)
        if not cleaned:
            raise EmuleError("没有指定任何文件哈希")
        return cleaned

    def transfer_action(self, file_hash, action, priority=None):
        client = self._online_client()
        file_hash = self._partfile_hashes([file_hash])[0]
        action = (action or "").strip().lower()
        is_priority = False
        if action in ("pause", "paused"):
            client.partfile_command(Op.PARTFILE_PAUSE, file_hash)
        elif action in ("resume", "start"):
            client.partfile_command(Op.PARTFILE_RESUME, file_hash)
        elif action in ("cancel", "delete", "remove"):
            client.partfile_command(Op.PARTFILE_DELETE, file_hash)
        elif action in ("stop",):
            client.partfile_command(Op.PARTFILE_STOP, file_hash)
        elif action in ("priority", "prio", "set_priority"):
            name = (priority or "normal").strip().lower()
            if name not in _PRIORITY_RAW:
                raise EmuleError("优先级只能是 low / normal / high / auto：%s" % priority)
            client.set_partfile_priority(file_hash, _PRIORITY_RAW[name])
            is_priority = True
        else:
            raise EmuleError("不支持的操作：%s（支持 pause / resume / cancel / stop / priority）"
                             % action)
        return {"ok": True, "hash": file_hash, "action": action,
                "priority": (priority or "") if is_priority else ""}

    def transfer_apply(self, hashes, action):
        results = []
        ok_all = True
        for file_hash in (hashes or []):
            try:
                result = self.transfer_action(file_hash, action)
                results.append({"hash": result["hash"], "ok": True, "error": "", "kept": ""})
            except EmuleError as exc:
                ok_all = False
                results.append({"hash": str(file_hash or "").strip().upper(),
                                "ok": False, "error": str(exc), "kept": ""})
        return {"ok": ok_all, "action": action, "count": len(results), "results": results}

    # ------------------------------------------------------------ 删除任务
    def transfer_delete(self, hashes, delete_data=False):
        """删除下载任务；delete_data=False 时先把 <temp_dir>/NNN.part 系列搬到回收目录。

        delete_data=True  → 直接 EC DELETE（aMule 的 CPartFile::Delete 会删掉 Temp 下的
                            .part 与 .part.met 系列），并顺手清掉该 hash 的回收目录。
        delete_data=False → PAUSE → STOP → 等句柄落盘 → 搬文件 → DELETE。
                            STOP 走 CPartFile::StopFile()，它会 FlushBuffer()，否则缓冲区里
                            最后几 MB 还挂在旧 inode 上，搬出来的 .part 与 .part.met 的
                            gap 记录对不上。
        每个 hash 一个结果条目：{hash, ok, error, kept}，kept 是保留目录路径（没有则空串）。
        """
        cleaned = self._partfile_hashes(hashes)
        client = self._online_client()
        engine = self._engine_settings()
        temp_dir = (engine.get("temp_dir") or "").strip()
        var_dir = self.var_dir
        delete_data = bool(delete_data)
        records = {}
        for record in client.download_queue():
            key = (record.get("hash") or "").upper()
            if key:
                records[key] = record
        results = []
        ok_all = True
        for file_hash in cleaned:
            try:
                kept = self._delete_one(client, file_hash, records.get(file_hash),
                                        temp_dir, var_dir, delete_data)
                results.append({"hash": file_hash, "ok": True, "error": "", "kept": kept})
            except (EmuleOffline, EmuleTimeout):
                raise                       # 引擎掉线/超时是整体故障，不要伪装成"这一条失败"
            except EmuleError as exc:
                ok_all = False
                results.append({"hash": file_hash, "ok": False, "error": str(exc), "kept": ""})
        return {"ok": ok_all, "action": "delete", "delete_data": delete_data,
                "count": len(results), "results": results}

    def _delete_one(self, client, file_hash, record, temp_dir, var_dir, delete_data):
        """单个 hash 的删除实现，返回保留目录路径（没有搬走任何文件时为空串）。"""
        if record is None:
            raise EmuleError("下载列表里没有该文件：%s" % file_hash)
        partmet_id = int(record.get("partmet_id") or 0)
        if delete_data:
            # 彻底删除：aMule 的 CPartFile::Delete 自己会清 Temp 下的 .part/.part.met，
            # 我们只需把同一 hash 的回收目录一并清掉。先删任务再清目录：清目录失败
            # （路径不合规等）不该连"删任务"这个用户诉求一起否掉。
            client.partfile_command(Op.PARTFILE_DELETE, file_hash)
            self._purge_deleted_dir(var_dir, file_hash)
            return ""
        # 保留数据：定位不到 partmet 就整体放弃（安全优先：宁可不删，也不留半套文件）
        if partmet_id <= 0:
            raise EmuleError("无法定位临时数据文件，未执行删除")
        plan = self._plan_quarantine(temp_dir, var_dir, file_hash, partmet_id)
        self._stop_partfile(client, file_hash)
        kept = self._run_quarantine(plan)
        client.partfile_command(Op.PARTFILE_DELETE, file_hash)
        return kept

    @staticmethod
    def _part_file_names(partmet_id):
        """partmet 编号 → Temp 下属于该任务的四个文件名（aMule 用 %03u.part.met）。"""
        if partmet_id <= 0:
            return []
        stem = "%03d.part" % partmet_id
        return [stem, stem + ".met", stem + ".met.bak", stem + ".met.seeds"]

    def _stop_partfile(self, client, file_hash):
        """暂停 + 停盘，让缓冲区块真正写进 .part 后再搬文件。"""
        try:
            client.partfile_command(Op.PARTFILE_PAUSE, file_hash)
            client.partfile_command(Op.PARTFILE_STOP, file_hash)
        except (EmuleOffline, EmuleTimeout):
            raise                       # 引擎掉线/超时原样上抛，面板据此回 503/504
        except EmuleError as exc:
            raise EmuleError("暂停任务失败，未执行删除：%s" % exc)
        time.sleep(PARTFILE_STOP_WAIT)

    def _plan_quarantine(self, temp_dir, var_dir, file_hash, partmet_id):
        """只做路径计算与越界校验，不碰磁盘；任何一处越界都抛 EmuleError。"""
        names = self._part_file_names(partmet_id)
        if not names:
            raise EmuleError("无法定位临时数据文件，未执行删除")
        if not temp_dir:
            raise EmuleError("临时目录未配置，未执行删除")
        temp_root = os.path.realpath(temp_dir)
        if not os.path.isdir(temp_root):
            raise EmuleError("临时目录不存在，未执行删除：%s" % temp_dir)
        kept_dir = self._deleted_dir_path(var_dir, file_hash)
        sources = []
        for name in names:
            if not _PART_FILE_RE.match(name):
                raise EmuleError("临时数据文件名不合规，未执行删除：%s" % name)
            source = os.path.join(temp_dir, name)
            if not _within_root(os.path.realpath(source), temp_root):
                raise EmuleError("临时数据文件路径越界，未执行删除：%s" % source)
            target = os.path.join(kept_dir, name)
            if os.path.basename(target) != name or \
                    not _within_root(os.path.realpath(target), kept_dir):
                raise EmuleError("保留目录路径越界，未执行删除：%s" % target)
            sources.append({"name": name, "source": source, "target": target})
        return {"kept_dir": kept_dir, "sources": sources}

    def _run_quarantine(self, plan):
        """按计划把存在的文件搬到回收目录；返回保留目录路径（一个都没搬走时为空串）。"""
        kept_dir = plan["kept_dir"]
        pending = [item for item in plan["sources"] if os.path.exists(item["source"])]
        if not pending:
            return ""
        try:
            os.makedirs(kept_dir, exist_ok=True)
        except OSError as exc:
            raise EmuleError("创建保留目录失败：%s" % exc)
        for item in pending:
            try:
                # Temp 与 var 可能不在同一个卷上，shutil.move 会自动退化成复制后删除
                shutil.move(item["source"], item["target"])
            except (OSError, shutil.Error) as exc:
                raise EmuleError("搬迁临时数据失败（%s）：%s" % (item["name"], exc))
        return kept_dir

    def _deleted_dir_path(self, var_dir, file_hash):
        """<var_dir>/deleted/<HASH>/，并校验落在 var_dir 之内。"""
        if not _HASH_RE.match(file_hash or ""):
            raise EmuleError("文件哈希不合法，未执行删除：%s" % file_hash)
        root = os.path.realpath(var_dir)
        target = os.path.join(var_dir, DELETED_DIRNAME, file_hash)
        if not _within_root(os.path.realpath(target), root):
            raise EmuleError("保留目录路径越界，未执行删除：%s" % target)
        return target

    def _purge_deleted_dir(self, var_dir, file_hash):
        """删掉 <var_dir>/deleted/<HASH>/（不存在则什么都不做）。"""
        try:
            target = self._deleted_dir_path(var_dir, file_hash)
        except EmuleError:
            return
        if not os.path.isdir(target) or os.path.islink(target):
            return
        try:
            shutil.rmtree(target, ignore_errors=True)
        except OSError:
            pass

    # ------------------------------------------------------------ 添加链接
    _ED2K_RE = re.compile(r"^ed2k://\|file\|(?P<name>[^|]*)\|(?P<size>\d+)\|(?P<hash>[0-9a-fA-F]{32})\|/?$")

    @classmethod
    def normalize_link(cls, link):
        """把 ed2k:// 或 magnet:?xt=urn:ed2k:<hash> 归一化成标准 ed2k 链接。"""
        text = (link or "").strip()
        if not text:
            raise EmuleError("链接为空")
        if text.lower().startswith("ed2k://"):
            match = cls._ED2K_RE.match(text)
            if not match:
                raise EmuleError("eD2K 链接格式不正确：%s" % text[:80])
            name = match.group("name")
            size = int(match.group("size"))
            file_hash = match.group("hash").upper()
            return {
                "link": "ed2k://|file|%s|%d|%s|/" % (name, size, file_hash),
                "hash": file_hash,
                "name": name,
                "size": size,
            }
        if text.lower().startswith("magnet:"):
            query = text.split("?", 1)[1] if "?" in text else ""
            params = {}
            for pair in query.split("&"):
                if not pair:
                    continue
                key, _, value = pair.partition("=")
                params.setdefault(key.lower(), []).append(value)
            file_hash = ""
            for value in params.get("xt", []):
                lowered = value.lower()
                if lowered.startswith("urn:ed2k:"):
                    file_hash = value.split(":", 2)[2].upper()
                elif lowered.startswith("urn:ed2khash:"):
                    file_hash = value.split(":", 2)[2].upper()
                if file_hash:
                    break
            if len(file_hash) != 32:
                raise EmuleError("magnet 链接里没有 ed2k 哈希（只支持 urn:ed2k）：%s" % text[:80])
            name = params.get("dn", [""])[0]
            try:
                size = int(params.get("xl", ["0"])[0] or 0)
            except ValueError:
                size = 0
            return {
                "link": "ed2k://|file|%s|%d|%s|/" % (name, size, file_hash),
                "hash": file_hash,
                "name": name,
                "size": size,
            }
        raise EmuleError("无法识别的链接（只支持 ed2k:// 与 magnet:?xt=urn:ed2k:）：%s"
                         % text[:80])

    def add_links(self, links, category="", paused=False):
        if isinstance(links, str):
            links = [links]
        links = [item for item in (links or []) if (item or "").strip()]
        if not links:
            raise EmuleError("没有提供任何下载链接")
        client = self._online_client()
        category_id = 0
        try:
            category_id = int(category) if str(category).strip() not in ("", "None") else 0
        except (TypeError, ValueError):
            category_id = 0
        results = []
        for raw in links:
            try:
                normalized = self.normalize_link(raw)
            except EmuleError as exc:
                results.append({"link": raw, "ok": False, "hash": "", "name": "",
                                "size": 0, "error": str(exc)})
                continue
            try:
                client.add_link(normalized["link"], category_id)
            except EmuleError as exc:
                message = str(exc)
                if "already" in message.lower() or "Invalid link" in message:
                    message = "链接无效或该文件已在下载列表中"
                results.append({"link": normalized["link"], "ok": False,
                                "hash": normalized["hash"], "name": normalized["name"],
                                "size": normalized["size"], "error": message})
                continue
            if paused:
                try:
                    client.partfile_command(Op.PARTFILE_PAUSE, normalized["hash"])
                except EmuleError:
                    pass
            results.append({"link": normalized["link"], "ok": True,
                            "hash": normalized["hash"], "name": normalized["name"],
                            "size": normalized["size"], "error": ""})
        return results

    # ------------------------------------------------------------ 服务器
    def servers(self):
        client = self._online_client()
        records = client.server_list()
        try:
            state = client.get_connstate()
        except EmuleError:
            state = {}
        items = []
        for record in records:
            failed_count = int(record.get("failed") or 0)
            items.append({
                "ip": record.get("ip") or "",
                "port": int(record.get("port") or 0),
                "name": record.get("name") or "",
                "desc": record.get("desc") or "",
                "users": int(record.get("users") or 0),
                "maxusers": int(record.get("maxusers") or 0),
                "files": int(record.get("files") or 0),
                "priority": _SERVER_PRIORITY.get(int(record.get("priority") or 0), "normal"),
                "ping": int(record.get("ping") or 0),
                "failed": bool(failed_count),
                "failed_count": failed_count,
                "static": bool(record.get("static")),
                "version": record.get("version") or "",
            })
        items.sort(key=lambda entry: (entry["failed"], -entry["users"], entry["name"]))
        current = state.get("server") or {}
        current_payload = {}
        if current:
            current_payload = {
                "ip": current.get("ip") or "",
                "port": int(current.get("port") or 0),
                "name": current.get("name") or "",
            }
        return {
            "items": items,
            "current": current_payload,
            "ed2k_connected": bool(state.get("ed2k_connected")),
            "total": len(items),
            "working": sum(1 for item in items if not item["failed"]),
        }

    def server_connect(self, ip, port):
        if not ip:
            raise EmuleError("缺少服务器 IP")
        client = self._online_client()
        client.server_connect(ip, int(port or 0))
        return {"ok": True, "ip": ip, "port": int(port or 0)}

    def server_add(self, ip, port, name=""):
        if not ip:
            raise EmuleError("缺少服务器 IP")
        client = self._online_client()
        client.server_add(ip, int(port or 0), name or "")
        return {"ok": True, "ip": ip, "port": int(port or 0), "name": name}

    def server_remove(self, ip, port):
        if not ip:
            raise EmuleError("缺少服务器 IP")
        client = self._online_client()
        client.server_remove(ip, int(port or 0))
        return {"ok": True, "ip": ip, "port": int(port or 0)}

    def _server_ecid_map(self, client):
        """(ip, port) → ECID；只有增量更新包里才带服务器 ECID。"""
        try:
            update = client.get_update()
        except EmuleError:
            return {}
        mapping = {}
        for record in update.get("servers") or []:
            ip = record.get("ip") or ""
            port = int(record.get("port") or 0)
            ecid = int(record.get("ecid") or 0)
            if ip and ecid:
                mapping[(ip, port)] = ecid
        return mapping

    def server_priority(self, ip, port, priority):
        name = (priority or "normal").strip().lower()
        if name not in _SERVER_PRIORITY_RAW:
            raise EmuleError("服务器优先级只能是 low / normal / high：%s" % priority)
        client = self._online_client()
        mapping = self._server_ecid_map(client)
        ecid = mapping.get((ip, int(port or 0)))
        if not ecid:
            raise EmuleError("服务器列表里没有该服务器：%s:%s" % (ip, port))
        client.server_set_priority(ecid, _SERVER_PRIORITY_RAW[name])
        return {"ok": True, "ip": ip, "port": int(port or 0), "priority": name}

    def servers_update(self):
        """面板自己下载 server.met → 逐条导入 → 返回统计。

        不调用 EC_OP_SERVER_UPDATE_FROM_URL：那会让 amuled 自己去连 HTTP，
        在代理网络下会触发 wxWidgets 断言崩溃（已实测）。
        """
        engine = self._engine_settings()
        result = bootstrap.download_server_met(self.config_dir, engine["server_met_url"])
        if not result.get("ok"):
            raise EmuleError("更新服务器列表失败：%s" % (result.get("error") or "下载失败"))
        parsed = bootstrap.load_server_met(self.config_dir)
        client = self._online_client()
        existing = set()
        for record in client.server_list():
            existing.add((record.get("ip") or "", int(record.get("port") or 0)))
        added = 0
        skipped = 0
        failed = 0
        errors = []
        for record in parsed:
            key = (record.get("ip") or "", int(record.get("port") or 0))
            if key in existing:
                skipped += 1
                continue
            try:
                client.server_add(record["ip"], record["port"], record.get("name") or "")
                added += 1
                existing.add(key)
            except EmuleError as exc:
                failed += 1
                if len(errors) < 5:
                    errors.append("%s:%d %s" % (record["ip"], record["port"], exc))
        return {
            "ok": True,
            "url": result.get("url") or "",
            "size": int(result.get("size") or 0),
            "mtime": int(result.get("mtime") or 0),
            "count": len(parsed),
            "added": added,
            "skipped": skipped,
            "failed": failed,
            "errors": errors,
        }

    # ------------------------------------------------------------ Kad
    def kad_status(self):
        client = self._online_client()
        stats = client.stat_request()
        state = stats.get("connstate") or {}
        artifacts = bootstrap.artifact_status(self.config_dir)
        return {
            "connected": bool(state.get("kad_connected")),
            "running": bool(state.get("kad_running")),
            "firewalled": bool(state.get("kad_firewalled")),
            "nodes": int(stats.get("kad_nodes") or 0),
            "users": int(stats.get("kad_users") or 0),
            "files": int(stats.get("kad_files") or 0),
            "in_lan_mode": bool(stats.get("kad_in_lan_mode")),
            "ip": uint32_to_ip(stats.get("kad_ip_raw") or 0) if stats.get("kad_ip_raw") else "",
            "kad_id": state.get("kad_id") or "",
            "indexed": {
                "sources": int(stats.get("kad_indexed_sources") or 0),
                "keywords": int(stats.get("kad_indexed_keywords") or 0),
                "notes": int(stats.get("kad_indexed_notes") or 0),
                "load": int(stats.get("kad_indexed_load") or 0),
            },
            "buddy": {
                "status": int(stats.get("kad_buddy_status") or 0),
                "ip": uint32_to_ip(stats.get("kad_buddy_ip") or 0)
                      if stats.get("kad_buddy_ip") else "",
                "port": int(stats.get("kad_buddy_port") or 0),
            },
            "bootstrap": {
                "nodes_dat": artifacts["nodes_dat"],
                "server_met": artifacts["server_met"],
            },
        }

    def kad_bootstrap(self):
        """下载 nodes.dat → 重启 Kad 让它重新加载（aMule 启动 Kad 时读 nodes.dat）。"""
        engine = self._engine_settings()
        result = bootstrap.download_nodes_dat(self.config_dir, engine["nodes_dat_url"])
        if not result.get("ok"):
            raise EmuleError("下载 nodes.dat 失败：%s" % (result.get("error") or "下载失败"))
        client = self._online_client()
        reloaded = False
        try:
            client.kad_stop()
            time.sleep(0.6)
            client.kad_start()
            reloaded = True
        except EmuleError as exc:
            return {
                "ok": True, "reloaded": False, "error": str(exc),
                "url": result.get("url") or "", "size": int(result.get("size") or 0),
                "mtime": int(result.get("mtime") or 0),
                "nodes": int(result.get("detail") or 0),
            }
        return {
            "ok": True,
            "reloaded": reloaded,
            "url": result.get("url") or "",
            "size": int(result.get("size") or 0),
            "mtime": int(result.get("mtime") or 0),
            "nodes": int(result.get("detail") or 0),
            "path": result.get("path") or "",
        }

    # ------------------------------------------------------------ 共享
    def shared(self):
        client = self._online_client()
        records = client.shared_files()
        items = []
        for record in records:
            size = int(record.get("size") or 0)
            xferred = int(record.get("xferred") or 0)
            items.append({
                "hash": record.get("hash") or "",
                "name": record.get("name") or "",
                "path": record.get("path") or "",
                "size": size,
                "priority": self._shared_priority(int(record.get("priority") or 0)),
                "requests": int(record.get("requests") or 0),
                "requests_all": int(record.get("requests_all") or 0),
                "accepts": int(record.get("accepts") or 0),
                "accepts_all": int(record.get("accepts_all") or 0),
                "xferred": xferred,
                "xferred_all": int(record.get("xferred_all") or 0),
                "complete_sources": int(record.get("complete_sources") or 0),
                "on_queue": int(record.get("on_queue") or 0),
                "comment": record.get("comment") or "",
                "rating": int(record.get("rating") or 0),
                "ed2k_link": record.get("ed2k_link") or "",
            })
        items.sort(key=lambda entry: entry["name"].lower())
        return {"items": items, "total": len(items)}

    @staticmethod
    def _shared_priority(raw):
        if raw >= PRIO_AUTO_OFFSET:
            return "auto"
        return {0: "low", 1: "normal", 2: "high", 3: "high", 4: "low", 5: "auto"}.get(raw, "normal")

    def shared_reload(self):
        client = self._online_client()
        client.sharedfiles_reload()
        return {"ok": True, "message": "已请求重新扫描共享目录"}

    # ------------------------------------------------------------ 搜索
    def search_start(self, q, kind, method):
        query = (q or "").strip()
        if not query:
            raise EmuleError("搜索关键词不能为空")
        kind_key = (kind or "global").strip().lower()
        search_type = _SEARCH_KIND.get(kind_key)
        if search_type is None:
            raise EmuleError("不支持的搜索范围：%s（server / global / kad）" % kind)
        client = self._online_client()
        # method 是“搜索方式”（name=按文件名），不是服务器端的文件类型筛选；
        # 传错会让 aMule 用类型过滤，导致一条结果都搜不到。
        method_key = (method or "name").strip().lower()
        file_type = _SEARCH_METHOD.get(method_key, "")
        messages = client.search_start(query, search_type, file_type=file_type)
        with self._lock:
            self._search_seq += 1
            search_id = "s%d-%s" % (self._search_seq, uuid.uuid4().hex[:8])
            for session in self._searches.values():
                session["done"] = True
            self._searches[search_id] = {
                "search_id": search_id,
                "q": query,
                "kind": kind_key,
                "method": method or "",
                "started_at": int(time.time()),
                "results": collections.OrderedDict(),
                "done": False,
                "stopped": False,
                "messages": messages,
                "last_progress": 0,
                "zero_polls": 0,
                "poll_count": 0,
            }
            while len(self._searches) > 8:
                self._searches.popitem(last=False)
        return {"search_id": search_id, "started_at": int(time.time()),
                "messages": messages, "kind": kind_key}

    def _search_payload(self, session, progress, done):
        results = list(session["results"].values())
        results.sort(key=lambda entry: (-entry["sources"], entry["name"].lower()))
        return {
            "search_id": session["search_id"],
            "progress": int(_clamp(progress, 0, 100)),
            "done": bool(done),
            "results": results,
            "started_at": int(session["started_at"]),
            "query": session["q"],
            "kind": session["kind"],
            "stopped": bool(session.get("stopped")),
        }

    def search_state(self, search_id):
        with self._lock:
            session = self._searches.get(search_id)
        if session is None:
            raise EmuleError("搜索会话不存在或已过期：%s" % search_id)
        if session["done"]:
            return self._search_payload(session, 100, True)
        client = self._online_client()
        try:
            raw_progress = client.search_progress()
            records = client.search_results()
        except EmuleOffline:
            raise
        except EmuleError as exc:
            session["done"] = True
            raise EmuleError("读取搜索结果失败：%s" % exc)
        for record in records:
            file_hash = (record.get("hash") or "").upper()
            if not file_hash:
                continue
            size = int(record.get("size") or 0)
            existing = session["results"].get(file_hash)
            entry = {
                "hash": file_hash,
                "name": record.get("name") or "",
                "size": size,
                "sources": int(record.get("sources") or 0),
                "type": _type_of(record.get("name") or ""),
                "ext": _file_ext(record.get("name") or ""),
                "percent": existing["percent"] if existing else 0.0,
                "already": int(record.get("status") or 0) != 0,
                "complete_sources": int(record.get("complete_sources") or 0),
                "ed2k_link": "ed2k://|file|%s|%d|%s|/" % (
                    record.get("name") or "", size, file_hash),
            }
            session["results"][file_hash] = entry
        kind = session["kind"]
        progress, done = self._judge_search(session, kind, raw_progress)
        return self._search_payload(session, progress, done)

    def _judge_search(self, session, kind, raw):
        """EC 的搜索进度取值见 SearchList.cpp GetSearchProgress。

        LOCAL  进行中=0xffff，结束=0；
        GLOBAL 进行中=1..100，结束=0；
        KAD    进行中=0，结束=0xfffe。
        """
        session["poll_count"] = int(session.get("poll_count") or 0) + 1
        if raw == 0xFFFF:
            session["done"] = False
            return 99, False
        if raw == 0xFFFE:
            session["done"] = True
            return 100, True
        if raw > 0:
            session["done"] = False
            session["zero_polls"] = 0
            return int(_clamp(raw, 1, 99)), False
        # raw == 0：eD2k 搜索已结束；Kad 才刚开始
        if kind == "kad":
            session["done"] = False
            return 50, False
        session["zero_polls"] = int(session.get("zero_polls") or 0) + 1
        if session["zero_polls"] >= 2:
            session["done"] = True
            return 100, True
        return 99, False

    def search_stop(self, search_id):
        with self._lock:
            session = self._searches.get(search_id)
        if session is None:
            raise EmuleError("搜索会话不存在或已过期：%s" % search_id)
        client = self._online_client()
        client.search_stop()
        session["done"] = True
        session["stopped"] = True
        payload = self._search_payload(session, 100, True)
        payload["stopped"] = True
        return payload

    def search_download(self, search_id, file_hash):
        with self._lock:
            session = self._searches.get(search_id)
        if session is None:
            raise EmuleError("搜索会话不存在或已过期：%s" % search_id)
        file_hash = (file_hash or "").strip().upper()
        if len(file_hash) != 32:
            raise EmuleError("文件哈希必须是 32 位十六进制：%s" % file_hash)
        client = self._online_client()
        client.download_search_result(file_hash)
        name = ""
        entry = session["results"].get(file_hash)
        if entry is not None:
            entry["already"] = True
            name = entry["name"]
        return {"ok": True, "hash": file_hash, "name": name,
                "message": "已加入下载列表"}

    # ------------------------------------------------------------ 统计
    def stats(self):
        """统计树 → 扁平 [{group,name,value,raw,display,name_zh,group_zh}]。

        aMule 的节点名字是 printf 格式串（"Uptime: %s"、"Total: %i Known: %i"），
        这里把它清洗成干净标签（name 里不会再有 %s），并补中文名 name_zh 与
        中文分组 group_zh；未命中时 name_zh 为空串，由前端回退英文。
        value/raw/display 的语义保持原样（display 仍是"标签: 数值"的一行文本）。
        """
        client = self._online_client()
        flat = client.stat_tree()
        items = []
        for entry in flat:
            value = stat_value_zh(entry["value"])
            name = clean_stat_label(entry["name"], value)
            group_parts = []
            for part in (entry["group"] or "").split("/"):
                cleaned_part = clean_stat_label(part)
                if cleaned_part:
                    group_parts.append(cleaned_part)
            group = " / ".join(group_parts)
            display = name
            if value not in ("", None):
                display = "%s: %s" % (name, value) if name else str(value)
            items.append({
                "group": group,
                "name": name,
                "value": value,
                "raw": entry["raw"],
                "display": display,
                "name_zh": stat_name_zh(name),
                "group_zh": stat_group_zh(group),
            })
        return {"items": items, "total": len(items)}

    # ------------------------------------------------------------ 日志
    def _log_file_lines(self, limit):
        path = os.path.join(self.var_dir, "amuled.log")
        try:
            with open(path, "rb") as handle:
                handle.seek(0, os.SEEK_END)
                size = handle.tell()
                read_size = min(size, max(64 * 1024, limit * 256))
                handle.seek(max(0, size - read_size))
                data = handle.read()
        except OSError:
            return []
        text = data.decode("utf-8", "replace")
        return text.splitlines()[-limit:]

    def _parse_log_lines(self, lines, limit):
        # EC 的 EC_OP_GET_LOG 返回的是“整段日志”一个字符串，先按换行拆开
        expanded = []
        for line in lines or []:
            if isinstance(line, str) and ("\n" in line):
                expanded.extend(line.splitlines())
            else:
                expanded.append(line)
        lines = expanded
        entries = []
        current_ts = int(time.time())
        for line in lines:
            line = line.rstrip()
            if not line:
                continue
            match = _LOG_LINE.match(line)
            if match:
                stamp = match.group(1)
                text = match.group(2)
                try:
                    current_ts = int(time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")))
                except ValueError:
                    pass
            else:
                text = line
            level = "info"
            lowered = text.lower()
            prefix = _LOG_LEVEL_PREFIX.match(text)
            if prefix:
                text = prefix.group(2)
                lowered = text.lower()
            if any(word in lowered for word in _ERROR_WORDS):
                level = "error"
            elif any(word in lowered for word in _WARN_WORDS):
                level = "warn"
            entries.append({"t": current_ts, "level": level, "text": text})
        return entries[-limit:]

    def logs(self, limit=200):
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 200
        limit = int(_clamp(limit, 1, 2000))
        lines = None
        try:
            client = self._online_client()
            lines = client.log_lines()
        except EmuleOffline:
            lines = None
        except EmuleError:
            lines = None
        if not lines:
            lines = self._log_file_lines(limit)
        entries = self._parse_log_lines(lines, limit)
        return entries

    # ------------------------------------------------------------ 偏好
    def prefs(self):
        engine = self._engine_settings()
        client = self._online_client()
        raw = client.get_prefs()
        result = {
            "ec_port": int(engine["ec_port"]),
            "tcp_port": int(raw.get("tcp_port") or engine["tcp_port"]),
            "udp_port": int(raw.get("udp_port") or engine["udp_port"]),
            "nick": raw.get("nick") or engine["nick"],
            "incoming_dir": raw.get("incoming_dir") or engine["incoming_dir"],
            "temp_dir": raw.get("temp_dir") or engine["temp_dir"],
            "shared_dirs": raw.get("shared_dirs") or engine["shared_dirs"],
            "max_download": int(raw.get("max_download") or 0),
            "max_upload": int(raw.get("max_upload") or 0),
            "max_connections": int(raw.get("max_connections") or engine["max_connections"]),
            "max_sources": int(raw.get("max_sources") or engine["max_sources"]),
            "autoconnect": bool(raw.get("autoconnect", engine["autoconnect"])),
            "connect_ed2k": bool(raw.get("connect_ed2k", engine["connect_ed2k"])),
            "connect_kad": bool(raw.get("connect_kad", engine["connect_kad"])),
            "add_paused": bool(raw.get("add_paused", engine["add_paused"])),
            "ich": bool(raw.get("ich", engine["ich"])),
            "aich": bool(raw.get("aich", engine["aich"])),
            "upnp": bool(engine.get("upnp")),
            "ipfilter": bool(raw.get("ipfilter", engine["ipfilter"])),
            "user_hash": raw.get("user_hash") or "",
            "raw": raw,
        }
        return result

    def apply_prefs(self, patch):
        """把面板设置写回 aMule（EC SET_PREFERENCES），返回生效项与需重启项。"""
        patch = patch or {}
        if not isinstance(patch, dict):
            raise EmuleError("设置补丁必须是 JSON 对象")
        _tag_string, _tag_uint, _tag_node = tag_string, tag_uint, tag_node
        general = []
        connections = []
        files = []
        directories = []
        security = []
        applied = []
        restart_required = []

        if "nick" in patch and patch["nick"]:
            general.append(_tag_string(Tag.USER_NICK, str(patch["nick"])))
            applied.append("nick")
        if "max_download" in patch:
            connections.append(_tag_uint(Tag.CONN_MAX_DL, int(patch["max_download"] or 0)))
            applied.append("max_download")
        if "max_upload" in patch:
            connections.append(_tag_uint(Tag.CONN_MAX_UL, int(patch["max_upload"] or 0)))
            applied.append("max_upload")
        if "max_connections" in patch:
            connections.append(_tag_uint(Tag.CONN_MAX_CONN,
                                         int(patch["max_connections"] or 500)))
            applied.append("max_connections")
        if "max_sources" in patch:
            connections.append(_tag_uint(Tag.CONN_MAX_FILE_SOURCES,
                                         int(patch["max_sources"] or 300)))
            applied.append("max_sources")
        if "tcp_port" in patch:
            connections.append(_tag_uint(Tag.CONN_TCP_PORT, int(patch["tcp_port"] or 4662)))
            applied.append("tcp_port")
            restart_required.append("tcp_port")
        if "udp_port" in patch:
            connections.append(_tag_uint(Tag.CONN_UDP_PORT, int(patch["udp_port"] or 4672)))
            applied.append("udp_port")
            restart_required.append("udp_port")
        if "autoconnect" in patch:
            connections.append(_tag_uint(Tag.CONN_AUTOCONNECT,
                                         1 if patch["autoconnect"] else 0))
            applied.append("autoconnect")
        if "connect_ed2k" in patch:
            connections.append(_tag_uint(Tag.NETWORK_ED2K,
                                         1 if patch["connect_ed2k"] else 0))
            applied.append("connect_ed2k")
        if "connect_kad" in patch:
            connections.append(_tag_uint(Tag.NETWORK_KADEMLIA,
                                         1 if patch["connect_kad"] else 0))
            applied.append("connect_kad")
        if "ich" in patch:
            files.append(_tag_uint(Tag.FILES_ICH_ENABLED, 1 if patch["ich"] else 0))
            applied.append("ich")
        if "aich" in patch:
            files.append(_tag_uint(Tag.FILES_AICH_TRUST, 0 if patch["aich"] else 1))
            applied.append("aich")
        if "add_paused" in patch:
            files.append(_tag_uint(Tag.FILES_NEW_PAUSED, 1 if patch["add_paused"] else 0))
            applied.append("add_paused")
        if patch.get("incoming_dir"):
            directories.append(_tag_string(Tag.DIRECTORIES_INCOMING, patch["incoming_dir"]))
            applied.append("incoming_dir")
            restart_required.append("incoming_dir")
        if patch.get("temp_dir"):
            directories.append(_tag_string(Tag.DIRECTORIES_TEMP, patch["temp_dir"]))
            applied.append("temp_dir")
            restart_required.append("temp_dir")
        if isinstance(patch.get("shared_dirs"), (list, tuple)):
            shared = list(patch["shared_dirs"])
            container = _tag_uint(Tag.DIRECTORIES_SHARED, len(shared))
            for path in shared:
                container.children.append(_tag_string(Tag.STRING, path))
            directories.append(container)
            applied.append("shared_dirs")
        if "ipfilter" in patch:
            enabled = bool(patch["ipfilter"])
            security.append(_tag_uint(Tag.IPFILTER_CLIENTS, 1 if enabled else 0))
            security.append(_tag_uint(Tag.IPFILTER_SERVERS, 1 if enabled else 0))
            applied.append("ipfilter")
        # 下面这些只能落到 amule.conf（EC 没有对应偏好项），改完要重启引擎
        for key, label in (("upnp", "upnp"), ("ec_port", "ec_port"),
                           ("ec_password", "ec_password"), ("tcp_port", "tcp_port"),
                           ("udp_port", "udp_port")):
            if key in patch:
                restart_required.append(label)
                if label not in applied:
                    applied.append(label)

        if not applied:
            raise EmuleError("没有可应用的设置项")

        nodes = []
        if general:
            nodes.append(_tag_node(Tag.PREFS_GENERAL, general))
        if connections:
            nodes.append(_tag_node(Tag.PREFS_CONNECTIONS, connections))
        if files:
            nodes.append(_tag_node(Tag.PREFS_FILES, files))
        if directories:
            nodes.append(_tag_node(Tag.PREFS_DIRECTORIES, directories))
        if security:
            nodes.append(_tag_node(Tag.PREFS_SECURITY, security))

        if nodes:
            client = self._online_client()
            client.set_prefs(nodes)
        # 端口 / 目录 / UPnP 这类要落到 amule.conf，下次启动生效
        if restart_required:
            engine = self._engine_settings()
            merged = dict(engine)
            for key in ("tcp_port", "udp_port", "incoming_dir", "temp_dir", "shared_dirs",
                        "nick", "max_download", "max_upload", "max_connections",
                        "max_sources", "add_paused", "ich", "aich", "ipfilter", "upnp",
                        "ec_port", "ec_password"):
                if key in patch and patch[key] not in (None, ""):
                    merged[key] = patch[key]
            self._ctl.write_conf(merged)
        return {
            "ok": True,
            "applied": applied,
            "restart_required": sorted(set(restart_required)),
            "message": "设置已生效" if not restart_required
                       else "设置已保存，重启引擎后生效",
        }
