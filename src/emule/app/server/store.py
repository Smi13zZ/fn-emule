#!/usr/bin/env python3
"""fn-emule 面板持久层：settings.json / 速度历史 / 面板日志 / 配置备份。

docs/CONTRACT.md §2 §5 界定了这一层的职责与数据形状：

    $TRIM_PKGVAR/settings.json    面板 + 引擎 + 通知 + 备份 + 更新配置
    $TRIM_PKGVAR/panel.log        面板自身日志（引擎日志由 core.service 提供）
    $TRIM_PKGVAR/history/         通知投递记录等历史数据
    $TRIM_PKGVAR/backups/         tar.gz 配置备份
    $TRIM_PKGVAR/updates/         更新检查下载下来的 .fpk
    $TRIM_PKGVAR/amule/           aMule 配置目录（core 负责写，面板只做备份/恢复）

三条硬规则：
1. settings.json 一律「临时文件 + os.replace」原子替换，绝不原地截断 —— 掉电时
   最坏也只是丢掉这一次改动，不会把配置写成半个 JSON 让面板再也起不来。
2. 速度历史是内存环形缓冲（120 点，3 秒一个点），重启归零；aMule 自己也只给
   瞬时速度，把它落盘反而制造「有历史但其实不准」的错觉。
3. 备份只装配置（settings.json + amule.conf + server.met + nodes.dat），绝不装
   Incoming/ 与 Temp/：那是用户几十上百 GB 的下载数据。
"""
import collections
import copy
import json
import os
import re
import secrets
import tarfile
import threading
import time

# --------------------------------------------------------------------------
# 常量（与 CONTRACT §1 §5 对齐）
# --------------------------------------------------------------------------
DEFAULT_PANEL_PORT = 17581
DEFAULT_EC_PORT = 4712
DEFAULT_TCP_PORT = 4662
DEFAULT_UDP_PORT = 4672

HISTORY_MAX = 120
NOTIFY_LOG_MAX = 500
BACKUP_KEEP_MIN = 1
BACKUP_KEEP_MAX = 60
LOG_MAX_BYTES = 2 * 1024 * 1024
LOG_READ_BYTES = 256 * 1024

VERSION_FALLBACK = "26.11.0"

SERVER_MET_URL = "https://upd.emule-security.org/server.met"
NODES_DAT_URL = "https://upd.emule-security.org/nodes.dat"
UPDATE_REPO = "Smi13zZ/fn-emule"

# 备份成员：归档内路径 -> 相对 var 目录的源文件。只允许这四个，恢复也按同一张表。
BACKUP_MEMBERS = (
    ("settings.json", "settings.json"),
    ("amule/amule.conf", os.path.join("amule", "amule.conf")),
    ("amule/server.met", os.path.join("amule", "server.met")),
    ("amule/nodes.dat", os.path.join("amule", "nodes.dat")),
)
BACKUP_EXTS = (".tar.gz",)

SECRET_MARK = "__SET__"

_LOG_LINE = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}) \[([a-z]+)\] (.*)$")


def _env_int(env, name, fallback):
    """环境变量里的端口/小时数：非法值一律退回默认值，不让面板因为一个错字起不来。"""
    try:
        raw = str((env or {}).get(name, "") or "").strip()
        if not raw:
            return int(fallback)
        return int(raw)
    except (TypeError, ValueError):
        return int(fallback)


