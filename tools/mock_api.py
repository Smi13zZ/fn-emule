#!/usr/bin/env python3
"""mock_api.py - 按 docs/CONTRACT.md 造数据的假后端，只用于前端联调。

用法（在仓库根目录）：
    python tools/mock_api.py --port 17581
    # 然后浏览器打开 http://127.0.0.1:17581/

它同时把 src/emule/app/web 当静态目录伺服，所以前端改完刷新即可看到效果，
不需要 NAS、不需要 aMule。真实后端由 src/emule/app/server/emulepanel.py 提供。
"""
import argparse
import hashlib
import json
import mimetypes
import os
import random
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "src", "emule", "app", "web")

# RLock: _api() holds the lock for the whole request and the merge helpers below
# take it again — a plain Lock deadlocks the second acquire.
LOCK = threading.RLock()
STATE = {}


def _hash(name, i):
    return hashlib.md5((name + str(i)).encode()).hexdigest().upper()


def _mk(name, size, done_frac, status, speed=0, i=0):
    src_total = random.randint(3, 300)
    return {
        "hash": _hash(name, i),
        "name": name,
        "size": size,
        "done": int(size * done_frac),
        "percent": round(done_frac, 5),
        "speed": speed,
        "eta": int((size - int(size * done_frac)) / speed) if speed else 0,
        "status": status,
        "priority": random.choice(["low", "normal", "high", "auto"]),
        "category": random.choice(["", "电影", "剧集", "软件"]),
        "partfile": status != "complete",
        "added": int(time.time()) - random.randint(600, 864000),
        "sources": {
            "total": src_total,
            "transferring": random.randint(0, 8),
            "asked": random.randint(0, src_total),
            "found": random.randint(0, src_total),
            "a4af": random.randint(0, 5),
        },
        "progress": {"completed": int(size * done_frac)},
        "shared": False,
        "uploading": False,
    }


