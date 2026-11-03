#!/usr/bin/env python3
"""fn-emule 面板的 HTTP 抓取层：urllib + 系统代理 + 超时/重试/UA。

两条背景，决定了这个模块为什么存在：

1. fnOS 自带 python3 是纯标准库环境（CONTRACT §6），面板不能依赖 requests。
2. aMule 自带的 HTTP 客户端在代理网络下会触发 wxWidgets 断言直接崩溃，
   所以 server.met / nodes.dat / .fpk 一律由面板自己下载（见开发记忆），
   aMule 只负责读文件。

对外只暴露 get_text / get_json / download / describe_error，错误一律抛 FetchError，
调用方拿 str(exc) 就能直接给用户看中文原因。
"""
import gzip
import json
import os
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_TIMEOUT = 8.0
DEFAULT_RETRIES = 1
MAX_TEXT_BYTES = 2 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 256 * 1024 * 1024
CHUNK = 256 * 1024

PANEL_VERSION = "26.11.0"


def set_version(version):
    """让 UA 带上真实版本号，GitHub 侧排查问题时能对上是哪个包。"""
    global PANEL_VERSION
    text = str(version or "").strip()
    if text:
        PANEL_VERSION = text


def user_agent():
    return "fn-emule-panel/%s (+https://github.com/Smi13zZ/fn-emule)" % PANEL_VERSION


class FetchError(Exception):
    """抓取失败。消息已经是中文，可直接回给前端。"""


def describe_error(exc):
    """把 urllib 的一堆异常翻译成一句中文。"""
    if isinstance(exc, FetchError):
        return str(exc)
    if isinstance(exc, urllib.error.HTTPError):
        if exc.code == 401:
            return "HTTP 401（认证失败）"
        if exc.code == 403:
            return "HTTP 403（接口被限流或拒绝访问）"
        if exc.code == 404:
            return "HTTP 404（资源不存在）"
        if exc.code == 429:
            return "HTTP 429（请求过于频繁）"
        return "HTTP %d（服务器返回错误）" % exc.code
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None) or exc
        if isinstance(reason, socket.timeout):
            return "请求超时"
        if isinstance(reason, ssl.SSLError):
            return "HTTPS 证书校验失败：%s" % (reason,)
        if isinstance(reason, socket.gaierror):
            return "域名解析失败（检查 DNS 或代理）"
        if isinstance(reason, ConnectionRefusedError):
            return "连接被拒绝（检查代理设置）"
        return "网络不可达：%s" % (reason,)
    if isinstance(exc, socket.timeout):
        return "请求超时"
    if isinstance(exc, ssl.SSLError):
        return "HTTPS 证书校验失败：%s" % (exc,)
    return str(exc) or exc.__class__.__name__


def _insecure_tls():
    return str(os.environ.get("EMULE_INSECURE_TLS", "")).strip() in ("1", "true", "yes")


def _ssl_context(insecure=None):
    if insecure is None:
        insecure = _insecure_tls()
    if insecure:
        return ssl._create_unverified_context()
    try:
        return ssl.create_default_context()
    except Exception:  # pragma: no cover - 老 python 兜底
        return None


def _build_opener(insecure=False, proxy=None):
    """默认走系统代理（http_proxy/https_proxy/no_proxy 环境变量）。"""
    handlers = []
    if proxy:
        handlers.append(urllib.request.ProxyHandler(dict(proxy)))
    else:
        handlers.append(urllib.request.ProxyHandler())
    context = _ssl_context(insecure)
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    return urllib.request.build_opener(*handlers)


def _headers(extra=None):
    base = {
        "User-Agent": user_agent(),
        "Accept": "*/*",
        "Accept-Encoding": "gzip",
    }
    base.update(extra or {})
    return base