def default_settings(env=None, share_dir=""):
    """CONTRACT §5 的默认配置。首次启动时写入 settings.json。

    端口优先取安装向导（cmd/main 通过 EMULE_DEFAULT_* 环境变量传进来），
    ec_password 每次首启随机生成 —— 与 amule.conf 里的密码保持一致由 core 保证。
    """
    env = env if env is not None else os.environ
    share = share_dir or os.path.join("/var/apps/fn-emule", "shares", "fn-emule")
    return {
        "panel": {
            "port": _env_int(env, "EMULE_PANEL_PORT", DEFAULT_PANEL_PORT),
            "theme": "auto",
            "lang": "zh",
        },
        "engine": {
            "ec_port": _env_int(env, "EMULE_DEFAULT_EC_PORT", DEFAULT_EC_PORT),
            "ec_password": secrets.token_hex(8),
            "tcp_port": _env_int(env, "EMULE_DEFAULT_TCP_PORT", DEFAULT_TCP_PORT),
            "udp_port": _env_int(env, "EMULE_DEFAULT_UDP_PORT", DEFAULT_UDP_PORT),
            "nick": "fnOS@eMule",
            "incoming_dir": os.path.join(share, "Incoming"),
            "temp_dir": os.path.join(share, "Temp"),
            "shared_dirs": [os.path.join(share, "Incoming")],
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
        },
        "bootstrap": {
            "server_met_url": SERVER_MET_URL,
            "nodes_dat_url": NODES_DAT_URL,
            "auto_hours": 24,
            "last_update": 0,
        },
        "notify": {
            "enabled": False,
            "channels": [],
            "events": {"complete": True, "error": True},
        },
        "backup": {"auto": False, "keep": 7, "last": 0},
        "update": {"repo": UPDATE_REPO, "check": True, "last": 0, "latest": ""},
    }


def _preserve_channel_secrets(channels, existing):
    """整份配置保存时，通知通道里被打码的密钥必须保留原值。

    GET /api/settings 会把已保存的密钥换成 SECRET_MARK 再回给浏览器；浏览器如果
    把拿到的那份 settings 原样 POST 回来（改主题、切语言、保存别的分区都会这么做），
    channels 是 list、deep_merge 对 list 是整体替换，密钥就被字面量 "__SET__"
    覆盖掉了 —— 之后的推送全是 400，而且界面上看不出来（输入框本来就显示「已保存」）。

    所以凡是带 id 的通道，都用 notify.merge_config 跟旧配置合并一次：
    提交的是打码值或空串就沿用原密钥，提交了新值才替换。
    """
    if not isinstance(channels, list):
        return channels
    import notify as notifymod            # 延迟导入：store 是持久层，不该在导入期依赖通道定义
    by_id = {}
    for channel in existing or []:
        if isinstance(channel, dict) and channel.get("id"):
            by_id[str(channel.get("id"))] = channel
    out = []
    for channel in channels:
        if not isinstance(channel, dict):
            out.append(channel)
            continue
        old = by_id.get(str(channel.get("id") or ""))
        if not old:
            out.append(copy.deepcopy(channel))
            continue
        item = copy.deepcopy(channel)
        item["config"] = notifymod.merge_config(
            channel.get("type") or old.get("type"),
            channel.get("config") if isinstance(channel.get("config"), dict) else {},
            old.get("config") if isinstance(old.get("config"), dict) else {})
        out.append(item)
    return out


def deep_merge(base, patch):
    """递归合并：dict 逐键合并，list 与标量整体替换。返回新对象，不改入参。"""
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    if not isinstance(patch, dict):
        return out
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _clamp_int(value, low, high, fallback):
    try:
        num = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(low, min(high, num))