def seed():
    downloads = [
        _mk("Ubuntu 24.04.1 Desktop amd64.iso", 6_300_000_000, 0.42, "downloading", 1_820_000, 1),
        _mk("[电影] 星际穿越 Interstellar 2014 2160p HDR.mkv", 58_000_000_000, 0.87, "downloading", 3_400_000, 2),
        _mk("Debian 12.7 netinst amd64.iso", 640_000_000, 1.0, "complete", 0, 3),
        _mk("老友记 S01E01-S24 1080p", 12_000_000_000, 0.03, "paused", 0, 4),
        _mk("Kad 测试样本.bin", 2_000_000_000, 0.61, "waiting", 0, 5),
        _mk("libreoffice-24.8.2.msi", 340_000_000, 0.15, "error", 0, 6),
    ]
    uploads = [
        _mk("Debian 12.7 netinst amd64.iso", 640_000_000, 1.0, "complete", 0, 3),
        _mk("Ubuntu 24.04.1 Desktop amd64.iso", 6_300_000_000, 1.0, "complete", 0, 1),
    ]
    for u in uploads:
        # upload rows are live peer sessions: give them upload-ish numbers so the
        # merged task table shows speed / transferred / queue instead of a bar.
        u["uploading"] = True
        u["shared"] = True
        u["status"] = "uploading"
        u["speed"] = random.randint(40_000, 900_000)
        u["uploaded"] = u["done"]
        u["waiting_position"] = 0
        u["queue_rank"] = 0
        u["client"] = {"name": "eMule " + random.choice(["0.70b", "0.60d", "2.3.3"]),
                       "software": "eMule", "version": 70, "mod": "", "ip": "192.168.1.%d" % random.randint(2, 250),
                       "port": random.randint(1024, 65000), "userhash": u["hash"], "score": 0,
                       "upload_state": "uploading", "download_state": "transferring"}
    servers = [
        {"ip": "85.17.116.222", "port": 6082, "name": "ed2k-rust", "desc": "eMule Rust Server", "users": 230000, "maxusers": 500000, "files": 38000000, "priority": "high", "ping": 86, "failed": False, "failed_count": 0},
        {"ip": "176.103.48.36", "port": 2442, "name": "FreeRide", "desc": "FreeRide ED2K", "users": 45000, "maxusers": 150000, "files": 12000000, "priority": "normal", "ping": 210, "failed": False, "failed_count": 0},
        {"ip": "45.82.80.158", "port": 1080, "name": "eMule Security", "desc": "eMule Security No1", "users": 12000, "maxusers": 100000, "files": 5000000, "priority": "normal", "ping": 320, "failed": True, "failed_count": 3},
        {"ip": "91.208.75.178", "port": 4306, "name": "TV Underground", "desc": "TVU", "users": 8000, "maxusers": 200000, "files": 3000000, "priority": "low", "ping": 400, "failed": False, "failed_count": 0},
    ]
    shared = [
        {"hash": downloads[2]["hash"], "name": downloads[2]["name"], "size": 640_000_000, "type": "iso", "priority": "normal", "requests": 12, "accepted": 3, "transferred": 88_000_000, "path": "/var/apps/fn-emule/shares/fn-emule/Incoming/Debian 12.7 netinst amd64.iso"},
        {"hash": downloads[0]["hash"], "name": downloads[0]["name"], "size": 6_300_000_000, "type": "iso", "priority": "normal", "requests": 40, "accepted": 2, "transferred": 1_200_000_000, "path": "/var/apps/fn-emule/shares/fn-emule/Incoming/Ubuntu 24.04.1 Desktop amd64.iso"},
    ]
    history = []
    now = int(time.time())
    for i in range(60, 0, -1):
        history.append({"t": now - i * 3, "down": random.randint(0, 5_000_000), "up": random.randint(0, 800_000)})
    STATE.update({
        "downloads": downloads,
        "uploads": uploads,
        "servers": servers,
        "shared": shared,
        "history": history,
        "started": now,
        "session": {"down": 42_000_000_000, "up": 1_200_000_000},
        "settings": {
            "panel": {"port": 17581, "theme": "auto", "lang": "zh"},
            "engine": {"ec_port": 4712, "ec_password": "x", "tcp_port": 4662, "udp_port": 4672, "nick": "fnOS@eMule",
                       "incoming_dir": "/var/apps/fn-emule/shares/fn-emule/Incoming",
                       "temp_dir": "/var/apps/fn-emule/shares/fn-emule/Temp",
                       "shared_dirs": ["/var/apps/fn-emule/shares/fn-emule/Incoming"],
                       "max_download": 0, "max_upload": 0, "max_connections": 500, "max_sources": 300,
                       "autoconnect": True, "connect_ed2k": True, "connect_kad": True,
                       "add_paused": False, "ich": True, "aich": True, "upnp": False, "ipfilter": True},
            "bootstrap": {"server_met_url": "https://upd.emule-security.org/server.met",
                          "nodes_dat_url": "https://upd.emule-security.org/nodes.dat", "auto_hours": 24, "last_update": int(time.time()) - 3600},
            "notify": {"enabled": True, "channels": [], "events": {"complete": True, "error": True}},
            "backup": {"auto": False, "keep": 7, "last": 0},
            "update": {"repo": "Smi13zZ/fn-emule", "check": True, "last": 0, "latest": ""},
        },
        "search": {},
    })


def tick():
    """让数字每 3 秒动一下，前端曲线才有呼吸感。"""
    now = int(time.time())
    with LOCK:
        down = sum(d["speed"] for d in STATE["downloads"] if d["status"] == "downloading")
        up = random.randint(40_000, 1_400_000) if down else 0
        STATE["history"].append({"t": now, "down": down, "up": up})
        STATE["history"] = STATE["history"][-120:]
        STATE["session"]["down"] += int(down * 3)
        STATE["session"]["up"] += int(up * 3)
        for d in STATE["downloads"]:
            if d["status"] != "downloading":
                continue
            d["speed"] = max(1, int(d["speed"] * random.uniform(0.85, 1.15)))
            d["done"] = min(d["size"], d["done"] + d["speed"] * 3)
            d["percent"] = round(d["done"] / d["size"], 5)
            if d["done"] >= d["size"]:
                d["status"] = "complete"
                d["speed"] = 0


