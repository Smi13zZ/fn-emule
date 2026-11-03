#!/usr/bin/env python3
"""fn-emule 面板后端：HTTP 服务 + 路由 + 静态托管。

一个进程同时是三样东西：

1. HTTP 服务（ThreadingHTTPServer，监听 0.0.0.0:17581，fnOS 的 CGI 代理需要
   走本机回环），按 docs/CONTRACT.md §3 提供 ./api 下的全部接口；
2. 静态服务器，把 <app_home>/web 原样发给浏览器（no-store，不做 history 路由，
   视图状态全在前端 JS 里）；
3. aMule 引擎的所有者：启动时 service.prepare() + service.start()，收到
   SIGTERM/SIGINT 时先 service.stop() 再退出，绝不留孤儿 amuled。

引擎逻辑一行都不在这里 —— 全部通过 core.service.EmuleService 门面调用，
导入失败或引擎没起来时面板照常监听端口，前端可以一键重启引擎。

本地联调（不需要 aMule）：
    python src/emule/app/server/emulepanel.py --port 17581 --fake-service --var tmp/var
"""
import argparse
import ipaddress
import json
import mimetypes
import os
import queue
import re
import shlex
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import uuid

SERVER_DIR = os.path.dirname(os.path.abspath(__file__))
if SERVER_DIR not in sys.path:
    sys.path.insert(0, SERVER_DIR)

from html import unescape as html_unescape  # noqa: E402
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer  # noqa: E402

import netutil  # noqa: E402
import notify  # noqa: E402
import store as storemod  # noqa: E402

VERSION_FALLBACK = "26.11.0"
DEFAULT_PORT = storemod.DEFAULT_PANEL_PORT
DATA_TIMEOUT = 15.0        # CONTRACT：任何 /api 请求最多 15 秒，超时 504
CONTROL_TIMEOUT = 15.0     # 引擎启停同样受 15 秒约束
HEALTH_TIMEOUT = 2.5
SAMPLE_INTERVAL = 3.0      # 速度历史采样间隔（CONTRACT §8）
NOTIFY_INTERVAL = 5.0      # 任务完成/出错检测间隔
BACKUP_CHECK_INTERVAL = 300.0
HISTORY_POINTS = 60        # /api/overview 返回最近 60 点
UPDATE_TTL = 900
UPDATE_FAIL_TTL = 60

EXTRA_MIME = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff": "font/woff",
    ".woff2": "font/woff2",
    ".ttf": "font/ttf",
    ".map": "application/json; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".webmanifest": "application/manifest+json; charset=utf-8",
}

RT = None  # 运行期单例，Handler 通过它访问 store / engine / 配置


# --------------------------------------------------------------------------
# 异常与错误映射
# --------------------------------------------------------------------------
class EngineTimeout(Exception):
    """引擎在预算时间内没有回话。"""


class OfflineError(Exception):
    """引擎未运行 / EC 连不上。"""


class EngineFailure(Exception):
    """引擎返回的业务错误（EmuleError）。"""


class ServiceMissing(Exception):
    """core.service 不可用 —— 面板处于降级模式。"""


def is_timeout_message(message):
    """EC 读超时和「引擎没起」抛的是同一个 EmuleOffline，只能靠消息里的字样区分：
    超时类要回 504（引擎还在，只是没按时回包），其余回 503（引擎真的不可用）。"""
    text = str(message or "").lower()
    for word in ("超时", "timeout", "timed out"):
        if word in text:
            return True
    return False


def error_status(message):
    """业务错误落成 4xx 还是 5xx：能怪用户输入的就 400。"""
    text = str(message or "")
    for keyword in ("参数", "无效", "找不到", "不存在", "不支持", "不能为空", "已存在", "格式"):
        if keyword in text:
            return 400
    return 500


# --------------------------------------------------------------------------
# 路径与版本
# --------------------------------------------------------------------------
def resolve_app_home(explicit=""):
    home = (explicit or os.environ.get("EMULE_APP_HOME")
            or os.environ.get("TRIM_APPDEST") or "").strip()
    if home:
        return os.path.abspath(home)
    # 本地开发：本文件在 <app>/server/ 下
    return os.path.dirname(SERVER_DIR)


def resolve_var_dir(explicit=""):
    var = (explicit or os.environ.get("EMULE_VAR")
           or os.environ.get("TRIM_PKGVAR") or "").strip()
    if var:
        return os.path.abspath(var)
    # 与 core.service.default_var_dir() 对齐：fnOS 上固定是 /var/apps/fn-emule/var；
    # 开发机（没有 /var/apps）退回仓库里的 tmp/var。
    if os.path.isdir("/var/apps"):
        return "/var/apps/fn-emule/var"
    repo_root = os.path.abspath(os.path.join(SERVER_DIR, "..", "..", "..", ".."))
    return os.path.join(repo_root, "tmp", "var")


def resolve_share_dir(app_home):
    share = (os.environ.get("EMULE_SHARE_DIR") or "").strip()
    if share:
        return os.path.abspath(share)
    app_root = (os.environ.get("EMULE_APP_ROOT") or "").strip()
    if app_root:
        return os.path.join(app_root, "shares", "fn-emule")
    return os.path.join(os.path.dirname(app_home), "shares", "fn-emule")


def resolve_version():
    version = (os.environ.get("EMULE_VERSION") or "").strip()
    if version:
        return version
    # 仓库布局是 src/emule/manifest；装进 fpk 后 fnOS 把 app/** 摊平，manifest 直接
    # 落在 <APPDEST>/ 下。两个位置都试一下（cmd/main 正常会先给 EMULE_VERSION）。
    app_dir = os.path.dirname(SERVER_DIR)
    for manifest in (os.path.join(app_dir, "..", "manifest"),
                     os.path.join(app_dir, "manifest")):
        try:
            with open(manifest, "r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip().startswith("version"):
                        value = line.split("=", 1)[1].strip()
                        if value:
                            return value
        except (OSError, IndexError):
            continue
    return VERSION_FALLBACK


# --------------------------------------------------------------------------
# 引擎调用：单线程队列 + 超时
#
# aMule 的 EC 客户端不是线程安全的，所有引擎调用排成一队由一个 daemon 线程执行，
# 既是最干净的串行化，也保证「一次卡死的 EC 调用不会连累进程退出」（daemon 线程）。
# 调用方最多等 timeout 秒，等不到就抛 EngineTimeout -> 504。
# --------------------------------------------------------------------------
class EngineBox(object):
    def __init__(self):
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._loop, name="engine", daemon=True)
        self._closed = False
        self._thread.start()

    def _loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            fn, args, kwargs, box = item
            try:
                box["value"] = fn(*args, **kwargs)
                box["ok"] = True
            except BaseException as exc:  # noqa: BLE001 - 原样回传给调用方
                box["exc"] = exc
            finally:
                box["done"].set()

    def call(self, fn, args=(), kwargs=None, timeout=DATA_TIMEOUT):
        if self._closed:
            raise ServiceMissing("引擎组件已关闭")
        box = {"done": threading.Event(), "ok": False, "value": None, "exc": None}
        self._queue.put((fn, args, kwargs or {}, box))
        if not box["done"].wait(max(0.1, float(timeout))):
            raise EngineTimeout("引擎响应超时")
        if not box["ok"]:
            raise box["exc"] if box["exc"] is not None else RuntimeError("引擎调用失败")
        return box["value"]

    def close(self):
        self._closed = True
        try:
            self._queue.put(None)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 更新检查
# --------------------------------------------------------------------------
def version_tuple(value):
    nums = [int(part) for part in re.findall(r"\d+", str(value or ""))[:4]]
    while len(nums) < 4:
        nums.append(0)
    return tuple(nums)


def strip_html(raw):
    """Atom 里的正文是转义过的 HTML，摊平成可读文本给界面展示。"""
    text = html_unescape(raw or "")
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<li[^>]*>", "· ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\n{3,}", "\n\n", html_unescape(text)).strip()


class UpdateChecker(object):
    """GET /api/update/check 的实现。

    只打 GitHub 官方 API，结果缓存 15 分钟（匿名 60 次/小时的限额很容易打满）；
    仓库还没发版时 GitHub 返回 404，这里必须优雅地变成 state=no_release，
    而不是把异常甩到界面。
    """

    def __init__(self, store):
        self.store = store
        self._lock = threading.Lock()
        self._cache = {"at": 0.0, "payload": None}
        self._fail = {"at": 0.0, "payload": None}

    def repo(self):
        cfg = self.store.section("update")
        repo = str(cfg.get("repo") or "Smi13zZ/fn-emule").strip().strip("/")
        return repo or "Smi13zZ/fn-emule"

    def _blank(self, state, error=""):
        repo = self.repo()
        return {
            "ok": state != "error",
            "available": False,
            "has_update": False,
            "state": state,
            "error": error,
            "current": RT.version,
            "latest": "",
            "tag": "",
            "name": "",
            "notes": "",
            "published_at": "",
            "url": "",
            "assets": [],
            "repo": repo,
            "checked_at": int(time.time()),
            "cached": False,
        }

    # -- 三个来源：REST API / releases.atom / expanded_assets -----------------
    def _from_api(self, repo):
        data = netutil.get_json("https://api.github.com/repos/%s/releases/latest" % repo,
                                timeout=10.0, retries=1,
                                accept="application/vnd.github+json")
        if not isinstance(data, dict):
            raise netutil.FetchError("GitHub 返回的数据格式不对")
        return {
            "tag": str(data.get("tag_name") or data.get("name") or "").strip(),
            "name": str(data.get("name") or ""),
            "notes": str(data.get("body") or ""),
            "published_at": str(data.get("published_at") or ""),
            "url": str(data.get("html_url") or ""),
            "assets": [
                {"name": str(asset.get("name") or ""),
                 "size": int(asset.get("size") or 0),
                 "url": str(asset.get("browser_download_url") or "")}
                for asset in (data.get("assets") or [])
                if isinstance(asset, dict) and asset.get("browser_download_url")
            ],
            "source": "api",
        }

    def _from_atom(self, repo):
        """REST API 被限流（403/429）时的退路：releases.atom 没有配额。

        家用宽带出口 IP 共享，匿名 60 次/小时的限额很容易打满，所以要有退路。
        """
        xml = netutil.get_text("https://github.com/%s/releases.atom" % repo, timeout=10.0)
        entry = re.search(r"<entry>(.*?)</entry>", xml, re.S)
        if not entry:
            raise netutil.FetchError("releases.atom 里没有发布条目")
        block = entry.group(1)
        title = re.search(r"<title>(.*?)</title>", block, re.S)
        link = re.search(r'<link[^>]+rel="alternate"[^>]+href="([^"]+)"', block)
        updated = re.search(r"<updated>(.*?)</updated>", block, re.S)
        content = re.search(r"<content[^>]*>(.*?)</content>", block, re.S)
        url = html_unescape(link.group(1)) if link else ""
        tag = ""
        match = re.search(r"/tag/([^/]+)$", url)
        if match:
            tag = match.group(1)
        if not tag and title:
            match = re.search(r"(v?\d+(?:\.\d+)+)", title.group(1))
            tag = match.group(1) if match else ""
        return {
            "tag": tag,
            "name": strip_html(title.group(1)) if title else tag,
            "notes": strip_html(content.group(1)) if content else "",
            "published_at": updated.group(1) if updated else "",
            "url": url,
            "assets": [],
            "source": "atom",
        }

    def _assets_from_html(self, repo, tag):
        """API 拿不到资产列表时，从 releases/expanded_assets 这份 HTML 片段里抠下载链接。"""
        page = netutil.get_text(
            "https://github.com/%s/releases/expanded_assets/%s"
            % (repo, urllib.parse.quote(tag)), timeout=10.0)
        assets = []
        seen = set()
        for href in re.findall(r'href="(/[^"]+/releases/download/[^"]+)"', page):
            href = html_unescape(href)
            if href in seen:
                continue
            seen.add(href)
            assets.append({
                "name": urllib.parse.unquote(href.rsplit("/", 1)[-1]),
                "size": 0,
                "url": "https://github.com" + href,
            })
        return assets

    def check(self, force=False):
        now = time.time()
        with self._lock:
            cached = self._cache["payload"]
            if not force and cached and now - self._cache["at"] < UPDATE_TTL:
                payload = dict(cached)
                payload["cached"] = True
                return payload
            failed = self._fail["payload"]
            if not force and failed and now - self._fail["at"] < UPDATE_FAIL_TTL:
                payload = dict(failed)
                payload["cached"] = True
                return payload
        repo = self.repo()
        release = None
        first_error = ""
        try:
            release = self._from_api(repo)
        except netutil.FetchError as exc:
            first_error = str(exc)
            if "404" in first_error:
                payload = self._blank("no_release")
                payload["message"] = "仓库 %s 还没有发布 Release" % repo
                with self._lock:
                    self._cache.update({"at": now, "payload": dict(payload)})
                self._remember(payload)
                return payload
            RT.log("GitHub API 不可用（%s），改用 releases.atom" % first_error, level="warn")
        if release is None:
            try:
                release = self._from_atom(repo)
            except netutil.FetchError as exc:
                message = first_error or str(exc)
                if "404" in str(exc):
                    # 两个来源都说没有：仓库/发布确实不存在
                    payload = self._blank("no_release")
                    payload["message"] = "仓库 %s 还没有可用的 Release" % repo
                    with self._lock:
                        self._cache.update({"at": now, "payload": dict(payload)})
                    self._remember(payload)
                    return payload
                payload = self._blank("error", message)
                with self._lock:
                    self._fail.update({"at": now, "payload": dict(payload)})
                RT.log("更新检查失败：%s" % message, level="warn")
                return payload
        tag = str(release.get("tag") or "").strip()
        latest = tag[1:] if tag[:1] in ("v", "V") else tag
        assets = list(release.get("assets") or [])
        if not assets and tag:
            try:
                assets = self._assets_from_html(repo, tag)
            except netutil.FetchError as exc:
                RT.log("资产列表取不到：%s" % (exc,), level="warn")
        payload = {
            "ok": True,
            "available": bool(latest) and version_tuple(latest) > version_tuple(RT.version),
            "has_update": bool(latest) and version_tuple(latest) > version_tuple(RT.version),
            "state": "ok",
            "error": "",
            "current": RT.version,
            "latest": latest or "",
            "tag": tag,
            "name": str(release.get("name") or tag),
            "notes": str(release.get("notes") or "")[:6000],
            "published_at": str(release.get("published_at") or ""),
            "url": str(release.get("url") or ""),
            "assets": assets,
            "source": str(release.get("source") or ""),
            "repo": repo,
            "checked_at": int(now),
            "cached": False,
        }
        with self._lock:
            self._cache.update({"at": now, "payload": dict(payload)})
        self._remember(payload)
        return payload

    def _remember(self, payload):
        """把「上次检查时间 / 最新版本」写回 settings，设置页重启后仍有上下文。"""
        try:
            patch = {"update": {"last": int(time.time()), "latest": payload.get("latest") or ""}}
            self.store.update(patch)
        except Exception:
            pass


