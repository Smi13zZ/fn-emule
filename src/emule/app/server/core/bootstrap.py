# -*- coding: utf-8 -*-
"""server.met / nodes.dat / ipfilter.dat 下载与校验。

为什么要面板自己下：amuled 自带的 HTTP 下载线程在代理网络下会触发 wxWidgets 断言
直接崩溃（已实测），所以 server.met / nodes.dat 必须由面板下载好放进配置目录，
amule.conf 里 NewVersionCheck=0、aMule 自己永不下网。

约定：
  * urllib 走系统代理环境变量（http_proxy / https_proxy / no_proxy）。
  * 校验失败一律不覆盖旧文件，旧文件继续可用。
  * 写盘是“同目录临时文件 + os.replace”的原子替换。
  * 返回值里带 mtime，方便面板判断是否该更新。
"""

import io
import os
import struct
import urllib.error
import urllib.request
import zipfile

try:
    from .ec import EmuleError
except ImportError:                                    # pragma: no cover - 平铺导入
    from ec import EmuleError


#: server.met 版本标记字节（aMule 另有 MET_HEADER = 0x0E 写法）
SERVER_MET_VERSIONS = (0xE0, 0x0E)
MIN_SERVER_MET_SIZE = 16
MIN_NODES_DAT_SIZE = 100
DEFAULT_TIMEOUT = 25.0
USER_AGENT = "fn-emule/26.11.0 (eMule panel; +https://github.com/Smi13zZ/fn-emule)"

#: ipfilter 候选地址（官方只提供 zip，内部是 guarding.p2p）
DEFAULT_IPFILTER_URLS = [
    "https://upd.emule-security.org/ipfilter.zip",
    "http://upd.emule-security.org/ipfilter.zip",
]

#: 下载失败时的备用地址（第一个失败自动试第二个）
FALLBACK_URLS = {
    "server_met": [
        "https://upd.emule-security.org/server.met",
        "http://upd.emule-security.org/server.met",
        "https://www.gruk.org/server.met.gz",
    ],
    "nodes_dat": [
        "https://upd.emule-security.org/nodes.dat",
        "http://upd.emule-security.org/nodes.dat",
    ],
}


class BootstrapError(EmuleError):
    """下载或校验 server.met / nodes.dat 失败。"""


def _opener():
    # ProxyHandler() 不传参数时会读取 http_proxy/https_proxy/no_proxy 环境变量
    handlers = [urllib.request.ProxyHandler()]
    return urllib.request.build_opener(*handlers)


def http_get(url, timeout=DEFAULT_TIMEOUT, max_bytes=32 * 1024 * 1024):
    """下载 URL，返回 bytes；失败抛 BootstrapError（带中文原因）。"""
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "*/*",
    })
    try:
        with _opener().open(request, timeout=timeout) as response:
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise BootstrapError("下载内容过大（超过 %d 字节）：%s" % (max_bytes, url))
            return data
    except urllib.error.HTTPError as exc:
        raise BootstrapError("下载失败：HTTP %s（%s）" % (exc.code, url))
    except urllib.error.URLError as exc:
        raise BootstrapError("下载失败：%s（%s）" % (getattr(exc, "reason", exc), url))
    except OSError as exc:
        raise BootstrapError("下载失败：%s（%s）" % (exc, url))


def validate_server_met(data):
    """校验 server.met；返回服务器条数。

    真实格式（aMule ServerList.cpp）：uint8 版本（0xE0 或 MET_HEADER 0x0E）
    + uint32 LE 条数 + 每条 [uint32 ip][uint16 port][uint32 tag 数][tags...]。
    """
    if not data:
        raise BootstrapError("server.met 内容为空")
    if len(data) < MIN_SERVER_MET_SIZE:
        raise BootstrapError("server.met 太小（%d 字节），不是有效文件" % len(data))
    head = data[:64].lstrip().lower()
    if head.startswith(b"<") or head.startswith(b"{"):
        raise BootstrapError("server.met 返回的是网页/JSON（被劫持或需要登录），已丢弃")
    if data[0] not in SERVER_MET_VERSIONS:
        raise BootstrapError("server.met 版本标记不是 0xE0/0x0E（实际 0x%02X），已丢弃" % data[0])
    count = struct.unpack("<I", data[1:5])[0]
    if count <= 0 or count > 100000:
        raise BootstrapError("server.met 服务器条目数异常（%d）" % count)
    return count