def overview():
    now = int(time.time())
    dl = STATE["downloads"]
    return {
        "engine": {"running": True, "ec": True, "version": "2.3.3", "pid": 12345, "uptime": now - STATE["started"]},
        "ed2k": {"connected": True, "low_id": True, "server": {"name": "ed2k-rust", "ip": "85.17.116.222", "port": 6082}},
        "kad": {"connected": True, "firewalled": True, "nodes": 812, "users": 1_200_000, "files": 45_000_000},
        "speed": {"down": sum(d["speed"] for d in dl if d["status"] == "downloading"),
                  "up": STATE["history"][-1]["up"],
                  "down_limit": STATE["settings"]["engine"]["max_download"],
                  "up_limit": STATE["settings"]["engine"]["max_upload"],
                  "max_down": 10_000_000},
        "session": {"down": STATE["session"]["down"], "up": STATE["session"]["up"], "down_total": 0, "up_total": 0},
        "counters": {
            "downloads": len(dl),
            "downloads_active": sum(1 for d in dl if d["status"] in ("downloading", "waiting")),
            "downloads_paused": sum(1 for d in dl if d["status"] == "paused"),
            "downloads_waiting": sum(1 for d in dl if d["status"] == "waiting"),
            "downloads_complete": sum(1 for d in dl if d["status"] == "complete"),
            "uploads": len(STATE["uploads"]),
            "queue": sum(d["sources"]["asked"] for d in dl) // 3,
            "sources": sum(d["sources"]["total"] for d in dl),
            "connections": 88,
        },
        "disk": {"free": 8_400_000_000_000, "total": 12_000_000_000_000, "path": STATE["settings"]["engine"]["incoming_dir"]},
        "history": STATE["history"][-60:],
    }


def _apply_delete(hashes, delete_data):
    """删除任务：模拟 CONTRACT Â§3.2 的返回形状（results[].kept）。"""
    results = []
    ok_all = True
    for h in hashes:
        hit = None
        for d in STATE["downloads"]:
            if d["hash"] == h:
                hit = d
                break
        if hit is None:
            ok_all = False
            results.append({"hash": h, "ok": False, "error": "下载列表里没有该文件", "kept": ""})
            continue
        STATE["downloads"].remove(hit)
        kept = "" if delete_data else "/var/apps/fn-emule/var/deleted/%s" % h
        results.append({"hash": h, "ok": True, "error": "", "kept": kept})
    return {"ok": ok_all, "action": "delete", "count": len(results), "results": results}


def transfers(kind):
    """"all" merges both sides into the single task table the panel renders."""
    downloads = [dict(d, kind="download") for d in STATE["downloads"]]
    uploads = [dict(u, kind="upload") for u in STATE["uploads"]]
    if kind == "download":
        items = downloads
    elif kind == "upload":
        items = uploads
    else:
        items = downloads + uploads
    with LOCK:
        summary = {
            "count": len(items),
            "downloads": len(downloads),
            "uploads": len(uploads),
            "active": sum(1 for i in items if i["status"] in ("downloading", "waiting")),
            "uploading": sum(1 for i in items if i["status"] == "uploading"),
            "paused": sum(1 for i in items if i["status"] == "paused"),
            "waiting": sum(1 for i in items if i["status"] == "waiting"),
            "complete": sum(1 for i in items if i["status"] == "complete"),
            "down": sum(i["speed"] for i in items if i["status"] == "downloading"),
            "up": sum(i["speed"] for i in items if i["status"] == "uploading"),
        }
        return {"items": items, "summary": summary, "total": len(items)}