class Store(object):
    """所有面板配置与记录的落盘入口。线程安全（内部 RLock）。"""

    def __init__(self, var_dir, share_dir="", app_home="", version=""):
        self.var_dir = os.path.abspath(var_dir)
        self.app_home = app_home or ""
        self.version = str(version or VERSION_FALLBACK)
        self.share_dir = os.path.abspath(share_dir) if share_dir else self._guess_share_dir()

        self.path = os.path.join(self.var_dir, "settings.json")
        self.log_path = os.path.join(self.var_dir, "panel.log")
        self.amule_dir = os.path.join(self.var_dir, "amule")
        self.backup_dir = os.path.join(self.var_dir, "backups")
        self.update_dir = os.path.join(self.var_dir, "updates")
        self.history_dir = os.path.join(self.var_dir, "history")
        self.notify_log_path = os.path.join(self.history_dir, "notify-log.json")

        self._lock = threading.RLock()
        self._history = collections.deque(maxlen=HISTORY_MAX)
        self.data = {}

    # -- 路径 ---------------------------------------------------------------
    def _guess_share_dir(self):
        """var 目录的兄弟 shares/fn-emule 就是 fnOS 的 data-share 落点。

        /var/apps/fn-emule/var -> /var/apps/fn-emule/shares/fn-emule
        本地开发 tmp/var       -> tmp/shares/fn-emule
        """
        parent = os.path.dirname(self.var_dir)
        return os.path.join(parent, "shares", "fn-emule")

    def ensure_dirs(self):
        """建齐运行时目录。共享目录按 CONTRACT 要求 0777（fnOS 的 data-share 由
        普通用户和 root 共同读写，权限太紧会让下载完成的文件拿不出来）。"""
        targets = [
            (self.var_dir, 0o777),
            (self.amule_dir, 0o777),
            (self.backup_dir, 0o777),
            (self.history_dir, 0o777),
            (self.update_dir, 0o755),
            (self.share_dir, 0o777),
        ]
        settings = self.data.get("engine") or {}
        for key in ("incoming_dir", "temp_dir"):
            path = str(settings.get(key) or "").strip()
            if path:
                targets.append((path, 0o777))
        for path in settings.get("shared_dirs") or []:
            path = str(path or "").strip()
            if path:
                targets.append((path, 0o777))
        made = []
        for path, mode in targets:
            try:
                os.makedirs(path, exist_ok=True)
                made.append(path)
            except OSError:
                continue
            try:
                os.chmod(path, mode)
            except OSError:
                pass
        return made

    # -- settings -----------------------------------------------------------
    def load(self):
        """读 settings.json；不存在或读坏了就按 §5 生成默认配置并落盘。

        已存在的文件会与默认值做一次浅合并，这样升级新增的配置项能自动补上，
        老版本缺少的键不会让 UI 拿到 undefined。
        """
        with self._lock:
            fresh = False
            raw = None
            try:
                with open(self.path, "r", encoding="utf-8") as handle:
                    raw = json.load(handle)
            except (OSError, ValueError):
                raw = None
            if not isinstance(raw, dict):
                raw = {}
                fresh = True
            defaults = default_settings(share_dir=self.share_dir)
            merged = deep_merge(defaults, raw)
            changed = fresh or merged != raw
            self.data = merged
            if changed:
                self.save()
                if fresh:
                    self.log("首次启动：已生成默认配置 %s（面板端口 %s）"
                             % (self.path, merged["panel"]["port"]))
            return self.data

    def save(self):
        """原子写：同目录临时文件 -> fsync -> os.replace。"""
        with self._lock:
            try:
                os.makedirs(self.var_dir, exist_ok=True)
            except OSError as exc:
                raise ValueError("运行时目录不可写：%s（%s）" % (self.var_dir, exc))
            tmp = self.path + ".tmp"
            payload = json.dumps(self.data, ensure_ascii=False, indent=2, sort_keys=False)
            try:
                with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                    handle.write(payload)
                    handle.flush()
                    try:
                        os.fsync(handle.fileno())
                    except OSError:
                        pass
                os.replace(tmp, self.path)
                try:
                    os.chmod(self.path, 0o600)
                except OSError:
                    pass
            except OSError as exc:
                self.log("settings.json 写入失败：%s" % (exc,), level="error")
                raise
            return True

    def settings(self):
        """给 core.service 的 settings_provider 用：返回副本，避免被引擎侧改坏。"""
        with self._lock:
            return copy.deepcopy(self.data)

    def section(self, name):
        with self._lock:
            value = self.data.get(name)
            return copy.deepcopy(value) if isinstance(value, dict) else {}

    def update(self, patch):
        """把 patch 深合并进配置并落盘，返回 (最新配置, 变动的顶层分区集合)。

        engine.ec_password 传空串或打码标记时保留原值 —— 前端拿到的永远是打码值，
        原样回传不能把真实密码覆盖没了。
        """
        if not isinstance(patch, dict):
            return self.settings(), set()
        patch = copy.deepcopy(patch)
        engine_patch = patch.get("engine")
        if isinstance(engine_patch, dict):
            password = engine_patch.get("ec_password")
            if password is None or str(password).strip() in ("", SECRET_MARK, "__KEEP__"):
                engine_patch.pop("ec_password", None)
            else:
                engine_patch["ec_password"] = str(password).strip()
        notify_patch = patch.get("notify")
        if isinstance(notify_patch, dict) and "channels" in notify_patch:
            # 整份保存时把打码的通道密钥还原成真实值（见 _preserve_channel_secrets）
            with self._lock:
                existing = copy.deepcopy((self.data.get("notify") or {}).get("channels") or [])
            notify_patch["channels"] = _preserve_channel_secrets(
                notify_patch["channels"], existing)
        with self._lock:
            before = self.data
            merged = deep_merge(before, patch)
            changed = set()
            for key in set(list(before.keys()) + list(merged.keys())):
                if before.get(key) != merged.get(key):
                    changed.add(key)
            self.data = merged
            if changed:
                self.save()
            return self.settings(), changed

    def masked(self):
        """GET /api/settings 的载荷：引擎密码打码，通知渠道密钥由 notify 处理。"""
        out = self.settings()
        engine = out.get("engine")
        if isinstance(engine, dict):
            engine["ec_password"] = SECRET_MARK if engine.get("ec_password") else ""
        return out

    def set_value(self, section, key, value):
        with self._lock:
            target = self.data.setdefault(section, {})
            if not isinstance(target, dict):
                target = {}
                self.data[section] = target
            target[key] = value
            self.save()
            return value

    # -- 面板日志 -----------------------------------------------------------
    def log(self, message, level="info"):
        """写 panel.log。超过 2MB 直接轮转成 .1（只留一份，够排查即可）。"""
        text = str(message).replace("\n", " ").strip()
        line = "%s [%s] %s\n" % (time.strftime("%Y-%m-%d %H:%M:%S"), level, text)
        if os.environ.get("EMULE_DEBUG"):
            try:
                print(line.rstrip(), flush=True)
            except Exception:
                pass
        try:
            try:
                if os.path.getsize(self.log_path) > LOG_MAX_BYTES:
                    os.replace(self.log_path, self.log_path + ".1")
            except OSError:
                pass
            with open(self.log_path, "a", encoding="utf-8") as handle:
                handle.write(line)
        except OSError:
            pass

    def read_log(self, limit=200):
        """读日志尾部 limit 行，返回 [{t, level, text}]，旧的在前。"""
        try:
            limit = max(1, min(2000, int(limit)))
        except (TypeError, ValueError):
            limit = 200
        raw = ""
        try:
            size = os.path.getsize(self.log_path)
            with open(self.log_path, "rb") as handle:
                if size > LOG_READ_BYTES:
                    handle.seek(-LOG_READ_BYTES, os.SEEK_END)
                raw = handle.read().decode("utf-8", "replace")
        except OSError:
            return []
        lines = raw.splitlines()
        # 从文件中间开始读时第一行可能只剩半行，丢掉它
        if len(lines) > 1 and not raw.startswith("\n") and not _LOG_LINE.match(lines[0]):
            lines = lines[1:]
        out = []
        for line in lines[-limit:]:
            match = _LOG_LINE.match(line)
            if match:
                stamp, level, text = match.groups()
                try:
                    ts = int(time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")))
                except (ValueError, OverflowError):
                    ts = int(time.time())
                out.append({"t": ts, "level": level, "text": text})
            else:
                out.append({"t": int(time.time()), "level": "info", "text": line})
        return out

    # -- 速度历史 -----------------------------------------------------------
    def push_history(self, down, up, t=None):
        try:
            entry = {
                "t": int(t if t is not None else time.time()),
                "down": int(max(0, down)),
                "up": int(max(0, up)),
            }
        except (TypeError, ValueError):
            return
        with self._lock:
            self._history.append(entry)

    def history(self, limit=60):
        with self._lock:
            items = list(self._history)
        try:
            limit = max(1, min(HISTORY_MAX, int(limit)))
        except (TypeError, ValueError):
            limit = 60
        return items[-limit:]

    def history_size(self):
        with self._lock:
            return len(self._history)

    # -- 通知投递记录 -------------------------------------------------------
    def notify_records(self):
        """最新在前。文件坏了就当空记录，不让通知页整页报错。"""
        try:
            with open(self.notify_log_path, "r", encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            return []
        records = data.get("records") if isinstance(data, dict) else data
        if not isinstance(records, list):
            return []
        return [item for item in records if isinstance(item, dict)]

    def _save_notify_records(self, records):
        try:
            os.makedirs(self.history_dir, exist_ok=True)
            tmp = self.notify_log_path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                json.dump({"records": records}, handle, ensure_ascii=False, indent=1)
            os.replace(tmp, self.notify_log_path)
        except OSError as exc:
            self.log("通知记录写入失败：%s" % (exc,), level="error")

    def add_notify_record(self, record):
        if not isinstance(record, dict):
            return None
        with self._lock:
            records = self.notify_records()
            records.insert(0, record)
            del records[NOTIFY_LOG_MAX:]
            self._save_notify_records(records)
        return record

    def clear_notify_records(self):
        with self._lock:
            self._save_notify_records([])

    # -- 备份 ---------------------------------------------------------------
    def backup_name(self, tag="manual"):
        stamp = time.strftime("%Y%m%d-%H%M%S")
        safe_tag = re.sub(r"[^a-zA-Z0-9_-]+", "", str(tag or "manual"))[:16] or "manual"
        base = "emule-%s-%s-%s" % (self.version, stamp, safe_tag)
        name = base + ".tar.gz"
        index = 1
        while os.path.exists(os.path.join(self.backup_dir, name)):
            name = "%s-%d.tar.gz" % (base, index)
            index += 1
        return name

    def backup_create(self, tag="manual", keep=None):
        """打包四样配置。返回 {name,path,size,t,files,removed}。"""
        with self._lock:
            os.makedirs(self.backup_dir, exist_ok=True)
            name = self.backup_name(tag)
            dest = os.path.join(self.backup_dir, name)
            included = []
            tmp = dest + ".part"
            try:
                with tarfile.open(tmp, "w:gz") as archive:
                    for arcname, relpath in BACKUP_MEMBERS:
                        source = os.path.join(self.var_dir, relpath)
                        if not os.path.isfile(source):
                            continue
                        try:
                            archive.add(source, arcname=arcname)
                            included.append(arcname)
                        except (OSError, tarfile.TarError) as exc:
                            self.log("备份跳过 %s：%s" % (arcname, exc), level="warn")
                os.replace(tmp, dest)
            except (OSError, tarfile.TarError) as exc:
                try:
                    os.remove(tmp)
                except OSError:
                    pass
                raise ValueError("备份失败：%s" % (exc,))
            keep = _clamp_int(
                keep if keep is not None else (self.data.get("backup") or {}).get("keep", 7),
                BACKUP_KEEP_MIN, BACKUP_KEEP_MAX, 7)
            removed = self.backup_prune(keep, protect=name)
            backup_cfg = self.data.setdefault("backup", {})
            if isinstance(backup_cfg, dict):
                backup_cfg["last"] = int(time.time())
                self.save()
            try:
                size = os.path.getsize(dest)
            except OSError:
                size = 0
            self.log("配置备份完成：%s（%d 字节，%d 个文件，清理 %d 份）"
                     % (name, size, len(included), removed))
            return {
                "name": name,
                "path": dest,
                "size": size,
                "t": int(time.time()),
                "files": included,
                "removed": removed,
                "keep": keep,
            }

    def backup_path(self, name):
        """恢复只允许 backups 目录下的 .tar.gz —— 传 ../../ 一律当不存在。"""
        safe = os.path.basename(str(name or "").strip())
        if not safe or safe != str(name or "").strip():
            return ""
        if not safe.endswith(BACKUP_EXTS):
            return ""
        target = os.path.join(self.backup_dir, safe)
        if not os.path.isfile(target):
            return ""
        return target

    def backup_delete(self, name):
        """删除一份备份。名字校验与恢复完全一致（只认 backups 目录下的 .tar.gz）。"""
        path = self.backup_path(name)
        if not path:
            raise ValueError("备份文件不存在")
        try:
            os.remove(path)
        except OSError as exc:
            raise ValueError("删除失败：%s" % (exc,))
        self.log("已删除配置备份：%s" % os.path.basename(path))
        return {"name": os.path.basename(path), "removed": True}

    def backup_list(self):
        items = []
        try:
            names = os.listdir(self.backup_dir)
        except OSError:
            return items
        for name in names:
            if not name.endswith(BACKUP_EXTS):
                continue
            path = os.path.join(self.backup_dir, name)
            try:
                stat = os.stat(path)
            except OSError:
                continue
            items.append({"name": name, "size": int(stat.st_size), "t": int(stat.st_mtime)})
        items.sort(key=lambda item: item["t"], reverse=True)
        return items

    def backup_prune(self, keep, protect=""):
        """从旧到新删，保留最新 keep 份；protect（刚生成的那份）永远保留。"""
        keep = _clamp_int(keep, BACKUP_KEEP_MIN, BACKUP_KEEP_MAX, 7)
        kept = 0
        removed = 0
        for item in self.backup_list():
            if item["name"] == protect or kept < keep:
                kept += 1
                continue
            try:
                os.remove(os.path.join(self.backup_dir, item["name"]))
                removed += 1
            except OSError:
                continue
        return removed

    def backup_restore(self, name):
        """从 backups 目录恢复。返回 {name, files:[...]}。

        只解出白名单里的成员，其它成员（比如有人手工塞进来的 partfiles）直接忽略，
        绝不让归档里的路径决定写到哪里。
        """
        path = self.backup_path(name)
        if not path:
            raise ValueError("备份文件不存在")
        allowed = {}
        for arcname, relpath in BACKUP_MEMBERS:
            allowed[arcname] = relpath
        restored = []
        settings_blob = None
        amule_payload = {}
        with tarfile.open(path, "r:gz") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name_in_tar = member.name.lstrip("./")
                if name_in_tar not in allowed:
                    continue
                handle = archive.extractfile(member)
                if handle is None:
                    continue
                blob = handle.read()
                if name_in_tar == "settings.json":
                    settings_blob = blob
                    continue
                amule_payload[name_in_tar] = blob
            if settings_blob is None and not amule_payload:
                raise ValueError("备份包里没有可恢复的配置")
            if settings_blob is not None:
                try:
                    parsed = json.loads(settings_blob.decode("utf-8", "replace"))
                except ValueError as exc:
                    raise ValueError("备份里的 settings.json 无法解析：%s" % (exc,))
                if not isinstance(parsed, dict):
                    raise ValueError("备份里的 settings.json 格式不对")
                merged = deep_merge(default_settings(share_dir=self.share_dir), parsed)
                with self._lock:
                    self.data = merged
                    self.save()
                restored.append("settings.json")
            for arcname, blob in amule_payload.items():
                target = os.path.join(self.var_dir, allowed[arcname])
                try:
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    tmp = target + ".tmp"
                    with open(tmp, "wb") as handle:
                        handle.write(blob)
                    os.replace(tmp, target)
                    restored.append(arcname)
                except OSError as exc:
                    self.log("恢复 %s 失败：%s" % (arcname, exc), level="error")
        self.log("配置已从 %s 恢复：%s" % (os.path.basename(path), ", ".join(restored)))
        return {"name": os.path.basename(path), "files": restored}

    # -- 运行时端口文件 -----------------------------------------------------
    def write_runtime_ports(self, port):
        """把实际监听端口写进 var/runtime-ports.env（cmd/main 与 CGI 代理都读它）。

        格式必须和 cmd/main 写的完全一致（三行），否则「面板实际端口」与「CGI 转发
        目标」会漂移 —— v26.11.3 升级后 17581/8899 不一致就是这么来的。
        """
        try:
            port = int(port)
        except (TypeError, ValueError):
            return False
        if port < 1 or port > 65535:
            return False
        path = os.path.join(self.var_dir, "runtime-ports.env")
        try:
            os.makedirs(self.var_dir, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as handle:
                handle.write("BACKEND_PORT=%d\n" % port)
                handle.write("ADMIN_TARGET_PORT=%d\n" % port)
                handle.write("ADMIN_TARGET_HOST=127.0.0.1\n")
                handle.flush()
                try:
                    os.fsync(handle.fileno())
                except OSError:
                    pass
            os.replace(tmp, path)
            try:
                os.chmod(path, 0o600)
            except OSError:
                pass
            return True
        except OSError as exc:
            self.log("runtime-ports.env 写入失败：%s" % (exc,), level="warn")
            return False

    # -- 更新下载 -----------------------------------------------------------
    def updates_dir(self):
        try:
            os.makedirs(self.update_dir, exist_ok=True)
        except OSError:
            pass
        return self.update_dir
