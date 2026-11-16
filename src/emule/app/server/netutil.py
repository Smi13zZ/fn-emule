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
import http.client
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
    """抓取失败。

    消息是中文，用作拿不到 code 时的回退文本；code 是语言中立的失败标识，
    界面优先用它翻译 —— 后端只塞中文句子的话，英文界面会冒出中文。
    """

    def __init__(self, message="", code=""):
        Exception.__init__(self, message)
        self.code = str(code or "")


#: 网络层失败 → 用户能照着做点什么的那个原因。
#: 顺序有意义：socket.gaierror 是 OSError 的子类，通用判断必须排在最后。
def error_code(exc, seen=None):
    """把一个异常翻译成界面能翻译的码；认不出来返回空串。

    urllib 会把真实原因包在 URLError.reason 里（有时还套两层），所以这里递归
    拆壳 —— 不拆的话「DNS 解析失败」在界面上永远显示成一句泛泛的网络错误。
    """
    if isinstance(exc, FetchError):
        return exc.code
    if seen is None:
        seen = set()
    if id(exc) in seen:
        return ""
    seen.add(id(exc))
    if isinstance(exc, urllib.error.HTTPError):
        code = int(getattr(exc, "code", 0) or 0)
        if code in (403, 429):
            return "gh403"
        if code == 404:
            return "gh404"
        return ""
    if isinstance(exc, urllib.error.URLError):
        inner = getattr(exc, "reason", None)
        return error_code(inner, seen) if inner is not None else ""
    if isinstance(exc, ssl.SSLError):
        return "netTls"
    if isinstance(exc, socket.gaierror):
        return "netDns"
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "netTimeout"
    if isinstance(exc, ConnectionRefusedError):
        return "netRefused"
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "netReset"
    if isinstance(exc, http.client.IncompleteRead):
        return "netReset"
    return ""


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
    if isinstance(exc, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
        return "连接被中断，请重试"
    if isinstance(exc, http.client.RemoteDisconnected):
        return "连接被中断，请重试"
    if isinstance(exc, http.client.IncompleteRead):
        return "连接被中断，请重试"
    return str(exc) or exc.__class__.__name__


def fetch_error(exc):
    """同一个失败同时给出中文原因和语言中立码，两件事一次算完。

    分成两处各自判断会出现「码说 DNS、文字说超时」这种自相矛盾。
    """
    if isinstance(exc, FetchError):
        return exc
    return FetchError(describe_error(exc), error_code(exc))


def _http_status_error(status):
    """HTTP 状态码 → 带码的 FetchError（403/429 是限流，404 是资源不存在）。"""
    status = int(status or 0)
    if status in (403, 429):
        return FetchError("HTTP %d（接口被限流或拒绝访问）" % status, "gh403")
    if status == 404:
        return FetchError("HTTP 404（资源不存在）", "gh404")
    return FetchError("HTTP %d（服务器返回错误）" % status)


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


def _resolve_family(url, family=0):
    """预解析主机名，把请求固定到 IPv4 或 IPv6。

    family: 0=系统默认（双栈） 4=只要 A 记录 6=只要 AAAA 记录。
    用途：诊断页要分别拿到 v4/v6 公网地址，urllib 自己的 Happy Eyeballs
    总是挑系统偏好的那一条，所以这里显式钉住地址族。
    解析失败返回 None（调用方回落默认行为，不报错）。
    """
    if family not in (4, 6):
        return None
    try:
        host = urllib.parse.urlsplit(str(url)).hostname or ""
    except ValueError:
        return None
    if not host:
        return None
    want = socket.AF_INET if family == 4 else socket.AF_INET6
    try:
        infos = socket.getaddrinfo(host, None, family=want, type=socket.SOCK_STREAM)
    except OSError:
        return None
    if not infos:
        return None
    return infos[0][4][0]




def _pinned_request(url, method="GET", headers=None, data=None, timeout=DEFAULT_TIMEOUT,
                    insecure=False, family=4):
    """把 TCP 连接钉在指定地址族（4/6），URL 仍用原域名做 SNI 与 Host。

    代理环境（DNS 返回 fake-ip）下，按域名建连会被劫持到假地址导致证书校验失败；
    这个函数先在本地解析出真实 A/AAAA 记录，直接对真实 IP 建连，再用原域名完成
    TLS 握手与 HTTP 请求。仅用于诊断页的公网 IP 探测，别拿它做通用抓取。
    返回 (状态码, 解码后的文本)；失败抛 FetchError。
    """
    parts = urllib.parse.urlsplit(str(url))
    target_host = parts.hostname or ""
    if not target_host:
        raise FetchError("地址无效：%s" % (url or "(空)"))
    port = parts.port or (443 if parts.scheme == "https" else 80)
    want = socket.AF_INET if family == 4 else socket.AF_INET6
    addr = None
    try:
        infos = socket.getaddrinfo(target_host, port, family=family, type=socket.SOCK_STREAM)
        for info in infos:
            if info[0] == want:
                addr = info[4][0]
                break
    except OSError as exc:
        # 某些 DNS（fake-ip 代理）对按族查询会回 EAI_FAMILY，回退全族查询再过滤
        try:
            infos = socket.getaddrinfo(target_host, port, family=0, type=socket.SOCK_STREAM)
        except OSError as exc2:
            raise FetchError("解析 %s (IPv%d) 失败：%s" % (target_host, family, exc2),
                             "netDns")
        for info in infos:
            if info[0] == want:
                addr = info[4][0]
                break
    if not addr:
        raise FetchError("解析 %s (IPv%d) 没有可用地址（设备或网络可能没有 IPv6）"
                         % (target_host, family), "netDns")
    try:
        sock = socket.create_connection((addr, port), timeout=timeout)
    except OSError as exc:
        raise FetchError("连接 %s:%d 失败：%s" % (addr, port, exc), error_code(exc))
    try:
        if parts.scheme == "https":
            context = _ssl_context(insecure)
            if context is None:
                context = ssl.create_default_context()
            try:
                sock = context.wrap_socket(sock, server_hostname=target_host)
            except ssl.SSLError as exc:
                raise FetchError("HTTPS 握手失败：%s" % (exc,), "netTls")
        method_u = (method or ("POST" if data else "GET")).upper()
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        head = {"Host": parts.netloc, "User-Agent": user_agent(),
                "Accept": "*/*", "Accept-Encoding": "identity", "Connection": "close"}
        head.update(headers or {})
        payload = data if isinstance(data, bytes) else (data.encode() if data else None)
        blob = ("%s %s HTTP/1.1\r\n" % (method_u, path) +
                "".join("%s: %s\r\n" % (k, v) for k, v in head.items()) + "\r\n").encode("latin-1")
        if payload:
            blob += payload
        try:
            sock.sendall(blob)
        except OSError as exc:
            raise FetchError("发送请求失败：%s" % (exc,), error_code(exc))
        chunks = []
        while True:
            try:
                piece = sock.recv(65536)
            except socket.timeout:
                raise FetchError("请求超时", "netTimeout")
            if not piece:
                break
            chunks.append(piece)
        raw = b"".join(chunks)
    finally:
        try:
            sock.close()
        except OSError:
            pass
    sep = raw.find(b"\r\n\r\n")
    head_part = raw[:sep] if sep >= 0 else raw
    body_part = raw[sep + 4:] if sep >= 0 else b""
    status_line = head_part.split(b"\r\n", 1)[0].decode("latin-1", "replace")
    try:
        status = int(status_line.split(" ")[1])
    except (IndexError, ValueError):
        status = 0
    if status >= 400:
        raise _http_status_error(status)
    charset = "utf-8"
    for line in head_part.split(b"\r\n"):
        if line.lower().startswith(b"content-type:"):
            if b"charset=" in line:
                charset = line.split(b"charset=")[1].split(b";")[0].decode("latin-1", "replace").strip()
            break
    text = body_part.decode(charset or "utf-8", "replace")
    return status, text


def open_url(url, timeout=DEFAULT_TIMEOUT, headers=None, data=None, method=None,
             insecure=False, proxy=None, family=0):
    """一次请求，返回 (状态码, 解码后的文本)。网络层错误抛 FetchError。

    说明：family 钉死的请求走 _pinned_request（get_text 内部分流），open_url 不处理它。
    """
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
        raise fetch_error(exc)
    except urllib.error.URLError as exc:
        raise fetch_error(exc)
    except socket.timeout:
        raise FetchError("请求超时", "netTimeout")
    except (ssl.SSLError, ValueError) as exc:
        raise fetch_error(exc)


def get_text(url, timeout=DEFAULT_TIMEOUT, headers=None, retries=DEFAULT_RETRIES,
             accept=None, insecure=False, family=0):
    """取文本。retries 只针对网络层失败重试；HTTP 4xx 不重试（重试也没用）。

    family 传 4/6 时强制地址族（诊断页探测公网 IPv4/IPv6 用）。
    """
    extra = dict(headers or {})
    if accept:
        extra.setdefault("Accept", accept)
    last = None
    for attempt in range(max(0, int(retries)) + 1):
        try:
            if family in (4, 6):
                status, text = _pinned_request(url, headers=extra, timeout=timeout,
                                               insecure=insecure, family=family)
            else:
                status, text = open_url(url, timeout=timeout, headers=extra, insecure=insecure)
            if status and status >= 400:
                raise _http_status_error(status)
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
        raise FetchError("返回内容不是合法 JSON：%s" % (exc,), "checkFailed")


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
                        raise FetchError("文件超过 %d MB，已中止" % (limit // 1024 // 1024),
                                         "pkgTooBig")
                return bytes(blob)
        except urllib.error.HTTPError as exc:
            raise fetch_error(exc)
        except urllib.error.URLError as exc:
            last = fetch_error(exc)
        except socket.timeout:
            last = FetchError("请求超时", "netTimeout")
        except OSError as exc:
            last = FetchError("读取失败：%s" % (exc,), error_code(exc))
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
        raise FetchError("无法创建下载目录：%s" % (exc,), "noDir")
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
                            raise FetchError("文件超过 %d MB，已中止" % (limit // 1024 // 1024),
                                             "pkgTooBig")
                        handle.write(chunk)
                        if progress:
                            try:
                                progress(received, total)
                            except Exception:
                                pass
                # 服务器给了长度就必须收满。连接中途断掉时 read() 只是返回空，
                # 循环正常退出，半截文件于是被原子改名成"完整"的包 —— 后面
                # 只能靠解压失败才暴露，用户看到的原因也成了"包坏了"而不是
                # "网络断了"。这里先对账，字节不够就当场报网络错误。
                if total and received != total:
                    raise FetchError("下载不完整：收到 %d 字节，应为 %d"
                                     % (received, total), "netReset")
            os.replace(tmp, dest)
            return {"path": dest, "size": os.path.getsize(dest), "url": url}
        except urllib.error.HTTPError as exc:
            last = fetch_error(exc)
        except urllib.error.URLError as exc:
            last = fetch_error(exc)
        except socket.timeout:
            last = FetchError("下载超时", "netTimeout")
        except FetchError as exc:
            last = exc
        except OSError as exc:
            # 这里的 OSError 有两个来源，不能一律说成「写入文件失败」：
            # 对端断开连接（RemoteDisconnected / ConnectionReset）也是 OSError，
            # 把它说成磁盘问题会把用户引到完全错误的方向。
            code = error_code(exc)
            if code in ("netReset", "netRefused", "netTimeout", "netDns", "netTls"):
                last = FetchError(describe_error(exc), code)
            else:
                last = FetchError("写入文件失败：%s" % (exc,), code)
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