def transfer_detail(h):
    for d in STATE["downloads"] + STATE["uploads"]:
        if d["hash"] == h:
            total = max(1, d["size"])
            chunk_size = max(9_728_000, total // 64)
            chunks = []
            start = 0
            done = d["done"]
            while start < total:
                end = min(total, start + chunk_size)
                chunks.append({"start": start, "end": end, "state": "done" if end <= done else ("pending" if start < done else "missing")})
                start = end
            sources = []
            for k in range(min(24, d["sources"]["total"] or 0)):
                sources.append({
                    "ip": "1.2.%d.%d" % (k, random.randint(2, 250)),
                    "port": random.choice([4662, 4661, 5000, 1234]),
                    "client": random.choice(["eMule", "aMule", "eMule Plus", "Shareaza", "MLDonkey"]),
                    "version": random.choice(["0.70b", "2.3.3", "1.2c", "4.1.3"]),
                    "userhash": _hash(d["name"] + str(k), k),
                    "speed": random.choice([0, 0, 12_000, 84_000, 220_000]),
                    "state": random.choice(["downloading", "queue", "connected", "asked"]),
                    "queue_rank": random.randint(0, 9000),
                    "queue_wait": random.randint(0, 7200),
                })
            return {"file": d, "sources": sources, "chunks": chunks}
    return None


SENTINEL = object()


class Handler(BaseHTTPRequestHandler):
    server_version = "emule-mock/1.0"

    def log_message(self, fmt, *args):
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        try:
            return json.loads(self.rfile.read(n).decode() or "{}")
        except Exception:
            return {}

    def _api(self, method, path, qs):
        with LOCK:
            if path == "/api/health":
                return self._json({"ok": True, "version": "26.11.0", "amule": {"running": True, "ec": True}})
            if path == "/api/overview":
                return self._json(overview())
            if path == "/api/transfers":
                return self._json(transfers(qs.get("type", ["all"])[0]))
            if path in ("/api/transfers/add", "/api/transfers/apply"):
                pass  # 具体动作路由在下面按精确路径处理，避免被 {hash} 通配吃掉
            elif path.startswith("/api/transfers/"):
                parts = [p for p in path.split("/") if p]
                h = parts[2].upper()
                if len(parts) >= 4 and parts[3] == "action":
                    body = self._read_json()
                    act = body.get("action")
                    for d in STATE["downloads"]:
                        if d["hash"] == h:
                            if act == "pause":
                                d["status"] = "paused"; d["speed"] = 0
                            elif act == "resume":
                                d["status"] = "downloading"; d["speed"] = 120_000
                            elif act == "priority":
                                d["priority"] = body.get("priority", d["priority"])
                    if act == "delete":
                        return self._json(_apply_delete([h], bool(body.get("delete_data"))))
                    if act == "cancel":
                        return self._json(_apply_delete([h], True))
                    return self._json({"ok": True})
                if len(parts) >= 4 and parts[3] == "curl":
                    return self._json({"ok": True})
                info = transfer_detail(h)
                return self._json(info) if info else self._json({"error": "找不到该任务"}, 404)
            if path == "/api/transfers/add":
                body = self._read_json()
                added = []
                for i, link in enumerate(body.get("links") or []):
                    name = "新增任务 %s" % (link[:20] or i)
                    d = _mk(name, 700_000_000, 0.0, "downloading", 0, len(STATE["downloads"]) + i)
                    STATE["downloads"].append(d)
                    added.append({"hash": d["hash"], "name": d["name"], "ok": True})
                return self._json({"ok": True, "added": added})
            if path == "/api/transfers/apply":
                body = self._read_json()
                act = body.get("action")
                hashes = [str(h).upper() for h in (body.get("hashes") or [])]
                if act in ("delete", "cancel"):
                    return self._json(_apply_delete(hashes, act == "cancel" or bool(body.get("delete_data"))))
                for d in STATE["downloads"]:
                    if d["hash"] in hashes:
                        if act == "pause":
                            d["status"] = "paused"; d["speed"] = 0
                        elif act == "resume":
                            d["status"] = "downloading"; d["speed"] = 90_000
                return self._json({"ok": True})
            if path == "/api/servers":
                cur = STATE["servers"][0]
                return self._json({"items": STATE["servers"],
                                   "current": {"ip": cur["ip"], "port": cur["port"], "name": cur["name"]},
                                   "ed2k_connected": True, "total": len(STATE["servers"]),
                                   "working": sum(1 for s in STATE["servers"] if not s["failed"])})
            if path.startswith("/api/servers/"):
                return self._json({"ok": True, "message": "mock"})
            if path == "/api/kad":
                return self._json({"connected": True, "firewalled": True, "nodes": 812, "users": 1_200_000,
                                   "files": 45_000_000, "bootstrap_ok": True,
                                   "nodes_dat": {"path": "/var/apps/fn-emule/var/amule/nodes.dat", "size": 6574, "mtime": int(time.time()) - 3600}})
            if path == "/api/shared":
                return self._json({"items": STATE["shared"], "total": len(STATE["shared"])})
            if path == "/api/stats":
                rows = [{"group": "传输", "name": "下载速度", "value": "1.82 MB/s"},
                        {"group": "传输", "name": "上传速度", "value": "340 kB/s"},
                        {"group": "网络", "name": "已连接服务器", "value": "ed2k-rust"},
                        {"group": "网络", "name": "Kad 节点", "value": "812"},
                        {"group": "客户端", "name": "排队中", "value": "12"},
                        {"group": "客户端", "name": "已知客户端", "value": "38192"},
                        {"group": "共享", "name": "共享文件数", "value": "2"},
                        {"group": "会话", "name": "本次下载", "value": "42.0 GB"},
                        {"group": "会话", "name": "本次上传", "value": "1.20 GB"}]
                return self._json({"groups": ["传输", "网络", "客户端", "共享", "会话"], "items": rows})
            if path == "/api/log":
                lines = []
                for i in range(40):
                    lines.append({"t": int(time.time()) - (40 - i) * 37, "level": random.choice(["info", "info", "warn", "error"]),
                                  "text": random.choice([
                                      "Connecting to ed2k-rust (85.17.116.222:6082)",
                                      "Connected to ed2k-rust, LowID",
                                      "Kad: Connected, firewalled",
                                      "Downloading Ubuntu 24.04.1 Desktop amd64.iso",
                                      "New source found: 1.2.3.4:4662",
                                      "Server ed2k-rust reported 230000 users",
                                      "Part file saved: 004.part.met",
                                      "Error: connection lost to server"])
                                  })
                return self._json({"items": lines[-int(qs.get("limit", ["200"])[0]):]})
            if path in ("/api/settings",):
                if method == "POST":
                    body = self._read_json()
                    if "settings" in body:
                        STATE["settings"] = body["settings"]
                    return self._json({"ok": True, "settings": STATE["settings"]})
                return self._json({"settings": STATE["settings"]})
            if path == "/api/prefs":
                e = STATE["settings"]["engine"]
                return self._json({"tcp_port": e["tcp_port"], "udp_port": e["udp_port"], "ec_port": e["ec_port"],
                                   "nick": e["nick"], "incoming_dir": e["incoming_dir"], "temp_dir": e["temp_dir"],
                                   "max_download": e["max_download"], "max_upload": e["max_upload"],
                                   "max_connections": e["max_connections"], "max_sources": e["max_sources"]})
            if path.startswith("/api/core/"):
                return self._json({"ok": True, "running": True})
            if path == "/api/notify":
                return self._json({"settings": STATE["settings"]["notify"], "channels": [],
                                   "log": [{"t": int(time.time()) - 600, "event": "complete", "title": "下载完成",
                                            "text": "Debian 12.7 netinst amd64.iso", "ok": True}]})
            if path.startswith("/api/notify/"):
                return self._json({"ok": True})
            if path == "/api/backup/status":
                return self._json({"auto": False, "keep": 7, "last": 0, "items": [{"name": "emule-26.11.0-20261103.tar.gz", "size": 182734, "t": int(time.time()) - 86400}]})
            if path.startswith("/api/backup/"):
                return self._json({"ok": True})
            if path == "/api/update/check":
                return self._json({"available": False, "current": "26.11.0", "latest": "", "url": "", "notes": "", "state": "no_release"})
            if path.startswith("/api/update/"):
                return self._json({"ok": True})
            if path == "/api/search/start":
                sid = _hash(str(time.time()), 1)[:12]
                STATE["search"][sid] = {"started": int(time.time()), "q": (self._read_json().get("q") or "")}
                return self._json({"ok": True, "search_id": sid})
            if path.startswith("/api/search/"):
                parts = [p for p in path.split("/") if p]
                sid = parts[2] if len(parts) > 2 else ""
                if sid not in STATE["search"]:
                    STATE["search"][sid] = {"started": int(time.time()), "q": ""}
                age = int(time.time()) - STATE["search"][sid]["started"]
                n = min(30, 3 + age * 4)
                results = []
                for k in range(n):
                    results.append({"hash": _hash("res" + sid, k), "name": "搜索结果样本 %02d - Linux ISO 镜像.iso" % (k + 1),
                                    "size": random.randint(100_000_000, 9_000_000_000), "sources": random.randint(1, 400),
                                    "type": "iso", "ext": "iso", "percent": round(random.random(), 3),
                                    "already": False})
                return self._json({"search_id": sid, "q": STATE["search"][sid]["q"], "progress": min(100, age * 20),
                                   "done": age > 5, "results": results, "started_at": STATE["search"][sid]["started"]})
            return self._json({"error": "mock 未实现该接口: %s %s" % (method, path)}, 404)

    def _static(self, path):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(WEB, path.lstrip("/")))
        if not full.startswith(WEB) or not os.path.isfile(full):
            return self._json({"error": "not found"}, 404)
        ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
        with open(full, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ""))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path.startswith("/api/"):
            return self._api("GET", u.path, parse_qs(u.query))
        return self._static(u.path)

    def do_POST(self):
        u = urlparse(self.path)
        return self._api("POST", u.path, parse_qs(u.query))

    def do_DELETE(self):
        u = urlparse(self.path)
        return self._api("DELETE", u.path, parse_qs(u.query))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=17581)
    ap.add_argument("--host", default="127.0.0.1")
    args = ap.parse_args()
    seed()

    def loop():
        while True:
            time.sleep(3)
            tick()

    threading.Thread(target=loop, daemon=True).start()
    srv = ThreadingHTTPServer((args.host, args.port), Handler)
    print("mock api on http://%s:%d/  (web dir: %s)" % (args.host, args.port, WEB))
    srv.serve_forever()


if __name__ == "__main__":
    main()