def validate_nodes_dat(data):
    """校验 nodes.dat；返回节点数。

    真实格式（aMule RoutingZone.cpp ReadFile）：uint32 LE 恒为 0
    + uint32 LE 文件版本（1..3）+ [版本 3 时 uint32 LE bootstrap 版本]
    + uint32 LE 联系人数，每个联系人 25 字节（16 hash + 4 ip + 2 udp + 2 tcp + 1 版本）。
    """
    if not data:
        raise BootstrapError("nodes.dat 内容为空")
    if len(data) <= MIN_NODES_DAT_SIZE:
        raise BootstrapError("nodes.dat 太小（%d 字节），不是有效文件" % len(data))
    head = data[:64].lstrip().lower()
    if head.startswith(b"<") or head.startswith(b"{"):
        raise BootstrapError("nodes.dat 返回的是网页/JSON，已丢弃")
    if len(data) < 8:
        raise BootstrapError("nodes.dat 头部不完整")
    leading = struct.unpack("<I", data[0:4])[0]
    if leading != 0:
        raise BootstrapError("nodes.dat 是旧版（版本 0）格式，aMule 2.3.3 不再支持，已丢弃")
    version = struct.unpack("<I", data[4:8])[0]
    if version < 1 or version > 3:
        raise BootstrapError("nodes.dat 版本号异常（%d），已丢弃" % version)
    offset = 8
    if version == 3 and len(data) >= 12:
        bootstrap_edition = struct.unpack("<I", data[8:12])[0]
        offset = 12
        if bootstrap_edition == 1:
            # 精简版 nodes.dat（只有几十个节点，专门用来引导）
            pass
    if offset + 4 > len(data):
        raise BootstrapError("nodes.dat 缺少联系人数量字段")
    count = struct.unpack("<I", data[offset:offset + 4])[0]
    offset += 4
    if count == 0:
        raise BootstrapError("nodes.dat 不含任何联系人")
    if count * 25 > len(data) - offset:
        raise BootstrapError("nodes.dat 声明 %d 个联系人但数据不足（%d 字节），已丢弃"
                             % (count, len(data) - offset))
    return count


def file_info(path):
    """返回文件状态：{exists,size,mtime,path}。"""
    info = {"exists": False, "size": 0, "mtime": 0, "path": path}
    try:
        stat = os.stat(path)
        info["exists"] = True
        info["size"] = stat.st_size
        info["mtime"] = int(stat.st_mtime)
    except OSError:
        pass
    return info