# --------------------------------------------------------------------------
# 运行期
# --------------------------------------------------------------------------
class Runtime(object):
    def __init__(self, store, app_home, web_dir, version, port, fake_mode):
        self.store = store
        self.app_home = app_home
        self.web_dir = web_dir
        self.version = version
        self.port = port
        self.fake_mode = fake_mode
        self.started_at = int(time.time())
        self.stopping = threading.Event()
        self.engine_box = None
        self.service = None
        self.err_offline = ()
        self.err_error = ()
        self.err_timeout = ()
        self.engine_phase = "idle"
        self.engine_detail = ""
        self._last_status = {"running": False, "pid": 0, "ec": False, "uptime": 0}
        self.control_lock = threading.RLock()
        self.host = ""
        self.http_lock = threading.RLock()
        self.http_servers = []
        self._shutdown_lock = threading.Lock()
        self._shutdown_done = False
        self.threads = []
        self.update_checker = UpdateChecker(store)
        self._notify_state = {}
        self._notify_lock = threading.Lock()
        self._notify_miss = 0
        self._sample_miss = 0

    # -- 日志 ---------------------------------------------------------------
    def log(self, message, level="info"):
        self.store.log(message, level=level)

    # -- HTTP 监听（支持运行中换端口） ------------------------------------
    def start_http(self, host, port):
        """绑定并开始监听，返回 ThreadingHTTPServer。端口被占用时抛 OSError。"""
        server = ThreadingHTTPServer((host, port), Handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever,
                                  kwargs={"poll_interval": 0.4},
                                  name="http-%d" % port, daemon=True)
        thread.start()
        with self.http_lock:
            self.http_servers.append({"server": server, "thread": thread, "port": port})
        self.host = host
        self.port = port
        return server

    def stop_http_servers(self):
        """停掉所有监听（优雅停机用）。"""
        with self.http_lock:
            entries = list(self.http_servers)
            self.http_servers = []
        for entry in entries:
            try:
                entry["server"].shutdown()
            except Exception:  # noqa: BLE001
                pass
            try:
                entry["server"].server_close()
            except Exception:  # noqa: BLE001
                pass

    def switch_port(self, new_port):
        """运行中切换监听端口：先起新监听 → 成功再关旧监听 → 重写 runtime-ports.env。

        任何一步失败都抛 ValueError（中文原因），现有监听不受影响。
        """
        new_port = int_or(new_port)
        if new_port < 1 or new_port > 65535:
            raise ValueError("端口无效，应在 1-65535 之间")
        with self.http_lock:
            if new_port == self.port:
                return False
            try:
                server = ThreadingHTTPServer((self.host, new_port), Handler)
            except OSError as exc:
                raise ValueError("端口 %d 无法监听（可能被占用或没有权限）：%s"
                                 % (new_port, exc))
            server.daemon_threads = True
            thread = threading.Thread(target=server.serve_forever,
                                      kwargs={"poll_interval": 0.4},
                                      name="http-%d" % new_port, daemon=True)
            thread.start()
            previous = self.port
            old = None
            for entry in self.http_servers:
                if entry.get("port") == previous:
                    old = entry
                    break
            self.http_servers.append({"server": server, "thread": thread, "port": new_port})
            self.port = new_port
        # 旧监听延后 0.5 秒关：当前这个请求还挂在旧 server 上，先让它把响应写完
        if old is not None:
            def _retire(entry=old):
                time.sleep(0.5)
                try:
                    entry["server"].shutdown()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    entry["server"].server_close()
                except Exception:  # noqa: BLE001
                    pass
                with self.http_lock:
                    self.http_servers = [e for e in self.http_servers if e is not entry]

            threading.Thread(target=_retire, name="http-retire", daemon=True).start()
        self.store.write_runtime_ports(new_port)
        self.log("面板端口已切换为 %d（原 %d）" % (new_port, previous))
        return True

    def sync_recorded_port(self):
        """启动时把 settings.panel.port 对齐到实际监听端口（升级/改端口后自愈）。"""
        recorded = int_or(self.store.section("panel").get("port"))
        self.store.write_runtime_ports(self.port)
        if recorded == self.port:
            return False
        try:
            self.store.update({"panel": {"port": self.port}})
        except (ValueError, OSError) as exc:
            self.log("同步面板端口失败：%s" % (exc,), level="warn")
        self.log("面板端口已同步为 %d（原 %s）" % (self.port, recorded or "未记录"))
        return True

    # -- 引擎 ---------------------------------------------------------------
    def load_service(self, no_service=False):
        """延迟导入 core.service。导入失败 = 降级模式，面板照常工作。"""
        if no_service:
            self.log("按 EMULE_NO_SERVICE 要求跳过引擎加载（仅静态/接口联调）", level="warn")
            return
        if self.fake_mode:
            repo_root = os.path.abspath(os.path.join(SERVER_DIR, "..", "..", "..", ".."))
            path = os.environ.get("EMULE_FAKE_PATH") or os.path.join(repo_root, "tmp",
                                                                     "fake_service.py")
            if not os.path.isfile(path):
                self.log("找不到假引擎 %s，面板以降级模式运行" % path, level="error")
                return
            import importlib.util
            spec = importlib.util.spec_from_file_location("fn_emule_fake_service", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            self.service = module.EmuleService(self.store.settings)
            self.err_offline = (module.EmuleOffline,)
            self.err_error = (module.EmuleError,)
            self.engine_box = EngineBox()
            self.engine_phase = "ready"
            self.log("已启用假引擎（fn-emule/tmp/fake_service.py），仅供面板联调")
            return
        try:
            from core.service import EmuleError, EmuleOffline, EmuleService
        except Exception as exc:  # noqa: BLE001 - 缺文件/语法错都走降级
            self.log("core.service 不可用，面板以降级模式运行：%s" % (exc,), level="error")
            return
        try:  # 可选：core 提供的超时专用异常（EmuleOffline 的子类），有就按类型判 504
            from core.service import EmuleTimeout
        except Exception:  # noqa: BLE001 - 老版本 core 没有这个类
            EmuleTimeout = None
        try:
            self.err_offline = (EmuleOffline,)
            self.err_error = (EmuleError,)
            self.err_timeout = (EmuleTimeout,) if EmuleTimeout else ()
            self.service = EmuleService(self.store.settings, var_dir=self.store.var_dir)
            self.engine_box = EngineBox()
            self.engine_phase = "ready"
            self.log("已加载引擎门面 core.service.EmuleService")
        except Exception as exc:  # noqa: BLE001
            self.service = None
            self.engine_box = None
            self.log("引擎门面初始化失败，面板以降级模式运行：%r" % (exc,), level="error")

    def call(self, method, *args, **kwargs):
        """调一个引擎方法，把各类异常翻译成面板异常。

        kwargs 里的 timeout 是面板侧的等待预算（秒），不传给引擎方法。
        """
        if self.service is None or self.engine_box is None:
            raise ServiceMissing("引擎组件不可用（core.service 未加载）")
        timeout = float(kwargs.pop("timeout", DATA_TIMEOUT))
        fn = getattr(self.service, method, None)
        if fn is None:
            raise ServiceMissing("引擎接口缺失：%s" % method)
        try:
            return self.engine_box.call(fn, args, kwargs, timeout=timeout)
        except EngineTimeout:
            raise
        except self.err_timeout as exc:  # EmuleTimeout：引擎在跑，只是没按时回包
            raise EngineTimeout(str(exc) or "引擎响应超时")
        except self.err_offline as exc:
            message = str(exc) or "引擎未运行"
            if is_timeout_message(message):
                raise EngineTimeout(message)
            raise OfflineError(message)
        except self.err_error as exc:
            raise EngineFailure(str(exc) or "引擎操作失败")

    def status(self):
        """引擎进程状态。永远不抛异常 —— /api/health 必须能答话。

        引擎正卡在一次慢调用里时（EC 请求排队），这里不会等满 15 秒：拿最近
        一次已知状态兜底并标 stale，健康探针必须秒回。
        """
        if self.service is None or self.engine_box is None:
            return {"running": False, "pid": 0, "ec": False, "uptime": 0,
                    "phase": self.engine_phase, "detail": self.engine_detail}
        try:
            data = self.call("process_status", timeout=HEALTH_TIMEOUT)
        except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing) as exc:
            fallback = dict(self._last_status)
            fallback["phase"] = self.engine_phase
            fallback["detail"] = str(exc)
            fallback["stale"] = True
            return fallback
        data = as_dict(data)
        out = {
            "running": bool(data.get("running")),
            "pid": int_or(data.get("pid")),
            "ec": bool(data.get("ec")),
            "uptime": int_or(data.get("uptime")),
            "version": str(data.get("version") or ""),
            "bootstrap_notes": list(data.get("bootstrap_notes") or []),
            "phase": self.engine_phase,
            "detail": self.engine_detail or str(data.get("error") or ""),
        }
        if out["running"]:
            self._last_status = dict(out)
        return out

    def boot_engine(self):
        """后台线程：prepare + start。失败只记日志，绝不让面板进程退出。"""
        if self.service is None:
            self.engine_phase = "missing"
            self.engine_detail = "引擎组件不可用"
            return
        try:
            self.engine_phase = "preparing"
            self.log("引擎准备中：prepare()")
            self.call("prepare", timeout=180.0)
            self.engine_phase = "starting"
            self.log("引擎启动中：start()")
            self.call("start", timeout=120.0)
            self.engine_phase = "running"
            self.engine_detail = ""
            self.log("引擎已启动")
        except Exception as exc:  # noqa: BLE001 - 引擎挂了面板不能挂
            self.engine_phase = "failed"
            self.engine_detail = str(exc) or exc.__class__.__name__
            self.log("引擎启动失败（面板继续运行，可在界面一键重启）：%s" % self.engine_detail,
                     level="error")

    # -- 采样线程 -----------------------------------------------------------
    def start_workers(self):
        for target, name in (
            (self.sample_loop, "sample"),
            (self.notify_loop, "notify"),
            (self.backup_loop, "backup"),
        ):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)

    def sample_loop(self):
        """每 3 秒采一次 overview 的 down/up，塞进内存环形缓冲。"""
        while not self.stopping.wait(SAMPLE_INTERVAL):
            if self.service is None:
                continue
            try:
                data = self.call("overview", timeout=8.0)
                speed = as_dict(as_dict(data).get("speed"))
                self.store.push_history(int(speed.get("down") or 0), int(speed.get("up") or 0))
                self._sample_miss = 0
            except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing) as exc:
                self._sample_miss += 1
                if self._sample_miss in (1, 20, 200):
                    self.log("速度采样失败（引擎不可用）：%s" % (exc,), level="warn")
            except Exception as exc:  # noqa: BLE001
                self._sample_miss += 1
                self.log("速度采样异常：%r" % (exc,), level="error")

    def notify_loop(self):
        """每 5 秒采一次下载队列，捕捉「刚完成」「刚出错」两个状态跳变。"""
        while not self.stopping.wait(NOTIFY_INTERVAL):
            try:
                self.notify_tick()
            except Exception as exc:  # noqa: BLE001 - 通知线程绝不能因为一次异常退出
                self.log("通知轮询异常：%r" % (exc,), level="error")

    def notify_tick(self):
        if self.service is None:
            return
        cfg = self.store.section("notify")
        if not cfg.get("enabled"):
            return
        try:
            data = self.call("transfers", "download", timeout=10.0)
        except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing):
            self._notify_miss += 1
            if self._notify_miss in (1, 60):
                self.log("通知轮询暂时读不到下载队列（引擎不可用）", level="warn")
            return
        self._notify_miss = 0
        items = as_dict(data).get("items") or []
        pending = []
        with self._notify_lock:
            for item in items:
                if not isinstance(item, dict):
                    continue
                file_hash = str(item.get("hash") or "").upper()
                if not file_hash:
                    continue
                status = str(item.get("status") or "")
                previous = self._notify_state.get(file_hash)
                self._notify_state[file_hash] = status
                if previous is None or previous == status:
                    continue
                if status == "complete" and previous != "complete":
                    pending.append(("complete", item))
                elif status == "error" and previous != "error":
                    pending.append(("error", item))
            # 只记最近 4000 个任务状态，长时间运行不涨内存
            if len(self._notify_state) > 4000:
                self._notify_state.clear()
        # 发通知放在锁外：一次 HTTP 推送可能几秒，不能挡住状态记录
        for event, item in pending:
            try:
                self.dispatch_event(event, item)
            except Exception as exc:  # noqa: BLE001
                self.log("发送 %s 通知失败：%r" % (event, exc), level="error")

    def backup_loop(self):
        while not self.stopping.wait(BACKUP_CHECK_INTERVAL):
            cfg = self.store.section("backup")
            if not cfg.get("auto"):
                continue
            last = int_or(cfg.get("last"))
            if last and time.time() - last < 86400:
                continue
            try:
                result = self.store.backup_create(tag="auto", keep=cfg.get("keep") or 7)
                self.log("自动备份完成：%s" % result.get("name"))
            except Exception as exc:  # noqa: BLE001
                self.log("自动备份失败：%r" % (exc,), level="error")

    # -- 通知 ---------------------------------------------------------------
    def dispatch_event(self, event, item):
        cfg = self.store.section("notify")
        if not cfg.get("enabled"):
            return []
        events = cfg.get("events") or {}
        if not events.get(event, False):
            return []
        name = str(item.get("name") or "未命名任务")
        size = int_or(item.get("size"))
        if event == "complete":
            title = "eMule 下载完成 / Download complete"
            body = "%s\n%s\n%s" % (name, human_size(size), time.strftime("%Y-%m-%d %H:%M:%S"))
        else:
            title = "eMule 任务出错 / Download error"
            body = "%s\n任务状态变为 error，请在面板查看详情。\nTask failed, check the panel for details." % name
        return self.send_channels(title, body, event=event)

    def send_channels(self, title, body, event="manual", channel_id=""):
        cfg = self.store.section("notify")
        channels = [c for c in (cfg.get("channels") or []) if isinstance(c, dict)]
        if channel_id:
            channels = [c for c in channels if c.get("id") == channel_id]
        else:
            channels = [c for c in channels if c.get("enabled", True)]
        results = []
        for channel in channels:
            result = notify.send(channel, title, body)
            record = {
                "id": uuid_hex(),
                "at": int(time.time()),
                "event": event,
                "channel": channel.get("name") or channel.get("type") or "",
                "channel_id": channel.get("id") or "",
                "type": channel.get("type") or "",
                "ok": bool(result.get("ok")),
                "detail": str(result.get("detail") or "")[:300],
                "title": str(title)[:200],
                "body": str(body)[:600],
            }
            self.store.add_notify_record(record)
            results.append({"channel": record["channel"], "type": record["type"],
                            "ok": bool(result.get("ok")),
                            "detail": str(result.get("detail") or "")[:300]})
            if not result.get("ok"):
                self.log("通知发送失败（%s）：%s" % (record["channel"], record["detail"]),
                         level="warn")
        return results

    # -- 停机 ---------------------------------------------------------------
    def shutdown(self):
        """幂等停机：信号处理器和 main 的 finally 都会调一次。"""
        self.stopping.set()
        with self._shutdown_lock:
            if self._shutdown_done:
                return
            self._shutdown_done = True
        if self.engine_box is not None and self.service is not None:
            try:
                self.log("面板正在停止引擎")
                self.call("stop", timeout=20.0)
            except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing) as exc:
                self.log("停止引擎时出错：%s" % (exc,), level="warn")
            except Exception as exc:  # noqa: BLE001
                self.log("停止引擎时异常：%r" % (exc,), level="error")
            try:
                self.service.shutdown()
            except Exception:
                pass
        if self.engine_box is not None:
            self.engine_box.close()