def _decode(resp, raw, max_bytes):
    if len(raw) > max_bytes:
        raise FetchError("响应体超过 %d KB，已中止" % (max_bytes // 1024))
    encoding = str(resp.headers.get("Content-Encoding") or "").lower()
    if "gzip" in encoding:
        try:
            raw = gzip.decompress(raw)
        except (OSError, ValueError):
            pass
    charset = ""
    try:
        charset = resp.headers.get_content_charset() or ""
    except Exception:
        charset = ""
    return raw.decode(charset or "utf-8", "replace")


def open_url(url, timeout=DEFAULT_TIMEOUT, headers=None, data=None, method=None,
             insecure=False, proxy=None):
    """一次请求，返回 (状态码, 解码后的文本)。网络层错误抛 FetchError。"""
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise FetchError("地址无效：%s" % (url or "(空)"))
    req = urllib.request.Request(url, data=data, headers=_headers(headers),
                                 method=method or ("POST" if data else "GET"))
    opener = _build_opener(insecure=insecure, proxy=proxy)
    try:
        with opener.open(req, timeout=timeout) as resp:
            raw = resp.read(MAX_TEXT_BYTES + 1)
            return getattr(resp, "status", 200), _decode(resp, raw, MAX_TEXT_BYTES)
    except urllib.error.HTTPError as exc:
        raise FetchError(describe_error(exc))
    except urllib.error.URLError as exc:
        raise FetchError(describe_error(exc))
    except socket.timeout:
        raise FetchError("请求超时")
    except (ssl.SSLError, ValueError) as exc:
        raise FetchError(describe_error(exc))


def get_text(url, timeout=DEFAULT_TIMEOUT, headers=None, retries=DEFAULT_RETRIES,
             accept=None, insecure=False):
    """取文本。retries 只针对网络层失败重试；HTTP 4xx 不重试（重试也没用）。"""
    extra = dict(headers or {})
    if accept:
        extra.setdefault("Accept", accept)
    last = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            status, text = open_url(url, timeout=timeout, headers=extra, insecure=insecure)
            if status and status >= 400:
                raise FetchError("HTTP %d（服务器返回错误）" % status)
            return text
        except FetchError as exc:
            last = exc
            if "HTTP 4" in str(exc):
                break
            if attempt < int(retries):
                time.sleep(0.4 * (attempt + 1))
    raise last or FetchError("请求失败")


def get_json(url, timeout=DEFAULT_TIMEOUT, headers=None, retries=DEFAULT_RETRIES,
             accept="application/json", insecure=False):
    text = get_text(url, timeout=timeout, headers=headers, retries=retries,
                    accept=accept, insecure=insecure)
    try:
        return json.loads(text)
    except ValueError as exc:
        raise FetchError("返回内容不是合法 JSON：%s" % (exc,))


def fetch_bytes(url, timeout=DEFAULT_TIMEOUT + 12, headers=None, retries=DEFAULT_RETRIES,
                limit=MAX_DOWNLOAD_BYTES, insecure=False):
    """把整个响应读进内存（server.met / nodes.dat 这种几百 KB 的文件用）。"""
    extra = headers or {}
    last = None
    for attempt in range(max(0, int(retries)) + 1):
        req = urllib.request.Request(url, headers=_headers(extra))
        opener = _build_opener(insecure=insecure)
        try:
            with opener.open(req, timeout=timeout) as resp:
                blob = bytearray()
                while True:
                    chunk = resp.read(CHUNK)
                    if not chunk:
                        break
                    blob.extend(chunk)
                    if len(blob) > limit:
                        raise FetchError("文件超过 %d MB，已中止" % (limit // 1024 // 1024))
                return bytes(blob)
        except urllib.error.HTTPError as exc:
            raise FetchError(describe_error(exc))
        except urllib.error.URLError as exc:
            last = FetchError(describe_error(exc))
        except socket.timeout:
            last = FetchError("请求超时")
        except OSError as exc:
            last = FetchError("读取失败：%s" % (exc,))
        if attempt < int(retries):
            time.sleep(0.5 * (attempt + 1))
    raise last or FetchError("下载失败")


def download(url, dest, timeout=DEFAULT_TIMEOUT + 22, retries=DEFAULT_RETRIES,
             limit=MAX_DOWNLOAD_BYTES, insecure=False, progress=None):
    """流式下载到 dest（先写 .part 再原子改名），返回 {path,size,url}。

    progress(已下载字节, 总字节或 0) 可选，用于把进度写进界面。
    """
    url = str(url or "").strip()
    if not url.startswith(("http://", "https://")):
        raise FetchError("下载地址无效：%s" % (url or "(空)"))
    dest = os.path.abspath(dest)
    parent = os.path.dirname(dest)
    try:
        os.makedirs(parent, exist_ok=True)
    except OSError as exc:
        raise FetchError("无法创建下载目录：%s" % (exc,))
    tmp = dest + ".part"
    last = None
    for attempt in range(max(0, int(retries)) + 1):
        req = urllib.request.Request(url, headers=_headers())
        opener = _build_opener(insecure=insecure)
        try:
            with opener.open(req, timeout=timeout) as resp:
                total = 0
                try:
                    total = int(resp.headers.get("Content-Length") or 0)
                except (TypeError, ValueError):
                    total = 0
                received = 0
                with open(tmp, "wb") as handle:
                    while True:
                        chunk = resp.read(CHUNK)
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > limit:
                            raise FetchError("文件超过 %d MB，已中止" % (limit // 1024 // 1024))
                        handle.write(chunk)
                        if progress:
                            try:
                                progress(received, total)
                            except Exception:
                                pass
            os.replace(tmp, dest)
            return {"path": dest, "size": os.path.getsize(dest), "url": url}
        except urllib.error.HTTPError as exc:
            last = FetchError(describe_error(exc))
        except urllib.error.URLError as exc:
            last = FetchError(describe_error(exc))
        except socket.timeout:
            last = FetchError("下载超时")
        except (OSError, FetchError) as exc:
            last = exc if isinstance(exc, FetchError) else FetchError("写入文件失败：%s" % (exc,))
        try:
            os.remove(tmp)
        except OSError:
            pass
        if attempt < int(retries):
            time.sleep(0.6 * (attempt + 1))
    raise last or FetchError("下载失败")


def proxy_summary():
    """把当前生效的代理导出给设置页展示（不读取任何凭据，只报地址）。"""
    try:
        proxies = urllib.request.getproxies()
    except Exception:
        return {}
    out = {}
    for key, value in proxies.items():
        if not value:
            continue
        try:
            parsed = urllib.parse.urlsplit(str(value))
            host = parsed.hostname or ""
            port = parsed.port or ""
            out[key] = "%s%s" % (host, (":%d" % port) if port else "")
        except ValueError:
            out[key] = str(value)
    return out
