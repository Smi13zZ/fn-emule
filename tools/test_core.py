#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""EC 协议 + 引擎门面的真机自测脚本（可重复跑）。

用法：
    python3 tools/test_core.py --config /tmp/ec-test/var/amule --json
    python3 tools/test_core.py --config /tmp/ec-test/var/amule --password test123
    python3 tools/test_core.py --config ... --dump       # 打印关键 opcode 的原始 tag 树
    python3 tools/test_core.py --config ... --no-start    # 引擎已在跑，只做读写测试
    python3 tools/test_core.py --config ... --keep        # 测完不停引擎

脚本自己构造 settings dict（CONTRACT §5 结构），不依赖 panel-api 的 settings.json；
必要时会把 var/settings.json 里的同名键合并进来。
"""

import argparse
import json
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)
# 依次尝试：仓库内路径 → 平铺目录（/tmp/ec-test/core）→ 打包后布局（<APPDEST>/app/server/core）
_CORE_CANDIDATES = [
    os.path.join(REPO_ROOT, "src", "emule", "app", "server", "core"),
    os.path.join(REPO_ROOT, "core"),
    os.path.join(REPO_ROOT, "target", "app", "server", "core"),
    os.path.join(REPO_ROOT, "app", "server", "core"),
]
CORE_DIR = next((path for path in _CORE_CANDIDATES if os.path.isdir(path)),
                _CORE_CANDIDATES[0])
if CORE_DIR not in sys.path:
    sys.path.insert(0, CORE_DIR)

import ec as ecmod                      # noqa: E402
import bootstrap as bootstrapmod        # noqa: E402
from service import EmuleService        # noqa: E402


#: 自测用的合法 ed2k 链接（随机哈希，不会有真实来源，只验证流程）
TEST_LINK = ("ed2k://|file|fn-emule-selftest.bin|1048576|"
             "0123456789ABCDEF0123456789ABCDEF|/")
TEST_MAGNET = ("magnet:?xt=urn:ed2k:fedcba9876543210fedcba9876543210"
               "&dn=fn-emule-magnet.bin&xl=2097152")
TEST_LINK_HASH = "0123456789ABCDEF0123456789ABCDEF"
TEST_MAGNET_HASH = "FEDCBA9876543210FEDCBA9876543210"


def build_settings(var_dir, password, ports=(4662, 4672, 4712)):
    """按 CONTRACT §5 结构造一份自测设置。"""
    incoming = os.path.join(os.path.dirname(var_dir), "shares", "fn-emule", "Incoming")
    temp = os.path.join(os.path.dirname(var_dir), "shares", "fn-emule", "Temp")
    settings = {
        "panel": {"port": 17581, "theme": "auto", "lang": "zh"},
        "engine": {
            "ec_port": ports[2],
            "ec_password": password,
            "tcp_port": ports[0],
            "udp_port": ports[1],
            "nick": "fnOS@eMule-selftest",
            "incoming_dir": incoming,
            "temp_dir": temp,
            "shared_dirs": [incoming],
            "max_download": 0, "max_upload": 0,
            "max_connections": 500, "max_sources": 300,
            "autoconnect": True, "connect_ed2k": True, "connect_kad": True,
            "add_paused": False, "ich": True, "aich": True,
            "upnp": False, "ipfilter": True,
        },
        "bootstrap": {
            "server_met_url": "https://upd.emule-security.org/server.met",
            "nodes_dat_url": "https://upd.emule-security.org/nodes.dat",
            "auto_hours": 24, "last_update": 0,
        },
        "notify": {"enabled": False, "channels": [], "events": {"complete": True, "error": True}},
        "backup": {"auto": False, "keep": 7, "last": 0},
        "update": {"repo": "Smi13zZ/fn-emule", "check": True, "last": 0, "latest": ""},
    }
    settings_path = os.path.join(var_dir, "settings.json")
    if os.path.isfile(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as handle:
                stored = json.load(handle)
            for section in ("engine", "bootstrap"):
                if isinstance(stored.get(section), dict):
                    settings[section].update(stored[section])
        except (OSError, ValueError):
            pass
    return settings


def _guess_runtime_dir(repo_root):
    """猜测内置 amuled 运行时目录（仓库/打包两种布局 + EMULE_APP_HOME）。"""
    candidates = []
    app_home = os.environ.get("EMULE_APP_HOME") or os.environ.get("TRIM_APPDEST")
    if app_home:
        candidates += [os.path.join(app_home, "app", "runtime"),
                       os.path.join(app_home, "runtime")]
    candidates += [
        os.path.join(repo_root, "src", "emule", "app", "runtime"),
        os.path.join(repo_root, "target", "app", "runtime"),
        os.path.join(repo_root, "app", "runtime"),
    ]
    for path in candidates:
        if os.path.isdir(path):
            return os.path.abspath(path)
    return os.path.abspath(candidates[0])


class Runner(object):
    def __init__(self, as_json=False):
        self.checks = []
        self.as_json = as_json
        self.started = time.time()

    def log(self, message):
        if not self.as_json:
            sys.stderr.write("%s\n" % message)
            sys.stderr.flush()

    def run(self, name, func, validate=None, note=""):
        started = time.time()
        entry = {"name": name, "ok": False, "ms": 0, "note": note}
        try:
            result = func()
            entry["result"] = result
            if validate is not None:
                problem = validate(result)
                if problem:
                    entry["error"] = problem
                else:
                    entry["ok"] = True
            else:
                entry["ok"] = True
        except Exception as exc:                       # noqa: BLE001 - 自测脚本要收集全部失败
            entry["error"] = "%s: %s" % (type(exc).__name__, exc)
            entry["traceback"] = traceback.format_exc(limit=4)
        entry["ms"] = int((time.time() - started) * 1000)
        self.checks.append(entry)
        if not self.as_json:
            mark = "OK  " if entry["ok"] else "FAIL"
            detail = entry.get("error") or _summary_of(entry.get("result"))
            sys.stderr.write("[%s] %-28s %5dms  %s\n" % (mark, name, entry["ms"], detail))
            sys.stderr.flush()
        return entry

    def payload(self, extra=None):
        total = len(self.checks)
        passed = sum(1 for entry in self.checks if entry["ok"])
        payload = {
            "ok": passed == total and total > 0,
            "passed": passed,
            "total": total,
            "checks": self.checks,
            "elapsed_ms": int((time.time() - self.started) * 1000),
        }
        if extra:
            payload.update(extra)
        return payload


def _summary_of(result):
    """给人类读的一行摘要。"""
    if result is None:
        return ""
    if isinstance(result, list):
        return "%d 条" % len(result)
    if isinstance(result, dict):
        for key in ("total", "count", "items", "results", "running", "connected", "ok"):
            if key in result:
                value = result[key]
                if isinstance(value, list):
                    return "%s=%d" % (key, len(value))
                return "%s=%s" % (key, value)
        return ",".join(list(result.keys())[:6])
    return str(result)[:120]


# ---------------------------------------------------------------- 校验器

def need_dict(keys=()):
    def validate(result):
        if not isinstance(result, dict):
            return "返回值不是 dict：%r" % (result,)
        for key in keys:
            if key not in result:
                return "缺少字段 %s" % key
        return ""
    return validate


def need_nonempty_dict(keys=()):
    def validate(result):
        problem = need_dict(keys)(result)
        if problem:
            return problem
        return ""
    return validate


def check_overview(result):
    if not isinstance(result, dict):
        return "overview 不是 dict"
    for key in ("engine", "ed2k", "kad", "speed", "session", "counters", "disk"):
        if key not in result:
            return "overview 缺少 %s" % key
    if not result["engine"].get("running"):
        return "overview.engine.running 为 False"
    if not result["engine"].get("ec"):
        return "overview.engine.ec 为 False（EC 没连上）"
    return ""


def check_transfers(kind, minimum=0):
    def validate(result):
        if not isinstance(result, dict):
            return "transfers 不是 dict"
        for key in ("items", "summary", "total"):
            if key not in result:
                return "transfers 缺少 %s" % key
        if result["total"] < minimum:
            return "%s 列表只有 %d 条，期望至少 %d 条" % (kind, result["total"], minimum)
        return ""
    return validate


def check_servers(result):
    if not isinstance(result, dict):
        return "servers 不是 dict"
    for key in ("items", "current", "ed2k_connected", "total", "working"):
        if key not in result:
            return "servers 缺少 %s" % key
    if result["total"] <= 0:
        return "服务器列表为空（server.met 没导入？）"
    entry = result["items"][0]
    for key in ("ip", "port", "name", "users", "priority", "failed"):
        if key not in entry:
            return "服务器条目缺少 %s" % key
    return ""


def check_kad(result):
    if not isinstance(result, dict):
        return "kad 不是 dict"
    for key in ("connected", "firewalled", "nodes", "users", "files", "bootstrap"):
        if key not in result:
            return "kad 缺少 %s" % key
    if not result["bootstrap"]["nodes_dat"]["exists"]:
        return "配置目录里没有 nodes.dat"
    return ""


def check_shared(result):
    if not isinstance(result, dict) or "items" not in result:
        return "shared 不是 dict 或缺少 items"
    return ""


def check_stats(result):
    if not isinstance(result, dict) or "items" not in result:
        return "stats 不是 dict 或缺少 items"
    if not result["items"]:
        return "统计树为空"
    bad = [entry for entry in result["items"] if "group" not in entry or "name" not in entry
           or "value" not in entry]
    if bad:
        return "统计项字段不完整：%r" % (bad[0],)
    return ""


def check_logs(result):
    if not isinstance(result, list):
        return "logs 不是 list"
    if not result:
        return "日志为空"
    entry = result[0]
    for key in ("t", "level", "text"):
        if key not in entry:
            return "日志行缺少字段 %s" % key
    return ""


def check_prefs(result):
    if not isinstance(result, dict):
        return "prefs 不是 dict"
    for key in ("tcp_port", "udp_port", "incoming_dir", "max_download"):
        if key not in result:
            return "prefs 缺少 %s" % key
    return ""


def check_links(result):
    if not isinstance(result, list) or not result:
        return "add_links 没有返回结果"
    bad = [entry for entry in result if not entry.get("ok")]
    if bad:
        return "有链接添加失败：%s" % bad[0].get("error")
    return ""


# ---------------------------------------------------------------- 主流程

def dump_raw(service, password, port):
    """打印关键 opcode 的原始 tag 树，便于对照协议。"""
    client = ecmod.ECClient(port=port, password=password)
    client.connect()

    def show(packet, indent=0):
        pad = "  " * indent
        for tag in packet.children:
            name = ecmod.TAG_NAMES.get(tag.name, hex(tag.name))
            if tag.type == ecmod.TagType.STRING:
                value = repr(tag.text())
            elif tag.type == ecmod.TagType.HASH16:
                value = tag.hexhash()
            elif tag.type == ecmod.TagType.IPV4:
                value = str(tag.ip())
            elif tag.type == ecmod.TagType.CUSTOM and not tag.data:
                value = "<empty>"
            elif tag.type == ecmod.TagType.CUSTOM:
                value = "raw:%s" % tag.data[:24].hex()
            else:
                value = tag.int()
            print("%s%s type=%d %s" % (pad, name, tag.type, value))
            if tag.children:
                show(tag, indent + 1)

    requests = [
        ("GET_CONNSTATE", ecmod.Op.GET_CONNSTATE, None),
        ("STAT_REQ", ecmod.Op.STAT_REQ, None),
        ("GET_SERVER_LIST", ecmod.Op.GET_SERVER_LIST, None),
        ("GET_DLOAD_QUEUE", ecmod.Op.GET_DLOAD_QUEUE, None),
        ("GET_PREFERENCES", ecmod.Op.GET_PREFERENCES,
         [ecmod.tag_uint(ecmod.Tag.SELECT_PREFS, ecmod.Prefs.ALL_USED)]),
    ]
    for name, opcode, nodes in requests:
        print("\n=== %s (0x%02X) ===" % (name, opcode))
        packet = client.request(opcode, nodes or [])
        print("reply opcode=0x%02X (%s)" % (packet.opcode,
                                            ecmod.OP_NAMES.get(packet.opcode, "?")))
        show(packet)
    print("\n=== GET_STATSTREE ===")
    packet = client.request(ecmod.Op.GET_STATSTREE)
    print("reply opcode=0x%02X，顶层子 tag %d 个" % (packet.opcode, len(packet.children)))
    for node in packet.children:
        if node.name == ecmod.Tag.STATTREE_NODE:
            _dump_stat_node(node, 0)
    print("\n=== GET_LOG ===")
    packet = client.request(ecmod.Op.GET_LOG)
    lines = [tag.text() for tag in packet.all(ecmod.Tag.STRING)]
    print("日志 %d 字符，最后 5 行：\n%s" % (sum(len(line) for line in lines),
                                            "\n".join(lines[0].splitlines()[-5:])))
    client.close()


def _dump_stat_node(node, depth):
    pad = "  " * depth
    values = ["%s(type=%d)" % (ecmod.stat_value_text(tag), ecmod.stat_value_type(tag))
              for tag in node.all(ecmod.Tag.STAT_NODE_VALUE)]
    print("%s%s %s" % (pad, node.text(), " ".join(values)))
    for child in node.all(ecmod.Tag.STATTREE_NODE):
        _dump_stat_node(child, depth + 1)


def main(argv=None):
    parser = argparse.ArgumentParser(description="fn-emule 引擎层真机自测")
    parser.add_argument("--config", required=True, help="aMule 配置目录（如 /tmp/ec-test/var/amule）")
    parser.add_argument("--var", default="", help="面板 var 目录，默认取 --config 的上一级")
    parser.add_argument("--runtime", default="", help="运行时目录（含 usr/bin/amuled），默认用仓库内的")
    parser.add_argument("--password", default="test123", help="EC 明文口令（默认 test123）")
    parser.add_argument("--tcp-port", type=int, default=4662)
    parser.add_argument("--udp-port", type=int, default=4672)
    parser.add_argument("--ec-port", type=int, default=4712)
    parser.add_argument("--json", action="store_true", help="只输出 JSON")
    parser.add_argument("--no-start", action="store_true", help="不启动引擎（已在运行时用）")
    parser.add_argument("--keep", action="store_true", help="测完不停止引擎")
    parser.add_argument("--skip-search", action="store_true", help="跳过搜索测试")
    parser.add_argument("--search-wait", type=float, default=12.0, help="搜索最长等待秒数")
    parser.add_argument("--dump", action="store_true", help="打印原始 EC 包内容后退出")
    parser.add_argument("--with-network", action="store_true",
                        help="额外测试 servers_update / kad_bootstrap（需要外网）")
    args = parser.parse_args(argv)

    config_dir = os.path.abspath(args.config)
    var_dir = os.path.abspath(args.var or os.path.dirname(config_dir.rstrip("/")))
    runtime_dir = os.path.abspath(args.runtime) if args.runtime else \
        _guess_runtime_dir(REPO_ROOT)

    settings = build_settings(var_dir, args.password,
                              (args.tcp_port, args.udp_port, args.ec_port))
    service = EmuleService(lambda: settings, var_dir=var_dir, config_dir=config_dir,
                           runtime_dir=runtime_dir)

    if args.dump:
        service.prepare()
        if not args.no_start:
            service.start()
        dump_raw(service, args.password, args.ec_port)
        return 0

    runner = Runner(as_json=args.json)
    extra = {
        "config_dir": config_dir,
        "var_dir": var_dir,
        "runtime_dir": runtime_dir,
        "ec_port": args.ec_port,
    }
    runner.log("== fn-emule 引擎层自测 ==")
    runner.log("config=%s" % config_dir)
    runner.log("var=%s" % var_dir)

    runner.run("prepare", service.prepare, note="建目录 + 生成 amule.conf + bootstrap")

    if not args.no_start:
        runner.run("start", service.start, note="启动 amuled 并等 EC 就绪")
    runner.run("process_status", service.process_status, need_dict(("running", "pid", "ec", "uptime")))
    runner.run("overview", service.overview, check_overview)
    runner.run("transfers(download)", lambda: service.transfers("download"),
               check_transfers("download"))
    runner.run("transfers(upload)", lambda: service.transfers("upload"),
               check_transfers("upload"))
    runner.run("servers", service.servers, check_servers)
    runner.run("kad_status", service.kad_status, check_kad)
    runner.run("shared", service.shared, check_shared)

    # ---- 造一个共享文件，验证扫描 + 列表（也顺手验证 reload） ----
    def shared_with_file():
        incoming = settings["engine"]["incoming_dir"]
        os.makedirs(incoming, exist_ok=True)
        path = os.path.join(incoming, "fn-emule-selftest-shared.bin")
        if not os.path.exists(path):
            with open(path, "wb") as handle:
                handle.write(b"fn-emule self test shared payload\n" * 4096)
        service.shared_reload()
        deadline = time.time() + 15
        listing = {"items": [], "total": 0}
        while time.time() < deadline:
            listing = service.shared()
            if listing["total"] > 0:
                break
            time.sleep(1.0)
        if listing["total"] <= 0:
            return {"total": 0, "warning": "共享目录扫描 15 秒内没有结果"}
        first = listing["items"][0]
        for key in ("hash", "name", "size", "path", "ed2k_link"):
            if key not in first:
                raise RuntimeError("共享条目缺少字段 %s" % key)
        return {"total": listing["total"], "first": first}

    runner.run("shared_reload", shared_with_file,
               lambda result: "" if result.get("total", 0) > 0 else result.get("warning")
               or "共享列表仍为空")
    runner.run("stats", service.stats, check_stats)
    runner.run("logs", lambda: service.logs(50), check_logs)
    runner.run("prefs", service.prefs, check_prefs)

    # ---- 偏好写回（把当前昵称原样写回，验证 SET_PREFERENCES 通路） ----
    def apply_prefs():
        current = service.prefs()
        patch = {"nick": current.get("nick") or "fnOS@eMule"}
        result = service.apply_prefs(patch)
        again = service.prefs()
        return {"patch": patch, "applied": result.get("applied"),
                "nick_after": again.get("nick")}

    runner.run("apply_prefs", apply_prefs, need_dict(("applied", "nick_after")))

    if args.with_network:
        runner.run("servers_update", service.servers_update,
                   lambda result: "" if result.get("ok") else "servers_update 未成功")
        runner.run("kad_bootstrap", service.kad_bootstrap,
                   lambda result: "" if result.get("ok") else "kad_bootstrap 未成功")

    # ---- 链接归一化（纯函数，不需要引擎） ----
    def normalize():
        first = EmuleService.normalize_link(TEST_LINK)
        second = EmuleService.normalize_link(TEST_MAGNET)
        if first["hash"] != TEST_LINK_HASH:
            raise RuntimeError("ed2k 归一化哈希不对：%s" % first["hash"])
        if second["hash"] != TEST_MAGNET_HASH:
            raise RuntimeError("magnet 归一化哈希不对：%s" % second["hash"])
        return {"ed2k": first, "magnet": second}

    runner.run("normalize_link", normalize, need_dict(("ed2k", "magnet")))

    # ---- 添加下载任务 ----
    added = runner.run("add_links", lambda: service.add_links(
        [TEST_LINK, TEST_MAGNET], category="", paused=False), check_links)
    hashes = []
    if added.get("ok"):
        hashes = [entry["hash"] for entry in added["result"] if entry.get("ok")]

    def find_task():
        listing = service.transfers("download")
        found = [item for item in listing["items"] if item["hash"] in hashes]
        if not found:
            raise RuntimeError("添加后下载列表里看不到新任务（列表 %d 条）" % listing["total"])
        return {"item": found[0], "total": listing["total"],
                "status": found[0]["status"], "percent": found[0]["percent"]}

    seen = runner.run("transfers.see_new_task", find_task,
                      lambda result: "" if result.get("total") else "列表为空")

    # ---- 详情（分块图 + 来源） ----
    if hashes:
        runner.run("transfer_detail", lambda: service.transfer_detail(hashes[0]),
                   lambda result: "" if isinstance(result, dict) and "chunks" in result
                   and "sources" in result and "file" in result else "详情字段不完整")

    # ---- 暂停 / 恢复 / 优先级 ----
    def status_of(file_hash):
        for item in service.transfers("download")["items"]:
            if item["hash"] == file_hash:
                return item["status"]
        return "missing"

    def pause_resume():
        if not hashes:
            raise RuntimeError("没有可操作的任务")
        target = hashes[0]
        service.transfer_action(target, "pause")
        paused = status_of(target)
        service.transfer_action(target, "resume")
        resumed = status_of(target)
        service.transfer_action(target, "priority", priority="high")
        item = [entry for entry in service.transfers("download")["items"]
                if entry["hash"] == target][0]
        if paused != "paused":
            raise RuntimeError("pause 后状态是 %s，期望 paused" % paused)
        if item["priority"] != "high":
            raise RuntimeError("设置优先级后是 %s，期望 high" % item["priority"])
        return {"paused_status": paused, "resumed_status": resumed,
                "priority": item["priority"]}

    runner.run("transfer_action(pause/resume/priority)", pause_resume, need_dict(("paused_status",)))

    # ---- 批量操作 ----
    if hashes:
        def batch():
            result = service.transfer_apply(hashes, "pause")
            statuses = {entry["hash"]: status_of(entry["hash"]) for entry in result["results"]}
            resumed = service.transfer_apply(hashes, "resume")
            return {"paused": statuses, "resumed_ok": resumed["ok"]}
        runner.run("transfer_apply(批量暂停/恢复)", batch, need_dict(("paused", "resumed_ok")))

    # ---- 错误分支 ----
    def bad_hash():
        try:
            service.transfer_action("F" * 32, "pause")
        except ecmod.EmuleError as exc:
            return {"raised": True, "message": str(exc)}
        raise RuntimeError("对不存在的哈希操作居然没报错")

    runner.run("error.bad_hash", bad_hash, need_dict(("raised",)))

    def bad_search_id():
        try:
            service.search_state("no-such-search")
        except ecmod.EmuleError as exc:
            return {"raised": True, "message": str(exc)}
        raise RuntimeError("不存在的搜索会话居然没报错")

    runner.run("error.bad_search", bad_search_id, need_dict(("raised",)))

    # ---- 搜索 ----
    def ensure_ed2k():
        info = service.overview()
        if info["ed2k"]["connected"]:
            return {"connected": True, "server": info["ed2k"]["server"], "waited": 0}
        listing = service.servers()
        if not listing["items"]:
            return {"connected": False, "server": {}, "waited": 0}
        first = listing["items"][0]
        service.server_connect(first["ip"], first["port"])
        deadline = time.time() + 20
        while time.time() < deadline:
            state = service.overview()["ed2k"]
            if state["connected"]:
                return {"connected": True, "server": state["server"],
                        "waited": int(20 - (deadline - time.time()))}
            time.sleep(1.0)
        return {"connected": False, "server": {}, "waited": 20}

    if not args.skip_search:
        connected = runner.run("ed2k_connect", ensure_ed2k, need_dict(("connected",)))

        def start_search():
            errors = []
            for kind in ("server", "kad"):
                try:
                    return {"kind": kind, "payload": service.search_start("debian", kind, "name")}
                except ecmod.EmuleError as exc:
                    errors.append("%s: %s" % (kind, exc))
            return {"kind": "", "payload": {}, "errors": errors,
                    "degraded": "无法搜索（网络未连接）：%s" % "；".join(errors)}

        started = runner.run("search_start", start_search,
                             lambda result: "" if result.get("payload") or result.get("degraded")
                             else "既没有 search_id 也没有降级说明")
        search_result = started.get("result") or {}
        search_id = (search_result.get("payload") or {}).get("search_id", "")
        if not search_id:
            runner.log("!! 搜索被跳过：%s" % (search_result.get("degraded") or "未知原因"))

        def poll():
            if not search_id:
                return {"progress": 0, "done": True, "results": 0,
                        "history": [], "degraded": "网络未连接，未执行搜索"}
            deadline = time.time() + args.search_wait
            progress_history = []
            last = None
            while time.time() < deadline:
                last = service.search_state(search_id)
                progress_history.append(last["progress"])
                if last["done"]:
                    break
                time.sleep(1.0)
            if last is None:
                raise RuntimeError("一次都没拿到搜索状态")
            return {"progress": last["progress"], "done": last["done"],
                    "results": len(last["results"]), "history": progress_history[:12]}

        runner.run("search_state", poll, need_dict(("progress", "done")))
        runner.run("search_stop",
                   lambda: service.search_stop(search_id) if search_id
                   else {"search_id": "", "done": True, "degraded": "网络未连接，未执行搜索"},
                   need_dict(("done",)))

    # ---- 清理测试任务 ----
    if hashes:
        def cancel():
            results = []
            for file_hash in hashes:
                try:
                    results.append(service.transfer_action(file_hash, "cancel"))
                except ecmod.EmuleError as exc:
                    results.append({"hash": file_hash, "ok": False, "error": str(exc)})
            remaining = [item["hash"] for item in service.transfers("download")["items"]
                         if item["hash"] in hashes]
            return {"cancelled": len(results), "still_there": remaining}
        runner.run("cancel_test_tasks", cancel, need_dict(("cancelled",)))

    if not args.no_start and not args.keep:
        runner.run("stop", service.stop, note="SIGTERM 优雅停止")

    payload = runner.payload(extra)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print("\n== 结果：%d/%d 通过，用时 %dms ==" % (payload["passed"], payload["total"],
                                                     payload["elapsed_ms"]))
        for entry in payload["checks"]:
            if entry["ok"]:
                print(" - %-34s %s" % (entry["name"], _summary_of(entry.get("result"))))
        for entry in payload["checks"]:
            if not entry["ok"]:
                print(" - %s: %s" % (entry["name"], entry.get("error")))
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