def _atomic_write(path, data):
    """原子写：同目录 .tmp → os.replace。"""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    tmp = "%s.%d.tmp" % (path, os.getpid())
    with open(tmp, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


def download_to(path, urls, validator, timeout=DEFAULT_TIMEOUT):
    """按顺序尝试多个 URL，校验通过后原子落盘；返回结果字典。

    失败时不碰旧文件，结果里 ok=False + error 中文原因。
    """
    if isinstance(urls, str):
        urls = [urls]
    errors = []
    for url in urls:
        try:
            data = http_get(url, timeout=timeout)
            detail = validator(data)
            _atomic_write(path, data)
            info = file_info(path)
            return {
                "ok": True,
                "url": url,
                "path": path,
                "size": info["size"],
                "mtime": info["mtime"],
                "detail": detail,
                "error": "",
            }
        except BootstrapError as exc:
            errors.append(str(exc))
        except OSError as exc:
            errors.append("写入 %s 失败：%s" % (path, exc))
    return {
        "ok": False,
        "url": urls[0] if urls else "",
        "path": path,
        "size": 0,
        "mtime": 0,
        "detail": 0,
        "error": "；".join(errors) or "下载失败",
    }


def download_server_met(config_dir, url=None, timeout=DEFAULT_TIMEOUT):
    """下载 server.met 到配置目录。"""
    urls = [url] if url else []
    urls += [candidate for candidate in FALLBACK_URLS["server_met"] if candidate not in urls]
    return download_to(os.path.join(config_dir, "server.met"), urls,
                       validate_server_met, timeout=timeout)


def download_nodes_dat(config_dir, url=None, timeout=DEFAULT_TIMEOUT):
    """下载 nodes.dat 到配置目录。"""
    urls = [url] if url else []
    urls += [candidate for candidate in FALLBACK_URLS["nodes_dat"] if candidate not in urls]
    return download_to(os.path.join(config_dir, "nodes.dat"), urls,
                       validate_nodes_dat, timeout=timeout)


def has_ipfilter_range(data):
    """内容里是否至少有一条 "起始IP,结束IP,级别" 记录。

    允许很长的注释头（官方 guarding.p2p 前几十行都是注释），所以在前面 1MB 里找。
    """
    sample = (data or b"")[:1024 * 1024].decode("latin-1", "replace")
    for line in sample.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or stripped.startswith("//"):
            continue
        parts = [part.strip() for part in stripped.split(",")]
        if len(parts) >= 3 and parts[0] and parts[0][0].isdigit() and \
                (parts[1][:1].isdigit() or parts[1].count(".") == 3):
            return True
    return False


def ipfilter_usable(config_dir):
    """现有 ipfilter.dat 是否真的有过滤条目（aMule 启动时会写一个 182 字节的空壳）。"""
    path = os.path.join(config_dir, "ipfilter.dat")
    try:
        with open(path, "rb") as handle:
            return has_ipfilter_range(handle.read(1024 * 1024))
    except OSError:
        return False


def download_ipfilter(config_dir, url=None, timeout=DEFAULT_TIMEOUT):
    """下载 ipfilter 并落成明文 ipfilter.dat。

    官方只提供 ipfilter.zip（内含 guarding.p2p），所以这里用标准库 zipfile 就地解包，
    校验是纯文本的 "start,end,level" 再原子写盘；失败不影响主流程。
    """

    def _plain_text(data):
        if not data or len(data) < 256:
            raise BootstrapError("ipfilter 内容太小（%d 字节）" % len(data or b""))
        head = data[:64].lstrip().lower()
        if head.startswith(b"<") or head.startswith(b"{"):
            raise BootstrapError("ipfilter 返回的是网页/JSON，已丢弃")
        # 允许很长的注释头（官方 guarding.p2p 前面几十行都是注释），
        # 所以在前 1MB 里找第一行数据 "起始IP,结束IP,级别" 来判定格式。
        sample = data[:1024 * 1024].decode("latin-1", "replace")
        for line in sample.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("//"):
                continue
            parts = [part.strip() for part in stripped.split(",")]
            if len(parts) >= 3 and parts[0] and parts[0][0].isdigit() and                     (parts[1][0].isdigit() or parts[1].count(".") == 3):
                return len(data)
        raise BootstrapError("ipfilter 内容不是 ipfilter.dat 文本格式，已丢弃")

    urls = [url] if url else list(DEFAULT_IPFILTER_URLS)
    errors = []
    for candidate in urls:
        try:
            data = http_get(candidate, timeout=timeout, max_bytes=64 * 1024 * 1024)
            if data[:2] == b"PK":
                with zipfile.ZipFile(io.BytesIO(data)) as archive:
                    names = [name for name in archive.namelist()
                             if not name.endswith("/")]
                    names.sort(key=lambda name: (not name.lower().endswith(
                        (".dat", ".p2p", ".txt")), name))
                    if not names:
                        raise BootstrapError("ipfilter.zip 里没有可用文件")
                    data = archive.read(names[0])
            size = _plain_text(data)
            target = os.path.join(config_dir, "ipfilter.dat")
            _atomic_write(target, data)
            info = file_info(target)
            return {"ok": True, "url": candidate, "path": target, "size": info["size"],
                    "mtime": info["mtime"], "detail": size, "error": ""}
        except (BootstrapError, zipfile.BadZipFile, OSError) as exc:
            errors.append(str(exc))
    return {"ok": False, "url": urls[0] if urls else "", "path":
            os.path.join(config_dir, "ipfilter.dat"), "size": 0, "mtime": 0, "detail": 0,
            "error": "；".join(errors) or "下载失败"}


def ensure_files(config_dir, settings=None, force_server_met=True,
                 force_nodes_dat=True, timeout=DEFAULT_TIMEOUT):
    """首次准备：缺文件才下载（force_* 为 False 时只补缺失）。"""
    result = {"server_met": None, "nodes_dat": None}
    server_met = os.path.join(config_dir, "server.met")
    nodes_dat = os.path.join(config_dir, "nodes.dat")
    server_exists = file_info(server_met)["exists"]
    nodes_exists = file_info(nodes_dat)["exists"]
    if force_server_met or not server_exists:
        result["server_met"] = download_server_met(
            config_dir, (settings or {}).get("server_met_url"), timeout=timeout)
    if force_nodes_dat or not nodes_exists:
        result["nodes_dat"] = download_nodes_dat(
            config_dir, (settings or {}).get("nodes_dat_url"), timeout=timeout)
    return result


def server_met_count(config_dir):
    """配置目录里 server.met 的服务器条数（文件不存在或损坏返回 0）。

    aMule 退出时会用内存里的列表覆盖 server.met；如果它启动时读不到服务器，
    就会写回一个 0 条的 server.met，所以面板必须按“条数”判断是否需要重下。
    """
    path = os.path.join(config_dir, "server.met")
    try:
        with open(path, "rb") as handle:
            return validate_server_met(handle.read())
    except (OSError, BootstrapError):
        return 0


def nodes_dat_count(config_dir):
    """配置目录里 nodes.dat 的联系人数（文件不存在或损坏返回 0）。"""
    path = os.path.join(config_dir, "nodes.dat")
    try:
        with open(path, "rb") as handle:
            return validate_nodes_dat(handle.read())
    except (OSError, BootstrapError):
        return 0


def artifact_status(config_dir):
    """当前配置目录里的 bootstrap 文件状态（含可用条数）。"""
    server_met = file_info(os.path.join(config_dir, "server.met"))
    server_met["count"] = server_met_count(config_dir) if server_met["exists"] else 0
    nodes_dat = file_info(os.path.join(config_dir, "nodes.dat"))
    nodes_dat["count"] = nodes_dat_count(config_dir) if nodes_dat["exists"] else 0
    ipfilter = file_info(os.path.join(config_dir, "ipfilter.dat"))
    ipfilter["usable"] = ipfilter_usable(config_dir) if ipfilter["exists"] else False
    return {
        "server_met": server_met,
        "nodes_dat": nodes_dat,
        "ipfilter": ipfilter,
    }


# ---------------------------------------------------------------- server.met 解析

#: eD2k 文件 tag 类型（src/include/tags/TagTypes.h）
TAGTYPE_HASH16 = 0x01
TAGTYPE_STRING = 0x02
TAGTYPE_UINT32 = 0x03
TAGTYPE_FLOAT32 = 0x04
TAGTYPE_BOOL = 0x05
TAGTYPE_BOOLARRAY = 0x06
TAGTYPE_BLOB = 0x07
TAGTYPE_UINT16 = 0x08
TAGTYPE_UINT8 = 0x09
TAGTYPE_BSOB = 0x0A
TAGTYPE_UINT64 = 0x0B
TAGTYPE_STR1 = 0x11

#: 服务器 tag 的短名字 id（eMule Server.h ST_*）
ST_SERVERNAME = 0x01
ST_DESCRIPTION = 0x0B
ST_PING = 0x0C
ST_FAIL = 0x0D
ST_PREFERENCE = 0x0E
ST_DYNIP = 0x0F
ST_MAXUSERS = 0x20
ST_VERSION = 0x91
ST_LASTPING = 0x90

#: 短 id → 字段名
_SERVER_TAG_IDS = {
    ST_SERVERNAME: "name",
    ST_DESCRIPTION: "desc",
    ST_PING: "ping",
    ST_FAIL: "failed",
    ST_PREFERENCE: "preference",
    ST_DYNIP: "dynip",
    ST_MAXUSERS: "maxusers",
    ST_VERSION: "version",
    ST_LASTPING: "lastping",
}

#: 长名字 → 字段名
_SERVER_TAG_NAMES = {
    "name": "name",
    "description": "desc",
    "desc": "desc",
    "ping": "ping",
    "failed": "failed",
    "fail": "failed",
    "preference": "preference",
    "prio": "preference",
    "dynip": "dynip",
    "maxusers": "maxusers",
    "users": "users",
    "files": "files",
    "version": "version",
    "lastping": "lastping",
    "softlimit": "softlimit",
    "hardlimit": "hardlimit",
}


def _read_ed2k_tag(data, offset):
    """读一个 eD2k 文件 tag，返回 (字段名, 值, 新偏移)。

    布局（aMule SafeFile.cpp CFileDataIO::WriteTag / Tag.cpp CTag 构造）：
      u8 type（bit7 表示 type & 0x7F 且紧跟 1 字节短名字 id）
      u16 LE 名字长度（为 1 时后面是 1 字节短 id，否则是名字字符串）
      值：string → u16 LE 长度 + 字节；uint32 → 4 字节 LE；……
    """
    total = len(data)
    tag_type = data[offset]
    offset += 1
    short_type = bool(tag_type & 0x80)
    if short_type:
        tag_type &= 0x7F
    name = ""
    name_id = None
    if short_type or offset + 2 > total:
        name_id = data[offset]
        offset += 1
    else:
        name_len = struct.unpack("<H", data[offset:offset + 2])[0]
        offset += 2
        if name_len == 1:
            name_id = data[offset]
            offset += 1
        else:
            name = data[offset:offset + name_len].decode("latin-1", "replace")
            offset += name_len
    field = _SERVER_TAG_IDS.get(name_id) if name_id is not None else None
    field = field or _SERVER_TAG_NAMES.get(name.lower(), "")

    value = None
    if tag_type == TAGTYPE_STRING:
        if offset + 2 > total:
            raise BootstrapError("server.met tag 字符串长度缺失")
        length = struct.unpack("<H", data[offset:offset + 2])[0]
        offset += 2
        raw = data[offset:offset + length]
        offset += length
        if raw.startswith(b"\xef\xbb\xbf"):
            raw = raw[3:]
        value = raw.decode("utf-8", "replace")
    elif tag_type in (TAGTYPE_UINT32, TAGTYPE_FLOAT32):
        value = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4
    elif tag_type == TAGTYPE_UINT64:
        value = struct.unpack("<Q", data[offset:offset + 8])[0]
        offset += 8
    elif tag_type == TAGTYPE_UINT16:
        value = struct.unpack("<H", data[offset:offset + 2])[0]
        offset += 2
    elif tag_type == TAGTYPE_UINT8:
        value = data[offset]
        offset += 1
    elif tag_type == TAGTYPE_BOOL:
        value = data[offset] != 0
        offset += 1
    elif tag_type == TAGTYPE_HASH16:
        value = data[offset:offset + 16].hex().upper()
        offset += 16
    elif tag_type == TAGTYPE_BOOLARRAY:
        length = struct.unpack("<H", data[offset:offset + 2])[0]
        offset += 2 + (length // 8) + 1
        value = length
    elif tag_type == TAGTYPE_BLOB:
        length = struct.unpack("<I", data[offset:offset + 4])[0]
        offset += 4 + length
        value = length
    elif tag_type == TAGTYPE_BSOB:
        value = data[offset]
        offset += 1
    elif TAGTYPE_STR1 <= tag_type <= TAGTYPE_STR1 + 21:
        length = tag_type - TAGTYPE_STR1 + 1
        value = data[offset:offset + length].decode("utf-8", "replace")
        offset += length
    else:
        raise BootstrapError("server.met 里出现未知 tag 类型 0x%02X" % tag_type)
    return field, value, offset


def parse_server_met(data):
    """解析 server.met → [{"ip","port","name","desc","users","maxusers","files",...}]。"""
    count = validate_server_met(data)
    servers = []
    offset = 5
    total = len(data)
    for _ in range(count):
        if offset + 10 > total:
            break
        ip_raw = struct.unpack("<I", data[offset:offset + 4])[0]
        port = struct.unpack("<H", data[offset + 4:offset + 6])[0]
        tag_count = struct.unpack("<I", data[offset + 6:offset + 10])[0]
        offset += 10
        record = {
            # eD2k 的 ip 是“反主机序”：低字节是第一段
            "ip": "%d.%d.%d.%d" % (ip_raw & 0xFF, (ip_raw >> 8) & 0xFF,
                                   (ip_raw >> 16) & 0xFF, (ip_raw >> 24) & 0xFF),
            "port": port,
            "name": "",
            "desc": "",
            "users": 0,
            "maxusers": 0,
            "files": 0,
            "version": "",
            "ping": 0,
            "failed": 0,
            "preference": 0,
        }
        for _tag in range(min(tag_count, 64)):
            if offset >= total:
                break
            try:
                field, value, offset = _read_ed2k_tag(data, offset)
            except (BootstrapError, struct.error, IndexError):
                offset = total
                break
            if not field or value is None:
                continue
            if field in ("name", "desc") and not record[field] and isinstance(value, str):
                record[field] = value
            elif field in ("users", "maxusers", "files", "ping", "failed", "preference") \
                    and isinstance(value, int):
                if not record[field]:
                    record[field] = value
            elif field == "version" and isinstance(value, str) and not record["version"]:
                record["version"] = value
        if record["port"]:
            servers.append(record)
    return servers


def load_server_met(config_dir):
    """读取并解析配置目录里的 server.met。"""
    path = os.path.join(config_dir, "server.met")
    try:
        with open(path, "rb") as handle:
            return parse_server_met(handle.read())
    except (OSError, BootstrapError):
        return []