def uuid_hex():
    return uuid.uuid4().hex[:12]


def human_size(num):
    try:
        value = float(num)
    except (TypeError, ValueError):
        return "-"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return ("%.1f %s" % (value, unit)) if unit != "B" else ("%d B" % int(value))
        value /= 1024.0
    return "-"


# --------------------------------------------------------------------------
# 载荷整形：把 core 的返回补成 CONTRACT §3 的形状
# --------------------------------------------------------------------------
def as_dict(value):
    return value if isinstance(value, dict) else {}


def as_list(value):
    return value if isinstance(value, list) else []


def int_or(value, fallback=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return fallback


def normalize_overview(data):
    data = as_dict(data)
    engine = as_dict(data.get("engine"))
    ed2k = as_dict(data.get("ed2k"))
    server = as_dict(ed2k.get("server"))
    kad = as_dict(data.get("kad"))
    speed = as_dict(data.get("speed"))
    session = as_dict(data.get("session"))
    counters = as_dict(data.get("counters"))
    disk = as_dict(data.get("disk"))
    return {
        "engine": {
            "running": bool(engine.get("running")),
            "ec": bool(engine.get("ec")),
            "version": str(engine.get("version") or ""),
            "pid": int_or(engine.get("pid")),
            "uptime": int_or(engine.get("uptime")),
        },
        "ed2k": {
            "connected": bool(ed2k.get("connected")),
            "low_id": bool(ed2k.get("low_id")),
            "server": {
                "name": str(server.get("name") or ""),
                "ip": str(server.get("ip") or ""),
                "port": int_or(server.get("port")),
            },
        },
        "kad": {
            "connected": bool(kad.get("connected")),
            "firewalled": bool(kad.get("firewalled")),
            "nodes": int_or(kad.get("nodes")),
            "users": int_or(kad.get("users")),
            "files": int_or(kad.get("files")),
        },
        "speed": {
            "down": int_or(speed.get("down")),
            "up": int_or(speed.get("up")),
            "down_limit": int_or(speed.get("down_limit")),
            "up_limit": int_or(speed.get("up_limit")),
            "max_down": int_or(speed.get("max_down")),
        },
        "session": {
            "down": int_or(session.get("down")),
            "up": int_or(session.get("up")),
            "down_total": int_or(session.get("down_total")),
            "up_total": int_or(session.get("up_total")),
        },
        "counters": {
            "downloads": int_or(counters.get("downloads")),
            "downloads_active": int_or(counters.get("downloads_active")),
            "downloads_paused": int_or(counters.get("downloads_paused")),
            "downloads_waiting": int_or(counters.get("downloads_waiting")),
            "uploads": int_or(counters.get("uploads")),
            "queue": int_or(counters.get("queue")),
            "sources": int_or(counters.get("sources")),
            "connections": int_or(counters.get("connections")),
            "complete": int_or(counters.get("downloads_complete")),
            "shared": int_or(counters.get("shared")),
            "ed2k_users": int_or(counters.get("ed2k_users")),
            "ed2k_files": int_or(counters.get("ed2k_files")),
            "banned": int_or(counters.get("banned")),
        },
        "disk": {
            "free": int_or(disk.get("free")),
            "total": int_or(disk.get("total")),
            "path": str(disk.get("path") or ""),
        },
    }


def normalize_transfer(item):
    item = as_dict(item)
    sources = as_dict(item.get("sources"))
    # 白名单式整形：core 的 _ecid 等下划线内部字段绝不写进 JSON
    out = {
        "hash": str(item.get("hash") or "").upper(),
        "name": str(item.get("name") or ""),
        "size": int_or(item.get("size")),
        "done": int_or(item.get("done")),
        "percent": round(float(item.get("percent") or 0.0), 5),
        "speed": int_or(item.get("speed")),
        "eta": int_or(item.get("eta")),
        "status": str(item.get("status") or "waiting"),
        "priority": str(item.get("priority") or "normal"),
        "category": str(item.get("category") or ""),
        "partfile": bool(item.get("partfile")),
        "added": int_or(item.get("added")),
        "sources": {
            "total": int_or(sources.get("total")),
            "transferring": int_or(sources.get("transferring")),
            "asked": int_or(sources.get("asked")),
            "found": int_or(sources.get("found")),
            "a4af": int_or(sources.get("a4af")),
        },
        "progress": {
            "completed": int_or(as_dict(item.get("progress")).get("completed"), int_or(item.get("done")))
        },
        "shared": bool(item.get("shared")),
        "uploading": bool(item.get("uploading")),
    }
    for extra in ("available_parts", "ed2k_link"):
        if extra in item:
            out[extra] = item.get(extra)
    return out


def normalize_transfers(data, kind):
    data = as_dict(data)
    items = data.get("items")
    if not isinstance(items, list):
        items = data if isinstance(data, list) else []
    items = [normalize_transfer(item) for item in items]
    summary = as_dict(data.get("summary"))
    if not summary:
        summary = {
            "count": len(items),
            "active": sum(1 for i in items if i["status"] in ("downloading", "waiting")),
            "paused": sum(1 for i in items if i["status"] == "paused"),
            "waiting": sum(1 for i in items if i["status"] == "waiting"),
            "complete": sum(1 for i in items if i["status"] == "complete"),
            "down": sum(i["speed"] for i in items if i["status"] == "downloading"),
            "up": sum(i["speed"] for i in items if i["uploading"]),
        }
    else:
        summary = {
            "count": int_or(summary.get("count"), len(items)),
            "active": int_or(summary.get("active")),
            "paused": int_or(summary.get("paused")),
            "waiting": int_or(summary.get("waiting")),
            "complete": int_or(summary.get("complete")),
            "down": int_or(summary.get("down")),
            "up": int_or(summary.get("up")),
        }
    return {"items": items, "summary": summary, "total": int_or(data.get("total"), len(items)),
            "type": kind}


def normalize_server(item):
    item = as_dict(item)
    return {
        "ip": str(item.get("ip") or ""),
        "port": int_or(item.get("port")),
        "name": str(item.get("name") or ""),
        "desc": str(item.get("desc") or ""),
        "users": int_or(item.get("users")),
        "maxusers": int_or(item.get("maxusers")),
        "files": int_or(item.get("files")),
        "priority": str(item.get("priority") or "normal"),
        "ping": int_or(item.get("ping")),
        "failed": bool(item.get("failed")),
        "failed_count": int_or(item.get("failed_count")),
        "static": bool(item.get("static")),
        "version": str(item.get("version") or ""),
    }


def notify_record_public(record):
    """通知记录同时给新旧两套字段：t/text（前端展示）和 at/body（面板内部）。"""
    record = as_dict(record)
    at = int_or(record.get("at") or record.get("t"))
    body = str(record.get("body") or record.get("text") or "")
    return {
        "id": str(record.get("id") or ""),
        "t": at,
        "at": at,
        "event": str(record.get("event") or "manual"),
        "channel": str(record.get("channel") or ""),
        "channel_id": str(record.get("channel_id") or ""),
        "type": str(record.get("type") or ""),
        "ok": bool(record.get("ok")),
        "detail": str(record.get("detail") or ""),
        "title": str(record.get("title") or ""),
        "text": body,
        "body": body,
    }


def mask_settings(settings):
    """GET /api/settings：引擎密码与通知渠道密钥都不回传明文。"""
    out = as_dict(settings)
    engine = out.get("engine")
    if isinstance(engine, dict):
        engine["ec_password"] = storemod.SECRET_MARK if engine.get("ec_password") else ""
    out_notify = out.get("notify")
    if isinstance(out_notify, dict):
        channels = out_notify.get("channels")
        if isinstance(channels, list):
            out_notify["channels"] = [notify.channel_public(c) for c in channels
                                      if isinstance(c, dict)]
    return out


def normalize_notify_settings(cfg):
    cfg = as_dict(cfg)
    events = as_dict(cfg.get("events"))
    return {
        "enabled": bool(cfg.get("enabled")),
        "events": {
            "complete": bool(events.get("complete", True)),
            "error": bool(events.get("error", True)),
        },
        "channels": [notify.channel_public(c) for c in as_list(cfg.get("channels"))
                     if isinstance(c, dict)],
    }


def with_ok(result):
    """把 core 返回的 dict 归一成带 ok 的载荷；非 dict 就包一层。"""
    if isinstance(result, dict):
        payload = {"ok": bool(result.get("ok", True))}
        payload.update(result)
        return payload
    if isinstance(result, list):
        return {"ok": True, "items": result, "total": len(result)}
    return {"ok": True, "result": result}


# --------------------------------------------------------------------------
# 设置校验
# --------------------------------------------------------------------------
ENGINE_PORT_FIELDS = ("ec_port", "tcp_port", "udp_port")
INT_FIELDS = ("max_download", "max_upload", "max_connections", "max_sources")


def validate_settings_patch(patch):
    """只挡明显错误的值，返回中文原因；返回空串表示通过。"""
    if not isinstance(patch, dict):
        return "设置内容格式不对"
    panel_cfg = patch.get("panel")
    if isinstance(panel_cfg, dict):
        if "port" in panel_cfg:
            port = int_or(panel_cfg.get("port"), 0)
            if port < 1 or port > 65535:
                return "面板端口无效，应在 1-65535 之间"
        if "theme" in panel_cfg and panel_cfg["theme"] not in ("auto", "light", "dark"):
            return "主题只能是 auto/light/dark"
        if "lang" in panel_cfg and panel_cfg["lang"] not in ("zh", "en"):
            return "语言只能是 zh 或 en"
    engine = patch.get("engine")
    if isinstance(engine, dict):
        for field in ENGINE_PORT_FIELDS:
            if field in engine:
                port = int_or(engine.get(field), 0)
                if port < 1 or port > 65535:
                    return "引擎端口 %s 无效，应在 1-65535 之间" % field
        for field in INT_FIELDS:
            if field in engine:
                value = int_or(engine.get(field), -1)
                if value < 0:
                    return "引擎设置 %s 不能为负数" % field
        for field in ("incoming_dir", "temp_dir"):
            if field in engine:
                text = str(engine.get(field) or "").strip()
                if not text:
                    return "目录 %s 不能为空" % field
        if "shared_dirs" in engine and not isinstance(engine["shared_dirs"], list):
            return "共享目录必须是列表"
        if "nick" in engine and len(str(engine.get("nick") or "")) > 64:
            return "昵称过长（最多 64 个字符）"
    backup_cfg = patch.get("backup")
    if isinstance(backup_cfg, dict) and "keep" in backup_cfg:
        keep = int_or(backup_cfg.get("keep"), 0)
        if keep < storemod.BACKUP_KEEP_MIN or keep > storemod.BACKUP_KEEP_MAX:
            return "备份保留份数应在 %d-%d 之间" % (storemod.BACKUP_KEEP_MIN,
                                                   storemod.BACKUP_KEEP_MAX)
    update_cfg = patch.get("update")
    if isinstance(update_cfg, dict) and "repo" in update_cfg:
        repo = str(update_cfg.get("repo") or "").strip()
        if repo and not re.match(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", repo):
            return "GitHub 仓库格式应为 owner/repo"
    notify_cfg = patch.get("notify")
    if isinstance(notify_cfg, dict) and "channels" in notify_cfg:
        if not isinstance(notify_cfg["channels"], list):
            return "通知通道必须是列表"
    return ""


# --------------------------------------------------------------------------
# 网络诊断（CONTRACT §3.1）
#
# 一次请求把「引擎侧事实」和「本机侧探测」拼成一张诊断卡：
#   * 引擎侧只问 core.service（overview / prefs），不自己算；
#   * 本机侧只跑只读命令（ss / ip / iptables -S / nft list ruleset），每项都有
#     超时，失败只降级成 checks 里的 warn/error，绝不 5xx；
#   * 公网 IP 探测走 netutil，失败快速放弃（不是致命项）。
# --------------------------------------------------------------------------
DIAG_BUDGET = 12.0          # 整个接口的预算（CONTRACT §3.1）
DIAG_PROBE_TIMEOUT = 2.0    # 单条本机命令的预算（留出余量给总预算）
DIAG_ENGINE_TIMEOUT = 6.0   # 单次引擎调用的预算
DIAG_STATUS_TIMEOUT = 3.0   # 探活（process_status，1 个 EC 请求）的单独预算
PUBLIC_IP_URLS = ("https://api.ipify.org", "https://ifconfig.me/ip")
CGNAT_NET = ipaddress.ip_network("100.64.0.0/10")

CHECK_ORDER = ("engine", "ed2k_connect", "high_id", "kad", "tcp_listen", "udp_bind",
               "firewall", "public_ip", "cgnat", "inbound")


def _diag_check(check_id, level, title, detail="", action=""):
    return {"id": check_id, "level": level, "title": title,
            "detail": str(detail or "")[:400], "action": str(action or "")[:300]}


def _run_readonly(argv, timeout):
    """只跑只读诊断命令，返回 (ok, stdout, 中文错误)。"""
    if not sys.platform.startswith("linux"):
        return False, "", "当前系统不是 Linux，无法执行 %s" % argv[0]
    try:
        proc = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              timeout=max(0.5, float(timeout)), check=False)
    except subprocess.TimeoutExpired:
        return False, "", "命令超时：%s" % " ".join(argv[:2])
    except FileNotFoundError:
        return False, "", "系统缺少命令：%s" % argv[0]
    except (OSError, ValueError) as exc:
        return False, "", "命令执行失败：%s" % exc
    out = (proc.stdout or b"").decode("utf-8", "replace")
    err = (proc.stderr or b"").decode("utf-8", "replace")
    if proc.returncode != 0 and not out.strip():
        reason = err.strip().splitlines()[-1] if err.strip() else "命令返回 %d" % proc.returncode
        return False, "", str(reason)[:160]
    return True, out, ""


def _diag_remaining(deadline):
    return max(0.0, deadline - time.monotonic())


def _diag_probe_timeout(deadline):
    return max(0.3, min(DIAG_PROBE_TIMEOUT, _diag_remaining(deadline)))


def _diag_ss_count(argv, deadline):
    """跑一条 ss 命令，返回 (ok, 行数, 错误)。"""
    ok, out, err = _run_readonly(argv, _diag_probe_timeout(deadline))
    if not ok:
        return False, 0, err
    lines = [line for line in out.splitlines() if line.strip()]
    return True, len(lines), ""


def _parse_ip_route(text):
    """从 ip -4 route get 1.1.1.1 的输出里取 src / via / dev。"""
    info = {"lan_ip": "", "gateway": "", "iface": ""}
    match = re.search(r"\bsrc\s+(\S+)", text or "")
    if match:
        info["lan_ip"] = match.group(1)
    match = re.search(r"\bvia\s+(\S+)", text or "")
    if match:
        info["gateway"] = match.group(1)
    match = re.search(r"\bdev\s+(\S+)", text or "")
    if match:
        info["iface"] = match.group(1)
    return info


def _lan_ip_via_socket():
    """没有 ip 命令时的兜底：UDP connect 不会真的发包，只拿出口网卡地址。"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(1.0)
        sock.connect(("1.1.1.1", 80))
        return sock.getsockname()[0]
    except OSError:
        return ""
    finally:
        try:
            sock.close()
        except OSError:
            pass


def _iptables_blocks(text, ports):
    """在 iptables -S 的输出里找针对端口的 DROP / REJECT。"""
    for line in (text or "").splitlines():
        rule = line.strip()
        if not rule or rule.startswith("#"):
            continue
        if not re.search(r"-j\s+(DROP|REJECT|drop|reject)\b", rule):
            continue
        for port in ports:
            if re.search(r"--dport\s+%d\b" % port, rule):
                return True, rule
    return False, ""


def _nft_blocks(text, ports):
    """在 nft list ruleset 的输出里找 dport 匹配且动作是 drop/reject 的行。"""
    for line in (text or "").splitlines():
        rule = line.strip()
        if not rule:
            continue
        if not re.search(r"dport", rule):
            continue
        if not any(re.search(r"\b%d\b" % port, rule) for port in ports):
            continue
        if re.search(r"\b(drop|reject)\b", rule):
            return True, rule
    return False, ""


def _diag_firewall(tcp_port, udp_port, deadline):
    """返回 (state, detail)。state ∈ open / blocked / unknown，绝不修改系统。"""
    ports = [port for port in (tcp_port, udp_port) if port]
    port_text = "/".join(str(port) for port in ports) or "相关端口"
    last_error = ""
    for argv in (["iptables", "-S"], ["sudo", "-n", "iptables", "-S"]):
        ok, out, err = _run_readonly(argv, _diag_probe_timeout(deadline))
        if not ok:
            last_error = last_error or err
            continue
        blocked, rule = _iptables_blocks(out, ports)
        if blocked:
            return "blocked", "iptables 规则拦截了端口：%s" % rule[:200]
        return "open", "iptables 未发现针对 %s 的 DROP/REJECT 规则" % port_text
    ok, out, err = _run_readonly(["nft", "list", "ruleset"], _diag_probe_timeout(deadline))
    if not ok:
        ok, out, err = _run_readonly(["sudo", "-n", "nft", "list", "ruleset"],
                                     _diag_probe_timeout(deadline))
    if ok:
        blocked, rule = _nft_blocks(out, ports)
        if blocked:
            return "blocked", "nftables 规则拦截了端口：%s" % rule[:200]
        if re.search(r"dport", out) and re.search(r"\b(drop|reject)\b", out):
            return "unknown", ("nftables 里有 drop/reject 规则，但无法逐行确认是否命中 %s，"
                              "建议在 fnOS 防火墙页面确认" % port_text)
        return "open", "nftables 未发现针对 %s 的 DROP/REJECT 规则" % port_text
    last_error = last_error or err
    try:
        if os.path.exists("/proc/net/ip_tables_names"):
            return "unknown", "存在 iptables 表但当前权限读不到规则（%s）" % last_error
    except OSError:
        pass
    return "unknown", "无法判断防火墙状态（%s）" % (last_error or "未找到 iptables / nft 命令")


def _diag_public_ip(deadline):
    """双栈探测公网 IP：返回 (ipv4, ipv6, error4, error6)。

    两种网络环境都要能工作：
    - 直连网络：按 family 钉死请求（getaddrinfo 只解析 A / AAAA）；
    - 代理网络（DNS 被劫持成 fake-ip）：钉死 family 会让证书校验失败，
      此时回退到默认请求（urllib 走系统偏好栈），从返回文本里挑对应版本地址；
      v6 用 ipify 的 /v6 端点等"只返回 IPv6"的服务来拿。
    - 一边失败不阻塞另一边；全失败才置 error。
    """
    ipv4, ipv6 = "", ""
    errors = []
    hosts = [u.split("//")[-1].split("/")[0] for u in PUBLIC_IP_URLS]

    def pick(text, family):
        for piece in (text or "").strip().replace(" ", ",").split(","):
            piece = piece.strip()
            try:
                addr = ipaddress.ip_address(piece)
            except ValueError:
                continue
            if addr.version == family:
                return str(addr)
        return ""

    def try_fetch(url, family):
        budget = min(2.5, max(0.8, _diag_remaining(deadline) / 2.0))
        if budget < 0.8:
            return None, "剩余诊断预算不足"
        try:
            return netutil.get_text(url, timeout=budget, retries=0, family=family), ""
        except netutil.FetchError as exc:
            return None, str(exc)
        except Exception as exc:  # noqa: BLE001
            return None, str(exc)

    # 第一轮：family 钉死（直连网络）
    for url in PUBLIC_IP_URLS:
        if _diag_remaining(deadline) < 0.8:
            break
        host = url.split("//")[-1].split("/")[0]
        for family, bucket in ((4, "ipv4"), (6, "ipv6")):
            if bucket == "ipv4" and ipv4 or bucket == "ipv6" and ipv6:
                continue
            text, err = try_fetch(url, family)
            got = pick(text, family) if text else ""
            if got:
                if family == 4: ipv4 = got
                else: ipv6 = got
            elif err:
                errors.append("%s (IPv%d)：%s" % (host, family, err))
        if ipv4 and ipv6:
            break

    # 第二轮：回退默认请求 + IPv6 专用端点（代理/fake-ip 网络）
    fallback_urls = [u for u in PUBLIC_IP_URLS]
    if not ipv4:
        for url in fallback_urls:
            text, err = try_fetch(url, 0)
            got = pick(text, 4) if text else ""
            if got:
                ipv4 = got
                break
            if err:
                errors.append("%s (fallback IPv4)：%s" % (url.split("//")[-1].split("/")[0], err))
    if not ipv6:
        v6_urls = ["https://api6.ipify.org", "https://ipv6.icanhazip.com",
                   "https://v6.ident.me"]
        for url in v6_urls:
            text, err = try_fetch(url, 0)
            got = pick(text, 6) if text else ""
            if got:
                ipv6 = got
                break
    # v4 与 v6 的错误分开记：v4 的原因挂在 IPv4 行，v6 的原因挂在 IPv6 行，
    # 不再共用一个字段（用户反馈：IPv4 行不该出现 IPv6 的说明）。
    error4 = ""
    error6 = ""
    v4_errors = [e for e in errors if "(IPv4)" in e]
    if not ipv4:
        error4 = "；".join(v4_errors[-2:]) or "公网 IPv4 探测失败"
    if not ipv6:
        error6 = "未获取到 IPv6 公网地址（设备或网络可能没有 IPv6 出口）"
    return ipv4, ipv6, error4, error6


def _is_private_ip(text):
    try:
        return ipaddress.ip_address(str(text or "")).is_private
    except ValueError:
        return False


def _is_cgnat(text):
    try:
        return ipaddress.ip_address(str(text or "")) in CGNAT_NET
    except ValueError:
        return False


def _diag_engine_probe(runtime):
    """用 1 个 EC 请求探活（最坏 3s）。返回 (status_dict, mode, detail)。

    mode: ok / offline / ec_down / ec_timeout。
    「引擎进程在、EC 不回包」时绝不再排 overview（内部 3 个 EC 请求、最长约 30s），
    否则那些线程会继续占着 core 的 EC 锁，把同时进来的 /api/overview 一起堵住。
    """
    try:
        status = as_dict(runtime.call("process_status", timeout=DIAG_STATUS_TIMEOUT))
    except EngineTimeout:
        return {}, "ec_timeout", "%.0f 秒内没有读到引擎状态，EC 控制通道可能卡死" % DIAG_STATUS_TIMEOUT
    except OfflineError as exc:
        return {}, "offline", str(exc) or "引擎未运行"
    except (EngineFailure, ServiceMissing) as exc:
        return {}, "offline", str(exc) or "引擎不可用"
    if not bool(status.get("running")):
        return status, "offline", str(status.get("detail") or status.get("error") or "引擎未运行")
    if not bool(status.get("ec")):
        return status, "ec_down", str(status.get("error") or "EC 控制通道不可用")
    return status, "ok", ""


def _diag_local_facts(deadline, tcp_port, udp_port):
    """只读的本机事实：网卡/路由/端口监听/防火墙/公网 IP。不发任何 EC 请求。"""
    host_info = {"lan_ip": "", "gateway": "", "iface": "",
                 "public_ip": "", "public_ip_error": "", "public_ip6": "", "public_ip6_error": "",
                 "private_ip": False, "cgnat_suspect": False}
    route_ok, route_out, _err = _run_readonly(["ip", "-4", "route", "get", "1.1.1.1"],
                                              _diag_probe_timeout(deadline))
    if route_ok:
        host_info.update(_parse_ip_route(route_out))
    if not host_info["lan_ip"]:
        host_info["lan_ip"] = _lan_ip_via_socket()
    host_info["private_ip"] = _is_private_ip(host_info["lan_ip"])

    inbound_argv = ["ss", "-Htn", "state", "established"]
    if tcp_port:
        inbound_argv.append("( sport = :%d )" % tcp_port)
    inbound_ok, inbound_count, inbound_err = _diag_ss_count(inbound_argv, deadline)
    tcp_ok, tcp_lines, tcp_err = _diag_ss_count(
        ["ss", "-Htln", "sport = :%d" % tcp_port] if tcp_port else ["ss", "-Htln"], deadline)
    udp_ok, udp_lines, udp_err = _diag_ss_count(
        ["ss", "-Huln", "sport = :%d" % udp_port] if udp_port else ["ss", "-Huln"], deadline)
    firewall, firewall_detail = _diag_firewall(tcp_port, udp_port, deadline)
    public_ip, public_ip6, public_ip_error, public_ip6_error = _diag_public_ip(deadline)
    host_info["public_ip"] = public_ip
    host_info["public_ip6"] = public_ip6
    host_info["public_ip_error"] = public_ip_error
    host_info["public_ip6_error"] = public_ip6_error
    host_info["cgnat_suspect"] = _is_cgnat(public_ip)
    facts = {
        "host": host_info,
        "inbound_ok": inbound_ok,
        "inbound_connections": int(inbound_count if inbound_ok else 0),
        "inbound_error": inbound_err,
        "tcp_ok": tcp_ok,
        "tcp_listening": bool(tcp_ok and tcp_lines > 0),
        "tcp_error": tcp_err,
        "udp_ok": udp_ok,
        "udp_bound": bool(udp_ok and udp_lines > 0),
        "udp_error": udp_err,
        "firewall": firewall,
        "firewall_detail": firewall_detail,
    }
    return facts


def _diag_degraded_card(runtime, mode, detail, status, deadline):
    """引擎不可用 / EC 不通时的诊断卡。

    只做本机侧探测（网卡、端口监听、防火墙、公网 IP），一律不调 overview / prefs，
    避免把一坨 EC 请求排在 core 的锁后面。契约字段与正常路径完全一致。
    """
    engine_cfg = runtime.store.section("engine")
    tcp_port = int_or(engine_cfg.get("tcp_port"))
    udp_port = int_or(engine_cfg.get("udp_port"))
    facts = _diag_local_facts(deadline, tcp_port, udp_port)
    host_info = facts["host"]
    running = mode != "offline"
    version = str(status.get("version") or "")
    host_text = host_info["lan_ip"] or "本机"

    engine_payload = {
        "running": running,
        "ec": False,
        "ed2k_connected": False,
        "low_id": False,
        "server": {"name": "", "ip": "", "port": 0},
        "kad": {"connected": False, "firewalled": False, "nodes": 0},
        "inbound_connections": facts["inbound_connections"],
        "tcp_port": tcp_port,
        "udp_port": udp_port,
    }

    checks = []
    if mode == "offline":
        checks.append(_diag_check("engine", "error", "引擎未运行", detail,
                                  "在面板「引擎」页启动引擎，再重新诊断"))
        checks.append(_diag_check("ed2k_connect", "error", "eD2k 未连接",
                                  "引擎没有运行，无法连接 eD2k 服务器。", "先启动引擎"))
        checks.append(_diag_check("high_id", "warn", "暂时无法判断 High ID",
                                  "引擎没有运行，读不到 eD2k 连接状态。", "先启动引擎"))
        checks.append(_diag_check("kad", "error", "Kad 状态未知",
                                  "引擎没有运行，无法读取 Kad 状态。", "先启动引擎"))
    else:
        title = "引擎无响应（EC 不可用）" if mode == "ec_down" else "引擎无响应（EC 超时）"
        checks.append(_diag_check("engine", "warn", title, detail,
                                  "在面板「引擎」页重启引擎，再重新诊断"))
        checks.append(_diag_check("ed2k_connect", "warn", "无法读取 eD2k 状态",
                                  "引擎的 EC 控制通道没有响应，暂时读不到 eD2k 连接状态。",
                                  "重启引擎后重新诊断"))
        checks.append(_diag_check("high_id", "warn", "暂时无法判断 High ID",
                                  "EC 控制通道不可用，读不到 eD2k 的 Low ID 标记。",
                                  "重启引擎后重新诊断"))
        checks.append(_diag_check("kad", "warn", "Kad 状态未知",
                                  "EC 控制通道不可用，暂时读不到 Kad 状态。",
                                  "重启引擎后重新诊断"))

    if not facts["tcp_ok"]:
        checks.append(_diag_check("tcp_listen", "warn", "无法探测 TCP 监听",
                                  facts["tcp_error"] or "ss 命令不可用"))
    elif facts["tcp_listening"]:
        checks.append(_diag_check("tcp_listen", "ok", "TCP %d 正在监听" % tcp_port,
                                  "eD2k 的 TCP 端口已在本机监听，等待服务器反连。"))
    else:
        checks.append(_diag_check("tcp_listen", "error" if running else "warn",
                                  "TCP %d 未监听" % tcp_port,
                                  "本机没有进程在监听 TCP %d，服务器无法反连（会拿到 Low ID）。" % tcp_port,
                                  "确认引擎已启动，且该端口没有被其它程序占用"))

    if not facts["udp_ok"]:
        checks.append(_diag_check("udp_bind", "warn", "无法探测 UDP 绑定",
                                  facts["udp_error"] or "ss 命令不可用"))
    elif facts["udp_bound"]:
        checks.append(_diag_check("udp_bind", "ok", "UDP %d 已绑定" % udp_port,
                                  "Kad 与 eD2k 的 UDP 端口已在本机绑定。"))
    else:
        checks.append(_diag_check("udp_bind", "error" if running else "warn",
                                  "UDP %d 未绑定" % udp_port,
                                  "本机没有进程占用 UDP %d，Kad 可能无法正常通信。" % udp_port,
                                  "确认引擎已启动，且该端口没有被其它程序占用"))

    if facts["firewall"] == "blocked":
        checks.append(_diag_check("firewall", "error", "防火墙可能拦截了端口",
                                  facts["firewall_detail"],
                                  "在 fnOS 防火墙放行 TCP %d 与 UDP %d" % (tcp_port, udp_port)))
    elif facts["firewall"] == "open":
        checks.append(_diag_check("firewall", "ok", "防火墙未拦截端口",
                                  facts["firewall_detail"]))
    else:
        checks.append(_diag_check("firewall", "warn", "防火墙状态未知",
                                  facts["firewall_detail"],
                                  "在 fnOS 防火墙页面确认 TCP %d / UDP %d 已放行"
                                  % (tcp_port, udp_port)))

    if host_info["public_ip"]:
        checks.append(_diag_check("public_ip", "ok", "公网 IP 已获取 (IPv4)",
                                  "当前公网出口 IP：%s" % host_info["public_ip"]))
    else:
        checks.append(_diag_check("public_ip", "warn", "获取公网 IP 失败 (IPv4)",
                                  host_info["public_ip_error"] or "网络不可达或代理未配置",
                                  "检查设备的网络与代理设置"))

    if host_info["cgnat_suspect"]:
        checks.append(_diag_check("cgnat", "warn", "疑似运营商 CGNAT",
                                  "公网 IP %s 属于 100.64.0.0/10（运营商级 NAT），端口映射不会生效。"
                                  % host_info["public_ip"],
                                  "向运营商申请公网 IP，或改用内网穿透/中转"))
    elif host_info["public_ip"]:
        checks.append(_diag_check("cgnat", "ok", "未检测到 CGNAT",
                                  "公网 IP 不在运营商 NAT 段内。"))
    else:
        checks.append(_diag_check("cgnat", "warn", "无法判断是否 CGNAT",
                                  "公网 IP 获取失败，无法判断是否处于运营商 NAT 之后。"))

    if not facts["inbound_ok"]:
        checks.append(_diag_check("inbound", "warn", "无法统计入站连接",
                                  facts["inbound_error"] or "ss 命令不可用"))
    elif facts["inbound_connections"] > 0:
        checks.append(_diag_check("inbound", "ok", "已有外部客户端连入",
                                  "当前有 %d 条外部连到 TCP %d 的连接（High ID 的直接证据）。"
                                  % (facts["inbound_connections"], tcp_port)))
    else:
        checks.append(_diag_check("inbound", "warn", "没有观察到外部连入",
                                  "读不到 eD2k 状态，无法判断当前是 High ID 还是 Low ID。",
                                  "先恢复引擎的 EC 连接，再重新诊断"))

    checks.sort(key=lambda check: CHECK_ORDER.index(check["id"])
                if check["id"] in CHECK_ORDER else len(CHECK_ORDER))

    if mode == "offline":
        grade = "error"
        title = "引擎未运行"
        summary_detail = "aMule 引擎没有运行，先启动引擎再做网络诊断。"
        suggestions = ["在面板「引擎」页启动 aMule 引擎，再重新诊断"]
    else:
        grade = "warn"
        title = "引擎无响应（EC 不可用）" if mode == "ec_down" else "引擎无响应（EC 超时）"
        summary_detail = ("引擎进程在运行，但 EC 控制通道没有响应，暂时读不到 eD2k / Kad 状态；"
                          "到「引擎」页重启引擎后重新诊断。")
        suggestions = ["在面板「引擎」页重启引擎，再重新诊断"]

    return {
        "ok": True,
        "checked_at": int(time.time()),
        "version": runtime.version,
        "summary": {"grade": grade, "high_id": False, "kad_open": False,
                    "title": title, "detail": summary_detail},
        "engine": engine_payload,
        "host": host_info,
        "ports": {"tcp_listening": facts["tcp_listening"], "udp_bound": facts["udp_bound"],
                  "firewall": facts["firewall"], "firewall_detail": facts["firewall_detail"]},
        "checks": checks,
        "suggestions": suggestions,
    }


def build_diagnostics(runtime):
    """按 CONTRACT §3.1 生成诊断数据。永远返回可用的 dict（调用方固定 200）。"""
    deadline = time.monotonic() + DIAG_BUDGET
    checks = []
    suggestions = []

    # 探活只发 1 个 EC 请求（最坏 3s）。引擎半死时直接出降级卡，
    # 绝不再排 overview（3 个 EC 请求）把 core 的 EC 锁占住。
    status, engine_mode, probe_detail = _diag_engine_probe(runtime)
    if engine_mode != "ok":
        return _diag_degraded_card(runtime, engine_mode, probe_detail, status, deadline)

    overview = {}
    overview_error = ""
    engine_budget = max(0.5, min(DIAG_ENGINE_TIMEOUT, _diag_remaining(deadline) - 3.0))
    try:
        overview = as_dict(runtime.call("overview", timeout=engine_budget))
    except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing) as exc:
        overview_error = str(exc) or "引擎不可用"

    ed2k = as_dict(overview.get("ed2k"))
    server = as_dict(ed2k.get("server"))
    kad = as_dict(overview.get("kad"))
    engine_cfg = runtime.store.section("engine")
    tcp_port = int_or(engine_cfg.get("tcp_port"))
    udp_port = int_or(engine_cfg.get("udp_port"))
    if runtime.service is not None:
        try:
            prefs = as_dict(runtime.call("prefs", timeout=max(0.5, min(4.0, _diag_remaining(deadline) - 3.0))))
            tcp_port = int_or(prefs.get("tcp_port"), tcp_port) or tcp_port
            udp_port = int_or(prefs.get("udp_port"), udp_port) or udp_port
        except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing):
            pass  # 读不到偏好就用面板设置里的端口，不是致命项

    running = bool(status.get("running"))
    ec_online = bool(status.get("ec"))
    ed2k_connected = bool(ed2k.get("connected"))
    low_id = bool(ed2k.get("low_id"))
    kad_connected = bool(kad.get("connected"))
    kad_firewalled = bool(kad.get("firewalled"))
    high_id = ed2k_connected and not low_id
    kad_open = kad_connected and not kad_firewalled

    # ---- 本机侧探测 ----
    host_info = {"lan_ip": "", "gateway": "", "iface": "",
                 "public_ip": "", "public_ip_error": "", "public_ip6": "", "public_ip6_error": "",
                 "private_ip": False, "cgnat_suspect": False}
    route_ok, route_out, _route_err = _run_readonly(["ip", "-4", "route", "get", "1.1.1.1"],
                                                    _diag_probe_timeout(deadline))
    if route_ok:
        host_info.update(_parse_ip_route(route_out))
    if not host_info["lan_ip"]:
        host_info["lan_ip"] = _lan_ip_via_socket()
    host_info["private_ip"] = _is_private_ip(host_info["lan_ip"])

    inbound_argv = ["ss", "-Htn", "state", "established"]
    if tcp_port:
        inbound_argv.append("( sport = :%d )" % tcp_port)
    inbound_ok, inbound_count, inbound_err = _diag_ss_count(inbound_argv, deadline)
    tcp_ok, tcp_lines, tcp_err = _diag_ss_count(
        ["ss", "-Htln", "sport = :%d" % tcp_port] if tcp_port else ["ss", "-Htln"], deadline)
    udp_ok, udp_lines, udp_err = _diag_ss_count(
        ["ss", "-Huln", "sport = :%d" % udp_port] if udp_port else ["ss", "-Huln"], deadline)
    tcp_listening = bool(tcp_ok and tcp_lines > 0)
    udp_bound = bool(udp_ok and udp_lines > 0)

    firewall_state, firewall_detail = _diag_firewall(tcp_port, udp_port, deadline)
    public_ip, public_ip6, public_ip_error, public_ip6_error = _diag_public_ip(deadline)
    host_info["public_ip"] = public_ip
    host_info["public_ip6"] = public_ip6
    host_info["public_ip_error"] = public_ip_error
    host_info["public_ip6_error"] = public_ip6_error
    host_info["cgnat_suspect"] = _is_cgnat(public_ip)

    engine_payload = {
        "running": running,
        "ec": ec_online,
        "ed2k_connected": ed2k_connected,
        "low_id": low_id,
        "server": {
            "name": str(server.get("name") or ""),
            "ip": str(server.get("ip") or ""),
            "port": int_or(server.get("port")),
        },
        "kad": {
            "connected": kad_connected,
            "firewalled": kad_firewalled,
            "nodes": int_or(kad.get("nodes")),
        },
        "inbound_connections": int(inbound_count if inbound_ok else 0),
        "tcp_port": tcp_port,
        "udp_port": udp_port,
    }
    inbound_connections = engine_payload["inbound_connections"]
    host_text = host_info["lan_ip"] or "本机"

    # ---- checks（id 词表固定，顺序按 CHECK_ORDER 排） ----
    if running:
        version = str(status.get("version") or "")
        checks.append(_diag_check("engine", "ok", "引擎运行中",
                                  ("aMule %s" % version) if version else "aMule 引擎已启动"))
    else:
        detail = status.get("detail") or overview_error or "面板读不到 aMule 的进程状态。"
        checks.append(_diag_check("engine", "error", "引擎未运行", detail,
                                  "在面板「引擎」页启动引擎，再重新诊断"))

    if not running:
        checks.append(_diag_check("ed2k_connect", "error", "eD2k 未连接",
                                  "引擎没有运行，无法连接 eD2k 服务器。", "先启动引擎"))
    elif ed2k_connected:
        checks.append(_diag_check(
            "ed2k_connect", "ok", "已连接 eD2k 服务器",
            "%s（%s:%s）" % (server.get("name") or "未知服务器",
                             server.get("ip") or "-", int_or(server.get("port")))))
    else:
        checks.append(_diag_check("ed2k_connect", "warn", "eD2k 未连接服务器",
                                  "引擎在运行，但还没有连上任何 eD2k 服务器。",
                                  "在「服务器」页更新服务器列表并连接，或检查端口是否被占用"))

    if not ed2k_connected:
        checks.append(_diag_check("high_id", "warn", "暂时无法判断 High ID",
                                  "eD2k 未连接服务器，服务器还没机会反连本机。",
                                  "先让引擎连上 eD2k 服务器"))
    elif high_id:
        checks.append(_diag_check("high_id", "ok", "eD2k 为 High ID",
                                  "公网可以主动连到本机 TCP %d。" % tcp_port))
    else:
        checks.append(_diag_check("high_id", "warn", "eD2k 为 Low ID（受限）",
                                  "服务器反连本机 TCP %d 失败，来源与速度会受影响。"
                                  "UPnP 已开启时路由器本应自动映射该端口；未生效多为路由器固件对 UPnP 兼容性差，"
                                  "可登录路由器确认映射记录，手动转发最可靠。" % tcp_port,
                                  "路由器把 TCP %d 转发到 %s" % (tcp_port, host_text)))

    if not running:
        checks.append(_diag_check("kad", "error", "Kad 状态未知",
                                  "引擎没有运行，无法读取 Kad 状态。", "先启动引擎"))
    elif kad_open:
        checks.append(_diag_check("kad", "ok", "Kad 正常",
                                  "已连上 Kad，节点 %d，外部可主动连入 UDP %d。"
                                  % (int_or(kad.get("nodes")), udp_port)))
    elif kad_connected:
        checks.append(_diag_check("kad", "warn", "Kad 受限（firewalled）",
                                  "外部节点无法主动连入 UDP %d，搜索与来源会变少（节点 %d）。"
                                  "注意：UPnP 只负责尝试自动映射端口，映射是否成功要看路由器，"
                                  "可在路由器管理页查看 4662/4672 的映射记录。"
                                  % (udp_port, int_or(kad.get("nodes"))),
                                  "路由器把 UDP %d 转发到 %s" % (udp_port, host_text)))
    else:
        checks.append(_diag_check("kad", "warn", "Kad 未连接",
                                  "引擎在运行，但 Kad 没有连上网络。",
                                  "在「Kad」页下载 nodes.dat 后重新连接 Kad"))

    if not tcp_ok:
        checks.append(_diag_check("tcp_listen", "warn", "无法探测 TCP 监听",
                                  tcp_err or "ss 命令不可用"))
    elif tcp_listening:
        checks.append(_diag_check("tcp_listen", "ok", "TCP %d 正在监听" % tcp_port,
                                  "eD2k 的 TCP 端口已在本机监听，等待服务器反连。"))
    else:
        checks.append(_diag_check("tcp_listen", "error" if running else "warn",
                                  "TCP %d 未监听" % tcp_port,
                                  "本机没有进程在监听 TCP %d，服务器无法反连（会拿到 Low ID）。" % tcp_port,
                                  "确认引擎已启动，且该端口没有被其它程序占用"))

    if not udp_ok:
        checks.append(_diag_check("udp_bind", "warn", "无法探测 UDP 绑定",
                                  udp_err or "ss 命令不可用"))
    elif udp_bound:
        checks.append(_diag_check("udp_bind", "ok", "UDP %d 已绑定" % udp_port,
                                  "Kad 与 eD2k 的 UDP 端口已在本机绑定。"))
    else:
        checks.append(_diag_check("udp_bind", "error" if running else "warn",
                                  "UDP %d 未绑定" % udp_port,
                                  "本机没有进程占用 UDP %d，Kad 可能无法正常通信。" % udp_port,
                                  "确认引擎已启动，且该端口没有被其它程序占用"))

    if firewall_state == "blocked":
        checks.append(_diag_check("firewall", "error", "防火墙可能拦截了端口",
                                  firewall_detail,
                                  "在 fnOS 防火墙放行 TCP %d 与 UDP %d" % (tcp_port, udp_port)))
    elif firewall_state == "open":
        checks.append(_diag_check("firewall", "ok", "防火墙未拦截端口", firewall_detail))
    else:
        checks.append(_diag_check("firewall", "warn", "防火墙状态未知", firewall_detail,
                                  "在 fnOS 防火墙页面确认 TCP %d / UDP %d 已放行"
                                  % (tcp_port, udp_port)))

    if public_ip:
        checks.append(_diag_check("public_ip", "ok", "公网 IP 已获取 (IPv4)",
                                  "当前公网出口 IP：%s" % public_ip))
    else:
        checks.append(_diag_check("public_ip", "warn", "获取公网 IP 失败 (IPv4)",
                                  public_ip_error or "网络不可达或代理未配置",
                                  "检查设备的网络与代理设置"))

    if host_info["cgnat_suspect"]:
        checks.append(_diag_check("cgnat", "warn", "疑似运营商 CGNAT",
                                  "公网 IP %s 属于 100.64.0.0/10（运营商级 NAT），端口映射不会生效。"
                                  % public_ip,
                                  "向运营商申请公网 IP，或改用内网穿透/中转"))
    elif public_ip:
        checks.append(_diag_check("cgnat", "ok", "未检测到 CGNAT",
                                  "公网 IP 不在运营商 NAT 段内。"))
    else:
        checks.append(_diag_check("cgnat", "warn", "无法判断是否 CGNAT",
                                  "公网 IP 获取失败，无法判断是否处于运营商 NAT 之后。"))

    if not inbound_ok:
        checks.append(_diag_check("inbound", "warn", "无法统计入站连接",
                                  inbound_err or "ss 命令不可用"))
    elif inbound_connections > 0:
        checks.append(_diag_check("inbound", "ok", "已有外部客户端连入",
                                  "当前有 %d 条外部连到 TCP %d 的连接（High ID 的直接证据）。"
                                  % (inbound_connections, tcp_port)))
    elif high_id:
        checks.append(_diag_check("inbound", "ok", "当前没有外部连入（空闲）",
                                  "已是 High ID，暂时没有外部客户端主动连入属正常现象。"))
    else:
        checks.append(_diag_check("inbound", "warn", "没有观察到外部连入",
                                  "没有外部客户端连到 TCP %d，与 Low ID 的表现一致。" % tcp_port,
                                  "路由器把 TCP %d 转发到 %s" % (tcp_port, host_text)))

    checks.sort(key=lambda check: CHECK_ORDER.index(check["id"])
                if check["id"] in CHECK_ORDER else len(CHECK_ORDER))

    # ---- 判定 ----
    levels = [check["level"] for check in checks]
    if not running or not ed2k_connected or "error" in levels:
        grade = "error"
    elif "warn" in levels:
        grade = "warn"
    else:
        grade = "ok"

    if not running:
        title = "引擎未运行"
        detail = "aMule 引擎没有运行，先启动引擎再做网络诊断。"
    elif not ed2k_connected:
        title = "eD2k 未连接"
        detail = "引擎在运行，但还没有连上 eD2k 服务器；High ID / Low ID 需要连上服务器才能判断。"
    elif grade == "ok":
        title = "High ID · Kad 正常" if kad_open else "High ID · Kad 受限"
        detail = "公网可以主动连到本机，eD2k 与 Kad 均为开放状态，来源与速度不受限。"
    elif high_id:
        title = "High ID · Kad 受限"
        detail = "公网可以主动连到本机（High ID），但 Kad 处于受限状态，搜索到的来源会变少。"
    elif kad_open:
        title = "Low ID · Kad 正常"
        detail = "公网无法主动连到本机（Low ID），来源与速度会受影响；Kad 状态正常。"
    else:
        title = "Low ID · Kad 受限"
        detail = "公网无法主动连到本机，Kad 也受限，来源与速度都会受影响。"

    # ---- 建议（按实际缺什么给什么，不固定全给） ----
    def _add(text):
        if text and text not in suggestions:
            suggestions.append(text)

    if not running:
        _add("在面板「引擎」页启动 aMule 引擎，再重新诊断")
    else:
        if ed2k_connected and not high_id:
            _add("路由器把 TCP %d 转发到 %s" % (tcp_port, host_text))
        if kad_connected and not kad_open:
            _add("路由器把 UDP %d 转发到 %s" % (udp_port, host_text))
        if not kad_connected:
            _add("在「Kad」页下载 nodes.dat 后重新连接 Kad")
        if firewall_state == "blocked":
            _add("在 fnOS 防火墙放行 TCP %d / UDP %d" % (tcp_port, udp_port))
        if host_info["cgnat_suspect"]:
            _add("公网 IP 属于运营商 CGNAT 段（100.64.0.0/10），端口映射不会生效；"
                 "可向运营商申请公网 IP，或使用内网穿透/中转")
        if suggestions:
            _add("改完在「设置 → 网络」保存并重启引擎")

    return {
        "ok": True,
        "checked_at": int(time.time()),
        "version": runtime.version,
        "summary": {
            "grade": grade,
            "high_id": bool(high_id),
            "kad_open": bool(kad_open),
            "title": title,
            "detail": detail,
        },
        "engine": engine_payload,
        "host": host_info,
        "ports": {
            "tcp_listening": tcp_listening,
            "udp_bound": udp_bound,
            "firewall": firewall_state,
            "firewall_detail": firewall_detail,
        },
        "checks": checks,
        "suggestions": suggestions,
    }


# --------------------------------------------------------------------------
# 请求处理器
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "fn-emule-panel"
    protocol_version = "HTTP/1.0"

    # -- 基础管道 -----------------------------------------------------------
    def log_message(self, fmt, *args):
        if os.environ.get("EMULE_HTTP_DEBUG") and RT is not None:
            RT.log("%s - %s" % (self.address_string(), fmt % args))

    def read_body(self):
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except (TypeError, ValueError):
            length = 0
        if length <= 0:
            return b""
        if length > 8 * 1024 * 1024:
            return b""
        chunks = []
        remaining = length
        while remaining > 0:
            chunk = self.rfile.read(min(remaining, 1 << 20))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def json_body(self):
        raw = self.read_body()
        if not raw:
            return {}
        try:
            data = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            return {}
        return data if isinstance(data, dict) else {}

    def send_payload(self, status, body=b"", ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            for key, value in (extra or {}).items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def send_json(self, payload, status=200):
        self.send_payload(status, json.dumps(payload, ensure_ascii=False))

    def fail(self, status, message, **extra):
        payload = {"error": str(message)}
        payload.update(extra)
        self.send_json(payload, status)

    # -- 路由 ---------------------------------------------------------------
    def do_GET(self):
        self.route("GET")

    def do_HEAD(self):
        self.route("GET")

    def do_POST(self):
        self.route("POST")

    def do_DELETE(self):
        self.route("DELETE")

    def do_OPTIONS(self):
        self.send_payload(204, b"", extra={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET,POST,DELETE,OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        })

    def route(self, method):
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)
        try:
            if path.startswith("/api/"):
                self.handle_api(method, path, query)
            else:
                if method not in ("GET",):
                    self.fail(405, "不支持的请求方法")
                    return
                self.serve_static(path)
        except EngineTimeout as exc:
            self.fail(504, str(exc) or "引擎响应超时")
        except OfflineError as exc:
            self.fail(503, str(exc) or "引擎未运行")
        except ServiceMissing as exc:
            self.fail(503, str(exc) or "引擎组件不可用")
        except EngineFailure as exc:
            self.fail(error_status(exc), str(exc) or "引擎操作失败")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:  # noqa: BLE001 - 任何未预期异常都要回一句中文
            if RT is not None:
                RT.log("处理 %s %s 时异常：%r" % (method, path, exc), level="error")
            try:
                self.fail(500, "面板内部错误：%s" % (exc,))
            except Exception:
                pass

    # -- 静态托管 -----------------------------------------------------------
    def serve_static(self, path):
        if RT is None or not RT.web_dir:
            self.send_payload(404, "前端资源目录未配置\n", "text/plain; charset=utf-8")
            return
        rel = path.lstrip("/")
        if not rel or rel.endswith("/"):
            rel += "index.html"
        if ".." in rel.split("/") or rel.startswith("/"):
            self.send_payload(403, "禁止访问\n", "text/plain; charset=utf-8")
            return
        full = os.path.normpath(os.path.join(RT.web_dir, rel))
        root = os.path.abspath(RT.web_dir)
        if full != root and not full.startswith(root + os.sep):
            self.send_payload(403, "禁止访问\n", "text/plain; charset=utf-8")
            return
        if os.path.isdir(full):
            full = os.path.join(full, "index.html")
        if not os.path.isfile(full):
            message = ("前端资源缺失：%s\n请重新安装 fn-emule 应用。\n"
                       "Missing web asset, please reinstall the fn-emule package.\n" % rel)
            self.send_payload(404, message, "text/plain; charset=utf-8")
            return
        ctype = EXTRA_MIME.get(os.path.splitext(full)[1].lower())
        if not ctype:
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        try:
            with open(full, "rb") as handle:
                body = handle.read()
        except OSError as exc:
            self.send_payload(500, "读取文件失败：%s\n" % (exc,), "text/plain; charset=utf-8")
            return
        self.send_payload(200, body, ctype)

    # -- API ---------------------------------------------------------------
    def handle_api(self, method, path, query):
        if RT is None:
            self.fail(503, "面板尚未初始化完成")
            return

        # 健康探针：任何时候都要答话
        if path == "/api/health":
            status = RT.status()
            self.send_json({
                "ok": True,
                "version": RT.version,
                "amule": {"running": bool(status.get("running")),
                          "ec": bool(status.get("ec")),
                          "version": str(status.get("version") or "")},
                "engine": {"phase": status.get("phase") or "idle",
                           "detail": status.get("detail") or "",
                           "bootstrap_notes": status.get("bootstrap_notes") or []},
                "uptime": int(time.time() - RT.started_at),
                "fake": bool(RT.fake_mode),
            })
            return

        if path == "/api/overview":
            self.require_method(method, "GET")
            raw = RT.call("overview")
            data = normalize_overview(raw)
            history = RT.store.history(HISTORY_POINTS)
            if not history:
                # 面板刚起来还没采到点：先用引擎自带的（如果有）顶上，别给前端空数组
                history = [item for item in as_list(as_dict(raw).get("history"))
                           if isinstance(item, dict)]
            data["history"] = history[-HISTORY_POINTS:]
            self.send_json(data)
            return

        if path == "/api/transfers":
            self.require_method(method, "GET")
            kind = (query.get("type") or ["download"])[0].strip().lower()
            if kind not in ("download", "upload"):
                kind = "download"
            self.send_json(normalize_transfers(RT.call("transfers", kind), kind))
            return

        if path == "/api/transfers/add":
            self.require_method(method, "POST")
            body = self.json_body()
            raw = body.get("links")
            if raw is None:
                raw = body.get("link")
            if isinstance(raw, str):
                links = [part.strip() for part in re.split(r"[\r\n]+", raw) if part.strip()]
            elif isinstance(raw, list):
                links = [str(item).strip() for item in raw if str(item).strip()]
            else:
                links = []
            if not links:
                self.fail(400, "请填写下载链接")
                return
            category = str(body.get("category") or "")
            paused = bool(body.get("paused"))
            added = RT.call("add_links", links, category, paused)
            if isinstance(added, dict):
                payload = {"ok": bool(added.get("ok", True))}
                payload.update(added)
            else:
                payload = {"ok": True, "added": as_list(added), "total": len(links)}
            self.send_json(payload)
            return

        if path == "/api/transfers/apply":
            self.require_method(method, "POST")
            body = self.json_body()
            hashes = body.get("hashes")
            if isinstance(hashes, str):
                hashes = [hashes]
            hashes = [str(item).upper() for item in as_list(hashes) if str(item).strip()]
            action = str(body.get("action") or "").strip()
            if not hashes:
                self.fail(400, "请选择要操作的任务")
                return
            if action not in ("pause", "resume", "cancel", "priority"):
                self.fail(400, "不支持的操作：%s" % (action or "(空)"))
                return
            priority = body.get("priority")
            if action == "priority":
                applied = [RT.call("transfer_action", file_hash, action, priority)
                           for file_hash in hashes]
                result = {"ok": True, "applied": applied, "count": len(applied)}
            else:
                result = RT.call("transfer_apply", hashes, action)
                if not isinstance(result, dict):
                    result = {"ok": True}
            payload = {"ok": bool(result.get("ok", True))}
            payload.update(result)
            self.send_json(payload)
            return

        match = re.match(r"^/api/transfers/([0-9A-Fa-f]{32})(/action)?$", path)
        if match:
            file_hash = match.group(1).upper()
            if match.group(2):
                self.require_method(method, "POST")
                body = self.json_body()
                action = str(body.get("action") or "").strip()
                if action not in ("pause", "resume", "cancel", "priority"):
                    self.fail(400, "不支持的操作：%s" % (action or "(空)"))
                    return
                result = RT.call("transfer_action", file_hash, action, body.get("priority"))
                payload = {"ok": True}
                if isinstance(result, dict):
                    payload.update(result)
                payload.setdefault("hash", file_hash)
                self.send_json(payload)
                return
            self.require_method(method, "GET")
            detail = as_dict(RT.call("transfer_detail", file_hash))
            self.send_json({
                "file": normalize_transfer(detail.get("file")),
                "sources": as_list(detail.get("sources")),
                "chunks": as_list(detail.get("chunks")),
            })
            return

        if path == "/api/servers":
            self.require_method(method, "GET")
            data = as_dict(RT.call("servers"))
            items = [normalize_server(item) for item in as_list(data.get("items"))]
            current = as_dict(data.get("current"))
            self.send_json({
                "items": items,
                "current": {
                    "ip": str(current.get("ip") or ""),
                    "port": int_or(current.get("port")),
                    "name": str(current.get("name") or ""),
                },
                "ed2k_connected": bool(data.get("ed2k_connected")),
                "total": int_or(data.get("total"), len(items)),
                "working": int_or(data.get("working"),
                                  sum(1 for i in items if not i.get("failed"))),
            })
            return

        if path in ("/api/servers/connect", "/api/servers/add", "/api/servers/remove",
                    "/api/servers/priority", "/api/servers/update"):
            self.require_method(method, "POST")
            body = self.json_body()
            action = path.rsplit("/", 1)[-1]
            if action == "update":
                self.send_json(with_ok(RT.call("servers_update")))
                return
            ip = str(body.get("ip") or "").strip()
            if not ip:
                self.fail(400, "请填写服务器 IP")
                return
            port = int_or(body.get("port"), 0)
            if port < 1 or port > 65535:
                self.fail(400, "端口无效，应在 1-65535 之间")
                return
            if action == "connect":
                result = RT.call("server_connect", ip, port)
            elif action == "add":
                result = RT.call("server_add", ip, port, str(body.get("name") or ""))
            elif action == "remove":
                result = RT.call("server_remove", ip, port)
            else:
                priority = str(body.get("priority") or "").strip()
                if priority not in ("low", "normal", "high", "auto"):
                    self.fail(400, "优先级取值无效")
                    return
                result = RT.call("server_priority", ip, port, priority)
            self.send_json(with_ok(result))
            return

        if path == "/api/kad":
            self.require_method(method, "GET")
            data = as_dict(RT.call("kad_status"))
            payload = {"ok": True}
            payload.update(data)
            # web-ui 按 tools/mock_api.py 的形状取 nodes_dat / bootstrap_ok，
            # core 把它们放在 bootstrap.{nodes_dat,server_met} 里，这里补一层兼容
            artifacts = as_dict(data.get("bootstrap"))
            nodes_dat = as_dict(artifacts.get("nodes_dat"))
            if nodes_dat:
                payload.setdefault("nodes_dat", nodes_dat)
                payload.setdefault("server_met", as_dict(artifacts.get("server_met")))
            payload.setdefault("bootstrap_ok", bool(nodes_dat.get("exists")
                                                    or int_or(nodes_dat.get("size"))
                                                    or int_or(data.get("nodes"))))
            self.send_json(payload)
            return

        if path == "/api/kad/bootstrap":
            self.require_method(method, "POST")
            self.send_json(with_ok(RT.call("kad_bootstrap")))
            return

        if path == "/api/shared":
            self.require_method(method, "GET")
            data = as_dict(RT.call("shared"))
            items = as_list(data.get("items"))
            self.send_json({"items": items, "total": int_or(data.get("total"), len(items))})
            return

        if path == "/api/shared/reload":
            self.require_method(method, "POST")
            self.send_json(with_ok(RT.call("shared_reload")))
            return

        if path == "/api/search/start":
            self.require_method(method, "POST")
            body = self.json_body()
            query_text = str(body.get("q") or "").strip()
            if not query_text:
                self.fail(400, "搜索关键词不能为空")
                return
            kind = str(body.get("kind") or "server").strip().lower()
            if kind not in ("server", "kad", "global"):
                self.fail(400, "搜索范围无效，应为 server/kad/global")
                return
            search_method = str(body.get("method") or "name").strip().lower()
            if search_method not in ("name", "size", "type"):
                search_method = "name"
            result = as_dict(RT.call("search_start", query_text, kind, search_method))
            payload = {"ok": True}
            payload.update(result)
            payload["search_id"] = str(result.get("search_id") or result.get("id") or "")
            self.send_json(payload)
            return

        match = re.match(r"^/api/search/([A-Za-z0-9_-]+)(/stop|/download)?$", path)
        if match:
            search_id = match.group(1)
            suffix = match.group(2) or ""
            if suffix == "/stop":
                self.require_method(method, "POST")
                self.send_json(with_ok(RT.call("search_stop", search_id)))
                return
            if suffix == "/download":
                self.require_method(method, "POST")
                body = self.json_body()
                file_hash = str(body.get("hash") or "").strip().upper()
                if not file_hash:
                    self.fail(400, "请提供要下载的哈希")
                    return
                self.send_json(with_ok(RT.call("search_download", search_id, file_hash)))
                return
            self.require_method(method, "GET")
            data = as_dict(RT.call("search_state", search_id))
            query_text = str(data.get("q") or data.get("query") or "")
            self.send_json({
                "search_id": str(data.get("search_id") or search_id),
                "q": query_text,
                "query": query_text,
                "kind": str(data.get("kind") or ""),
                "method": str(data.get("method") or ""),
                "progress": int_or(data.get("progress")),
                "done": bool(data.get("done")),
                "stopped": bool(data.get("stopped")),
                "results": as_list(data.get("results")),
                "started_at": int_or(data.get("started_at")),
            })
            return

        if path == "/api/stats":
            self.require_method(method, "GET")
            data = RT.call("stats")
            items = []
            groups = []
            if isinstance(data, list):
                items = [item for item in data if isinstance(item, dict)]
            elif isinstance(data, dict):
                items = [item for item in as_list(data.get("items")) if isinstance(item, dict)]
                groups = [str(g) for g in as_list(data.get("groups"))]
            rows = []
            for item in items:
                group = str(item.get("group") or "其他")
                if group not in groups:
                    groups.append(group)
                row = {"group": group, "name": str(item.get("name") or ""),
                       "value": item.get("value")}
                # core v26.11.1 起还带 name_zh / group_zh（未命中为空串），原样透出；
                # 前端按 name_zh || name 回退即可，面板不做二次翻译
                for extra in ("raw", "display", "name_zh", "group_zh"):
                    if extra in item:
                        row[extra] = item.get(extra)
                rows.append(row)
            self.send_json({"groups": groups, "items": rows})
            return

        if path == "/api/log":
            self.require_method(method, "GET")
            limit = int_or((query.get("limit") or ["200"])[0], 200)
            limit = max(1, min(2000, limit))
            engine_lines = []
            if RT.service is not None:
                try:
                    engine_lines = [line for line in as_list(RT.call("logs", limit, timeout=6.0))
                                    if isinstance(line, dict)]
                except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing):
                    engine_lines = []
            merged = []
            for line in engine_lines:
                merged.append({"t": int_or(line.get("t")),
                               "level": str(line.get("level") or "info"),
                               "text": str(line.get("text") or ""), "source": "engine"})
            for line in RT.store.read_log(limit):
                merged.append({"t": int_or(line.get("t")),
                               "level": str(line.get("level") or "info"),
                               "text": str(line.get("text") or ""), "source": "panel"})
            merged.sort(key=lambda line: line["t"])
            self.send_json({"items": merged[-limit:], "limit": limit})
            return

        if path == "/api/settings":
            if method == "GET":
                self.send_json({"ok": True, "settings": mask_settings(RT.store.settings()),
                                "version": RT.version,
                                "engine": {"phase": RT.engine_phase}})
                return
            self.require_method(method, "POST")
            body = self.json_body()
            patch = body.get("settings") if isinstance(body.get("settings"), dict) else body
            patch = {key: value for key, value in patch.items() if key != "ok"}
            error = validate_settings_patch(patch)
            if error:
                self.fail(400, error)
                return
            warnings = []
            message = ""
            panel_patch = patch.get("panel") if isinstance(patch.get("panel"), dict) else {}
            desired_port = int_or(panel_patch.get("port")) if "port" in panel_patch else 0
            if desired_port and desired_port != RT.port:
                # 先在新端口起监听，成功了才落盘 + 关旧监听；失败保持原样
                try:
                    RT.switch_port(desired_port)
                except ValueError as exc:
                    self.fail(400, str(exc))
                    return
                message = "面板已切换到新端口，请用新地址访问"
                warnings.append("面板已切换为 http://<本机IP>:%d/，旧端口已关闭" % desired_port)
            settings, changed = RT.store.update(patch)
            restart_required = False
            engine_patch = patch.get("engine") if isinstance(patch.get("engine"), dict) else {}
            if engine_patch:
                # 整份 engine 补丁交给 core：它自己决定哪些走 EC 即时生效、哪些要写
                # amule.conf 等重启，并把权威的 restart_required 回给我们。
                try:
                    applied = as_dict(RT.call("apply_prefs", engine_patch, timeout=10.0))
                    restart_required = bool(applied.get("restart_required"))
                    if applied.get("message"):
                        warnings.append(str(applied["message"]))
                except OfflineError:
                    warnings.append("引擎未运行，设置已保存，将在引擎启动后生效")
                except (EngineTimeout, EngineFailure, ServiceMissing) as exc:
                    warnings.append("应用引擎偏好失败：%s" % (exc,))
                for key in ("tcp_port", "udp_port", "ec_port", "incoming_dir", "temp_dir",
                            "shared_dirs", "ipfilter", "ec_password", "upnp"):
                    if key in engine_patch:
                        restart_required = True
            RT.log("设置已更新：%s" % (", ".join(sorted(changed)) or "无变化"))
            payload = {
                "ok": True,
                "settings": mask_settings(RT.store.settings()),
                "changed": sorted(changed),
                "restart_required": restart_required,
                "warnings": warnings,
            }
            if message:
                payload["message"] = message
            self.send_json(payload)
            return

        if path == "/api/prefs":
            if method == "POST":
                body = self.json_body()
                patch = body.get("prefs") if isinstance(body.get("prefs"), dict) else body
                patch = {k: v for k, v in patch.items() if k not in ("ok", "prefs")}
                self.send_json(with_ok(RT.call("apply_prefs", patch)))
                return
            self.require_method(method, "GET")
            try:
                prefs = as_dict(RT.call("prefs", timeout=8.0))
                offline = False
            except (OfflineError, ServiceMissing):
                prefs = as_dict(RT.store.section("engine"))
                offline = True
            payload = dict(prefs)
            payload["ok"] = True
            payload["prefs"] = prefs
            payload["offline"] = offline
            payload["source"] = "settings" if offline else "engine"
            self.send_json(payload)
            return

        if path == "/api/core/status":
            self.require_method(method, "GET")
            payload = {"ok": True}
            payload.update(RT.status())
            self.send_json(payload)
            return

        if path == "/api/diagnostics":
            # 诊断接口只读，GET / POST 行为一致；任何内部异常都降级成 grade=error
            if method not in ("GET", "POST"):
                self.fail(405, "不支持的请求方法：%s" % method)
                return
            try:
                payload = build_diagnostics(RT)
            except Exception as exc:  # noqa: BLE001 - 诊断本身绝不 5xx
                RT.log("诊断接口内部异常：%r" % (exc,), level="error")
                payload = {
                    "ok": True,
                    "checked_at": int(time.time()),
                    "version": RT.version,
                    "summary": {"grade": "error", "high_id": False, "kad_open": False,
                                "title": "诊断失败",
                                "detail": "诊断过程中出现内部错误：%s" % (exc,)},
                    "engine": {"running": False, "ec": False, "ed2k_connected": False,
                               "low_id": False,
                               "server": {"name": "", "ip": "", "port": 0},
                               "kad": {"connected": False, "firewalled": False, "nodes": 0},
                               "inbound_connections": 0, "tcp_port": 0, "udp_port": 0},
                    "host": {"lan_ip": "", "gateway": "", "iface": "", "public_ip": "",
                             "public_ip_error": "诊断中断", "private_ip": False,
                             "cgnat_suspect": False},
                    "ports": {"tcp_listening": False, "udp_bound": False,
                              "firewall": "unknown", "firewall_detail": "诊断中断"},
                    "checks": [_diag_check("engine", "error", "诊断失败", str(exc),
                                           "重试一次；仍然失败请看面板日志")],
                    "suggestions": ["重试诊断；如果仍然失败，请查看面板日志"],
                }
            self.send_json(payload)
            return

        match = re.match(r"^/api/core/(start|stop|restart)$", path)
        if match:
            self.require_method(method, "POST")
            action = match.group(1)
            if RT.service is None:
                self.fail(503, "引擎组件不可用（core.service 未加载），请检查安装是否完整")
                return
            with RT.control_lock:
                try:
                    RT.engine_phase = action + "ing"
                    RT.call(action, timeout=CONTROL_TIMEOUT)
                    RT.engine_phase = "running" if action != "stop" else "stopped"
                    RT.engine_detail = ""
                    RT.log("引擎操作成功：%s" % action)
                except EngineTimeout:
                    if action == "stop":
                        # 停引擎可能因为落盘 partfile 超过 15 秒。这不是失败，也不是
                        # 引擎不回话，而是「还在停」—— 用 202 明确告诉前端去轮询状态。
                        RT.engine_phase = "stopping"
                        RT.log("引擎停止超过 15 秒，转后台继续", level="warn")
                        payload = {"ok": True, "action": action, "pending": True,
                                   "message": "引擎正在停止（大文件落盘可能需要十几秒），请稍后刷新状态"}
                        payload.update(RT.status())
                        self.send_json(payload, 202)
                        return
                    raise
                except EngineFailure as exc:
                    RT.engine_phase = "failed"
                    RT.engine_detail = str(exc)
                    RT.log("引擎操作失败（%s）：%s" % (action, exc), level="error")
                    self.fail(500, "引擎操作失败：%s" % (exc,), amule=RT.status())
                    return
            payload = {"ok": True, "action": action}
            payload.update(RT.status())
            self.send_json(payload)
            return

        # ---------------- 通知 ----------------
        if path == "/api/notify":
            self.require_method(method, "GET")
            cfg = RT.store.section("notify")
            records = [notify_record_public(item) for item in RT.store.notify_records()]
            self.send_json({
                "ok": True,
                "settings": normalize_notify_settings(cfg),
                "channels": [notify.channel_public(c) for c in as_list(cfg.get("channels"))
                             if isinstance(c, dict)],
                "types": notify.type_list(RT.store.section("panel").get("lang") or "zh"),
                "log": records,
                "total": len(records),
            })
            return

        if path == "/api/notify/settings":
            self.require_method(method, "POST")
            body = self.json_body()
            # 两种载荷都接受：
            #   扁平 {enabled, events:{complete,error}} / {on_complete, on_error}
            #   包一层 {settings:{...}}（与 /api/settings 的写法统一）
            if isinstance(body.get("settings"), dict):
                body = body["settings"]
            cfg = RT.store.section("notify")
            events = as_dict(cfg.get("events"))
            patch = {}
            if "enabled" in body:
                patch["enabled"] = bool(body["enabled"])
            incoming_events = as_dict(body.get("events"))
            for key in ("complete", "error"):
                if key in incoming_events:
                    events[key] = bool(incoming_events[key])
            if "on_complete" in body:
                events["complete"] = bool(body["on_complete"])
            if "on_error" in body:
                events["error"] = bool(body["on_error"])
            patch["events"] = events
            RT.store.update({"notify": patch})
            RT.log("通知设置已更新：enabled=%s events=%s" % (patch.get("enabled", cfg.get("enabled")),
                                                          events))
            self.send_json({"ok": True,
                            "settings": normalize_notify_settings(RT.store.section("notify"))})
            return

        # 删除通道：POST {id, delete:true}（前端清单用法）/ DELETE 本路径 / DELETE /api/notify/channel/<id>
        match = re.match(r"^/api/notify/channel/([A-Za-z0-9_-]+)$", path)
        if match and method == "DELETE":
            self.delete_notify_channel(match.group(1))
            return

        if path == "/api/notify/channel":
            if method == "DELETE":
                body = self.json_body()
                channel_id = str(body.get("id") or (query.get("id") or [""])[0]).strip()
                if not channel_id:
                    self.fail(400, "请提供要删除的通道 id")
                    return
                self.delete_notify_channel(channel_id)
                return
            self.require_method(method, "POST")
            body = self.json_body()
            cfg = RT.store.section("notify")
            channel_id = str(body.get("id") or "").strip()
            if body.get("delete") or body.get("action") == "delete":
                if not channel_id:
                    self.fail(400, "请提供要删除的通道 id")
                    return
                self.delete_notify_channel(channel_id)
                return
            channel_type = str(body.get("type") or "").strip()
            if channel_type not in notify.CHANNEL_TYPES:
                self.fail(400, "未知的通知通道类型：%s" % (channel_type or "(空)"))
                return
            channels = [c for c in as_list(cfg.get("channels")) if isinstance(c, dict)]
            channel_id = channel_id or uuid_hex()
            old = None
            for channel in channels:
                if channel.get("id") == channel_id:
                    old = channel
                    break
            channel = {
                "id": channel_id,
                "name": str(body.get("name") or "").strip()
                        or notify.CHANNEL_TYPES[channel_type]["label_zh"],
                "type": channel_type,
                "enabled": bool(body.get("enabled", True)),
                "config": notify.merge_config(channel_type, as_dict(body.get("config")),
                                              as_dict((old or {}).get("config"))),
            }
            if old is None:
                channels.append(channel)
            else:
                channels = [channel if c.get("id") == channel_id else c for c in channels]
            enabled = bool(cfg.get("enabled"))
            # 加第一个通道就顺手打开总开关：加了却收不到消息是最迷惑的默认值
            if not enabled and len(channels) >= 1:
                enabled = True
            RT.store.update({"notify": {"channels": channels, "enabled": enabled}})
            self.send_json({
                "ok": True,
                "channel": notify.channel_public(channel),
                "channels": [notify.channel_public(c) for c in channels],
                "settings": normalize_notify_settings(RT.store.section("notify")),
            })
            return

        if path == "/api/notify/test":
            self.require_method(method, "POST")
            body = self.json_body()
            channel_id = str(body.get("id") or body.get("channel_id") or "").strip()
            cfg = RT.store.section("notify")
            channels = [c for c in as_list(cfg.get("channels")) if isinstance(c, dict)]
            if not channels:
                self.fail(400, "还没有配置通知通道，请先添加一个")
                return
            title = "eMule 测试通知 / Test notification"
            body_text = ("这是一条来自 eMule 面板的测试消息，收到即表示通知通道配置正确。\n"
                         "This is a test message from the eMule panel.")
            results = RT.send_channels(title, body_text, event="test", channel_id=channel_id)
            ok = bool(results) and all(item.get("ok") for item in results)
            self.send_json({"ok": ok, "results": results, "sent": len(results)})
            return

        # ---------------- 备份 ----------------
        if path == "/api/backup/status":
            self.require_method(method, "GET")
            cfg = RT.store.section("backup")
            items = RT.store.backup_list()
            self.send_json({
                "ok": True,
                "auto": bool(cfg.get("auto")),
                "keep": int_or(cfg.get("keep"), 7),
                "last": int_or(cfg.get("last")),
                "dir": RT.store.backup_dir,
                "count": len(items),
                "items": items,
            })
            return

        if path == "/api/backup/run":
            self.require_method(method, "POST")
            body = self.json_body()
            try:
                result = RT.store.backup_create(tag="manual", keep=body.get("keep"))
            except ValueError as exc:
                self.fail(500, str(exc))
                return
            payload = {"ok": True}
            payload.update(result)
            self.send_json(payload)
            return

        if path == "/api/backup/delete":
            self.require_method(method, "POST")
            body = self.json_body()
            name = str(body.get("name") or "").strip()
            if not name:
                self.fail(400, "请选择要删除的备份文件")
                return
            if not RT.store.backup_path(name):
                self.fail(404, "备份文件不存在或不在 backups 目录下")
                return
            try:
                result = RT.store.backup_delete(name)
            except ValueError as exc:
                self.fail(400, "删除失败：%s" % (exc,))
                return
            self.send_json({"ok": True, "name": result["name"], "removed": True})
            return

        if path == "/api/backup/restore":
            self.require_method(method, "POST")
            body = self.json_body()
            name = str(body.get("name") or "").strip()
            if not name:
                self.fail(400, "请选择要恢复的备份文件")
                return
            if not RT.store.backup_path(name):
                self.fail(404, "备份文件不存在或不在 backups 目录下")
                return
            try:
                result = RT.store.backup_restore(name)
            except ValueError as exc:
                self.fail(400, "恢复失败：%s" % (exc,))
                return
            warnings = []
            restarted = False
            if RT.service is not None:
                try:
                    RT.call("restart", timeout=CONTROL_TIMEOUT)
                    restarted = True
                    RT.engine_phase = "running"
                except (EngineTimeout, OfflineError, EngineFailure, ServiceMissing) as exc:
                    warnings.append("配置已恢复，但引擎重启失败：%s" % (exc,))
            self.send_json({"ok": True, "restored": result.get("files") or [],
                            "name": result.get("name") or name,
                            "restarted": restarted, "warnings": warnings})
            return

        # ---------------- 更新 ----------------
        if path == "/api/update/check":
            self.require_method(method, "GET")
            force = str((query.get("force") or ["0"])[0]).lower() not in ("", "0", "false", "no")
            self.send_json(RT.update_checker.check(force=force))
            return

        if path == "/api/update/install":
            self.require_method(method, "POST")
            self.install_update()
            return

        self.fail(404, "接口不存在：%s" % path)

    # -- 更新安装（只下载，不调用 fnOS 安装器） -----------------------------
    def install_update(self):
        info = RT.update_checker.check(force=True)
        if not info.get("ok"):
            self.fail(502, "无法获取版本信息：%s" % (info.get("error") or "未知原因"))
            return
        if not info.get("available"):
            self.fail(400, "当前已是最新版本（%s）" % (info.get("current") or RT.version))
            return
        assets = info.get("assets") or []
        picked = None
        for asset in assets:
            if str(asset.get("name") or "").lower().endswith(".fpk"):
                picked = asset
                if "-x86" in asset["name"] or "-all" in asset["name"]:
                    break
        if picked is None:
            self.fail(400, "该版本没有附带 .fpk 安装包，请到 Release 页面手动下载")
            return
        name = os.path.basename(str(picked.get("name") or "fn-emule-update.fpk"))
        if not name.lower().endswith(".fpk"):
            self.fail(400, "安装包文件名不合法")
            return
        dest = os.path.join(RT.store.updates_dir(), name)
        try:
            result = netutil.download(picked.get("url"), dest, timeout=180.0, retries=1)
        except netutil.FetchError as exc:
            RT.log("更新包下载失败：%s" % (exc,), level="error")
            self.fail(502, "下载安装包失败：%s" % (exc,))
            return
        validate_fpk(result["path"])
        RT.log("更新包已下载并通过校验：%s（%d 字节）" % (result["path"], result["size"]))

        # 覆盖升级流程：stop → uninstall → install-fpk → start（fnOS 不支持直接覆盖安装）。
        # 实测 fnOS 的 uninstall 不删除 @appdata（面板设置与下载进度都保留），
        # 所以覆盖升级是安全的。脚本以后台方式运行（面板进程本身会被重启）。
        var_dir = RT.store.var_dir
        panel_cfg = as_dict(RT.store.section("panel"))
        engine_cfg = as_dict(RT.store.section("engine"))
        env_path = os.path.join(var_dir, "update.env")
        with open(env_path, "w", encoding="utf-8") as handle:
            handle.write("wizard_backend_port=%d\n" % int_or(panel_cfg.get("port"), 17581))
            handle.write("wizard_tcp_port=%d\n" % int_or(engine_cfg.get("tcp_port"), 4662))
            handle.write("wizard_udp_port=%d\n" % int_or(engine_cfg.get("udp_port"), 4672))
        script_path = os.path.join(var_dir, "update-install.sh")
        script = (
            "#!/bin/bash\n"
            "set -u\n"
            'APP_NAME="fn-emule"'
            "FPK=" + shlex_quote(result["path"]) + "\n"
            "ENV_FILE=" + shlex_quote(env_path) + "\n"
            "LOG=" + shlex_quote(os.path.join(var_dir, "update-install.log")) + "\n"
            'exec 9>>"$LOG"'
            "log() { echo \"[$(date +%F_%T)] $*\" >&9; }\n"
            'log "开始更新安装：$FPK"'
            'appcenter-cli stop "$APP_NAME" >/dev/null 2>&1 || true\n'
            "sleep 2\n"
            'appcenter-cli uninstall "$APP_NAME" 2>&1 | tr "\r" "\n" | tail -1 >&9\n'
            "sleep 2\n"
            'appcenter-cli install-fpk "$FPK" -e "$ENV_FILE" -v 1 2>&1 | tr "\r" "\n" | grep -vE "installing|Verifying" | tail -3 >&9\n'
            "sleep 2\n"
            'started=0\n' +
            'n=0\n' +
            'while [ "$n" -lt 6 ]; do\n' +
            '  if appcenter-cli status "$APP_NAME" 2>/dev/null | grep -qE "running|starting"; then started=1; break; fi\n' +
            '  appcenter-cli start "$APP_NAME" 2>&1 | tail -1 >&9\n' +
            '  sleep 3\n' +
            '  if appcenter-cli status "$APP_NAME" 2>/dev/null | grep -qE "running|starting"; then started=1; break; fi\n' +
            '  n=$((n + 1))\n' +
            'done\n' +
            'if [ "$started" != "1" ]; then log "new package did not start, see log"; exit 1; fi\n'
            'log "更新安装脚本结束"'
        )
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(script)
        os.chmod(script_path, 0o755)
        RT.log("启动后台更新脚本，面板即将重启")
        subprocess.Popen(["/bin/bash", "-c",
                          "exec setsid \"%s\" >/dev/null 2>&1 < /dev/null &" % script_path],
                         cwd=var_dir, start_new_session=True)
        self.send_json({"ok": True, "path": result["path"], "name": name,
                        "size": result["size"], "version": info.get("latest") or "",
                        "note": "安装包已下载，正在后台执行覆盖升级（面板会短暂离线后自动恢复）"})

    # -- 小工具 -------------------------------------------------------------
    def delete_notify_channel(self, channel_id):
        """删除一个通知通道，返回 {ok, channel, channels, settings}。"""
        channel_id = str(channel_id or "").strip()
        if not channel_id:
            self.fail(400, "请提供要删除的通道 id")
            return
        cfg = RT.store.section("notify")
        channels = [c for c in as_list(cfg.get("channels")) if isinstance(c, dict)]
        target = None
        for channel in channels:
            if channel.get("id") == channel_id:
                target = channel
                break
        if target is None:
            self.fail(404, "通知通道不存在：%s" % channel_id)
            return
        remaining = [c for c in channels if c.get("id") != channel_id]
        RT.store.update({"notify": {"channels": remaining}})
        RT.log("已删除通知通道：%s" % (target.get("name") or target.get("type") or channel_id))
        self.send_json({
            "ok": True,
            "channel": notify.channel_public(target),
            "channels": [notify.channel_public(c) for c in remaining],
            "settings": normalize_notify_settings(RT.store.section("notify")),
        })

    def require_method(self, method, expected):
        if method != expected:
            self.fail(405, "不支持的请求方法：%s" % method)

def validate_fpk(path):
    """卸载之前先确认下载的 fpk 是合法的本应用安装包（结构 + appname）。"""
    import tarfile
    try:
        with tarfile.open(path, "r:gz") as tf:
            names = tf.getnames()
            if "manifest" not in names or "app.tgz" not in names:
                raise ValueError("安装包结构不完整")
            raw = tf.extractfile("manifest").read().decode("utf-8", "replace")
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("安装包无法解压：%s" % exc)
    appname = ""
    for line in raw.splitlines():
        if line.strip().startswith("appname"):
            appname = line.split("=", 1)[1].strip()
            break
    if appname != "fn-emule":
        raise ValueError("安装包应用名不匹配：%s" % (appname or "?"))



# --------------------------------------------------------------------------
# 入口
# --------------------------------------------------------------------------
def parse_args(argv):
    parser = argparse.ArgumentParser(description="fn-emule 面板后端（HTTP + 路由 + 静态托管）")
    parser.add_argument("--port", type=int, default=0,
                        help="监听端口，默认取 EMULE_PANEL_PORT 或设置里的 panel.port")
    parser.add_argument("--host", default=os.environ.get("EMULE_PANEL_HOST") or "0.0.0.0",
                        help="监听地址（fnOS 的 CGI 代理需要 0.0.0.0）")
    parser.add_argument("--var", default="", help="运行时数据目录，默认取 EMULE_VAR/TRIM_PKGVAR")
    parser.add_argument("--app-home", default="",
                        help="应用目录（含 web/），默认取 EMULE_APP_HOME/TRIM_APPDEST")
    parser.add_argument("--share-dir", default="", help="用户可见共享目录，默认取 EMULE_SHARE_DIR")
    parser.add_argument("--web", default="", help="前端目录，默认 <app_home>/web")
    parser.add_argument("--fake-service", action="store_true",
                        help="使用 tmp/fake_service.py 假引擎（等价于 EMULE_FAKE=1）")
    parser.add_argument("--no-service", action="store_true",
                        help="完全不加载引擎（等价于 EMULE_NO_SERVICE=1），只测 HTTP 层")
    return parser.parse_args(argv)


def build_runtime(args):
    global RT
    app_home = resolve_app_home(args.app_home)
    var_dir = resolve_var_dir(args.var)
    share_dir = (os.path.abspath(args.share_dir) if args.share_dir
                 else resolve_share_dir(app_home))
    web_dir = os.path.abspath(args.web) if args.web else os.path.join(app_home, "web")
    version = resolve_version()
    netutil.set_version(version)

    store = storemod.Store(var_dir, share_dir=share_dir, app_home=app_home, version=version)
    store.load()
    store.ensure_dirs()

    port = int_or(args.port, 0)
    if port <= 0:
        port = int_or(os.environ.get("EMULE_PANEL_PORT"), 0)
    if port <= 0:
        port = int_or(store.section("panel").get("port"), DEFAULT_PORT)
    if port <= 0:
        port = DEFAULT_PORT

    fake = bool(args.fake_service) or str(os.environ.get("EMULE_FAKE", "")).strip() in (
        "1", "true", "yes")
    no_service = bool(args.no_service) or str(os.environ.get("EMULE_NO_SERVICE", "")).strip() in (
        "1", "true", "yes")

    RT = Runtime(store, app_home, web_dir, version, port, fake)
    store.log("=" * 60)
    store.log("fn-emule 面板启动：version=%s var=%s web=%s fake=%s"
              % (version, var_dir, web_dir, fake))
    RT.load_service(no_service=no_service)
    return RT


def main(argv=None):
    global RT
    args = parse_args(argv if argv is not None else sys.argv[1:])
    rt = build_runtime(args)
    # 先监听，再起引擎：cmd/main 只等 30 秒端口就绪，引擎 bootstrap（下载
    # server.met/nodes.dat）可能比这更久，不能把它挡在监听之前。
    try:
        rt.start_http(args.host, rt.port)
    except OSError as exc:
        rt.log("端口 %s:%s 绑定失败：%s" % (args.host, rt.port, exc), level="error")
        rt.stop_http_servers()
        rt.shutdown()
        return 2
    # 升级/改端口后 settings.panel.port 可能还是旧值：对齐并持久化，同时重写
    # runtime-ports.env（CGI 代理与 cmd/main 都读它，必须和实际监听端口一致）
    rt.sync_recorded_port()
    rt.log("面板已监听 http://%s:%d/（./api 前缀）" % (args.host, rt.port))

    def on_signal(signum, frame):
        if rt.stopping.is_set():
            return
        rt.log("收到信号 %s，开始优雅停机" % signum)
        rt.stopping.set()

    try:
        signal.signal(signal.SIGTERM, on_signal)
        signal.signal(signal.SIGINT, on_signal)
    except (ValueError, OSError):
        pass

    if rt.service is not None:
        threading.Thread(target=rt.boot_engine, name="boot", daemon=True).start()
    rt.start_workers()
    # HTTP 监听跑在自己的线程里（运行中可以换端口），主线程只等停机信号
    try:
        while not rt.stopping.wait(0.5):
            pass
    except KeyboardInterrupt:
        rt.log("收到 KeyboardInterrupt，面板退出")
        rt.stopping.set()
    finally:
        rt.stop_http_servers()
        rt.shutdown()
        rt.log("面板已退出")
    return 0


if __name__ == "__main__":
    sys.exit(main())
