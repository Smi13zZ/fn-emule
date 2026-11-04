#!/usr/bin/env python3
"""smoke_test.py - 装好之后跑一遍验收：HTTP API + 静态页 + 引擎状态 + 一次真实的加任务/取消

在设备上直接跑（不在面板进程里跑）：

    python3 /tmp/emule-smoke.py --base http://127.0.0.1:17581

退出码 0 表示全绿；任何一项失败都会打印原因并以 1 退出。
"""
import argparse
import json
import sys
import time
import urllib.error
import urllib.request

RESULTS = []

# 一条真实存在的 eD2k 链接（Debian 的 netinst，测试用；加失败也算失败，但取消随时可做）
TEST_LINK = ("ed2k://|file|debian-12.7.0-amd64-netinst.iso|659554304|"
             "9F1D0F8A2A5A1B0F5C1E2F0B7C4D3E2A|/")

def check(name, fn, required=True):
    try:
        detail = fn()
        RESULTS.append({"name": name, "ok": True, "detail": detail})
        print("  PASS  %-26s %s" % (name, str(detail)[:110]))
    except Exception as e:  # noqa: BLE001
        RESULTS.append({"name": name, "ok": False, "detail": str(e), "required": required})
        print("  FAIL  %-26s %s" % (name, str(e)[:300]))
        if required:
            RESULTS.append({"name": "__abort__", "ok": False, "detail": "required check failed"})


class Client:
    def __init__(self, base):
        self.base = base.rstrip("/")

    def req(self, path, method="GET", body=None, timeout=20):
        url = self.base + path
        data = None
        headers = {"Accept": "application/json"}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        rq = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(rq, timeout=timeout) as r:
                raw = r.read()
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype:
                    return r.status, json.loads(raw.decode("utf-8", "replace") or "null")
                return r.status, raw
        except urllib.error.HTTPError as e:
            raw = e.read()
            try:
                return e.code, json.loads(raw.decode("utf-8", "replace") or "null")
            except Exception:
                return e.code, raw
        except Exception as e:  # noqa: BLE001
            raise RuntimeError("请求失败 %s: %s" % (path, e))

    def json(self, path, method="GET", body=None, expect=200):
        st, data = self.req(path, method, body)
        if st != expect:
            raise RuntimeError("%s %s -> HTTP %s %s" % (method, path, st, str(data)[:200]))
        if not isinstance(data, dict) and not isinstance(data, list):
            raise RuntimeError("%s %s 返回的不是 JSON: %r" % (method, path, str(data)[:120]))
        return data


def need(obj, *keys):
    missing = [k for k in keys if k not in obj]
    if missing:
        raise RuntimeError("缺字段: %s（实际键: %s）" % (",".join(missing), ",".join(list(obj)[:20])))
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:17581")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    c = Client(args.base)
    print("== eMule 面板验收 @ %s ==" % args.base)

    health = {}

    def f_health():
        d = c.json("/api/health")
        need(d, "ok", "version", "amule")
        health.update(d)
        if not d.get("ok"):
            raise RuntimeError("health.ok=false")
        if not (d.get("amule") or {}).get("running"):
            raise RuntimeError("引擎未运行: %s" % json.dumps(d.get("amule"), ensure_ascii=False)[:200])
        return "v%s aMule=%s ec=%s" % (d.get("version"), (d.get("amule") or {}).get("running"),
                                       (d.get("amule") or {}).get("ec"))

    check("health", f_health)

    def f_overview():
        d = c.json("/api/overview")
        need(d, "engine", "ed2k", "kad", "speed", "session", "counters", "disk", "history")
        need(d["engine"], "running", "ec")
        need(d["speed"], "down", "up")
        if not isinstance(d["history"], list):
            raise RuntimeError("history 不是数组")
        return "ed2k=%s kad=%s nodes=%s down=%s up=%s" % (
            d["ed2k"].get("connected"), d["kad"].get("connected"), d["kad"].get("nodes"),
            d["speed"].get("down"), d["speed"].get("up"))

    check("overview", f_overview)
    check("engine 进程", lambda: _engine(c))
    check("下载列表", lambda: _transfers(c, "download"))
    check("上传列表", lambda: _transfers(c, "upload"))
    check("服务器列表", lambda: _servers(c))
    check("Kad 状态", lambda: _kad(c))
    check("共享文件", lambda: _shared(c))
    check("统计", lambda: _stats(c))
    check("日志", lambda: _logs(c))
    check("设置读取", lambda: _settings_get(c))
    check("偏好读取", lambda: _prefs(c))
    check("通知配置", lambda: _notify(c))
    check("备份状态", lambda: _backup(c))
    check("更新检查", lambda: _update(c))
    check("静态首页", lambda: _static(c))
    check("前端资源", lambda: _static_assets(c))

    added = {}

    def f_add():
        d = c.json("/api/transfers/add", "POST", {"links": [TEST_LINK]})
        need(d, "added")
        ok = [x for x in d["added"] if x.get("ok")]
        if not ok:
            raise RuntimeError("加任务失败: %s" % json.dumps(d, ensure_ascii=False)[:300])
        added.update(ok[0])
        return "hash=%s name=%s" % (ok[0].get("hash", "")[:12], ok[0].get("name", "")[:40])

    check("添加 ed2k 任务", f_add)

    def f_seen():
        if not added.get("hash"):
            raise RuntimeError("没有上一步的 hash，跳过")
        time.sleep(1.5)
        d = c.json("/api/transfers?type=download")
        hit = [i for i in d.get("items", []) if (i.get("hash") or "").upper() == added["hash"].upper()]
        if not hit:
            raise RuntimeError("任务列表里找不到刚加的任务")
        it = hit[0]
        need(it, "name", "size", "percent", "status", "sources")
        return "%s %s%% %s" % (it["name"][:36], round(it["percent"] * 100, 2), it["status"])

    check("任务出现在列表", f_seen)

    def f_detail():
        if not added.get("hash"):
            raise RuntimeError("没有 hash")
        d = c.json("/api/transfers/" + added["hash"])
        need(d, "file", "sources", "chunks")
        return "sources=%d chunks=%d" % (len(d["sources"]), len(d["chunks"]))

    check("任务详情", f_detail)

    def f_action():
        if not added.get("hash"):
            raise RuntimeError("没有 hash")
        c.json("/api/transfers/%s/action" % added["hash"], "POST", {"action": "pause"})
        time.sleep(0.6)
        d = c.json("/api/transfers?type=download")
        hit = [i for i in d.get("items", []) if (i.get("hash") or "").upper() == added["hash"].upper()]
        if hit and hit[0].get("status") not in ("paused",):
            raise RuntimeError("暂停没生效，状态=%s" % hit[0].get("status"))
        return "paused ok"

    check("暂停任务", f_action)

    def f_delete():
        if not added.get("hash"):
            raise RuntimeError("没有 hash")
        r = c.json("/api/transfers/%s/action" % added["hash"], "POST",
                   {"action": "delete", "delete_data": True})
        need(r, "results")
        if not (r.get("results") or [{}])[0].get("ok"):
            raise RuntimeError("删除失败：%s" % ((r.get("results") or [{}])[0].get("error"),))
        time.sleep(1.0)
        d = c.json("/api/transfers?type=download")
        if [i for i in d.get("items", []) if (i.get("hash") or "").upper() == added["hash"].upper()]:
            raise RuntimeError("删除后任务还在列表里")
        return "deleted ok"

    check("删除任务(清理)", f_delete, required=False)

    def f_search():
        d = c.json("/api/search/start", "POST", {"q": "debian", "kind": "server", "method": "name"})
        need(d, "search_id")
        sid = d["search_id"]
        last = None
        for _ in range(12):
            time.sleep(1.0)
            st = c.json("/api/search/" + str(sid))
            need(st, "progress", "done", "results")
            last = st
            if st.get("done"):
                break
        c.json("/api/search/%s/stop" % sid, "POST", {})
        return "progress=%s results=%d" % (last.get("progress"), len(last.get("results", [])))

    check("eD2k 搜索", f_search, required=False)

    def f_stats_zh():
        d = c.json("/api/stats")
        items = d.get("items") or []
        if not items:
            raise RuntimeError("统计为空")
        bad = [i for i in items if "%s" in (i.get("name") or "")]
        if bad:
            raise RuntimeError("统计名里还有 %%s：%s" % bad[0].get("name"))
        zh = [i for i in items if i.get("name_zh")]
        ratio = len(zh) / float(len(items))
        if ratio < 0.8:
            raise RuntimeError("name_zh 覆盖率过低 %.0f%%（要求 >=80%%）" % (ratio * 100))
        if not [i for i in items if i.get("group_zh")]:
            raise RuntimeError("缺少 group_zh")
        return "%d 项，中文覆盖 %d%%" % (len(items), round(ratio * 100))

    check("统计中文化", f_stats_zh)

    def f_diag():
        d = c.json("/api/diagnostics")
        need(d, "summary", "engine", "host", "ports", "checks", "suggestions")
        need(d["summary"], "grade", "high_id", "kad_open", "title")
        if d["summary"]["grade"] not in ("ok", "warn", "error"):
            raise RuntimeError("grade 非法：%s" % d["summary"]["grade"])
        ids = [x.get("id") for x in d["checks"]]
        for need_id in ("engine", "ed2k_connect", "high_id", "kad", "tcp_listen",
                        "udp_bind", "firewall", "public_ip", "cgnat", "inbound"):
            if need_id not in ids:
                raise RuntimeError("checks 缺少 %s（实际：%s）" % (need_id, ",".join(ids)))
        for x in d["checks"]:
            if x.get("level") not in ("ok", "warn", "error"):
                raise RuntimeError("check %s level 非法：%s" % (x.get("id"), x.get("level")))
        return "grade=%s high_id=%s kad_open=%s checks=%d" % (
            d["summary"]["grade"], d["summary"]["high_id"], d["summary"]["kad_open"], len(d["checks"]))

    check("网络诊断", f_diag)

    def f_notify_types():
        d = c.json("/api/notify")
        types = d.get("types") or []
        need_names = ("bark", "serverchan", "pushplus", "wxpusher", "telegram", "wecom", "dingtalk", "slack", "webhook")
        got = [x.get("type") for x in types]
        missing = [x for x in need_names if x not in got]
        if missing:
            raise RuntimeError("缺少渠道类型：%s" % ",".join(missing))
        for x in types:
            if not (x.get("label_zh") or x.get("label")):
                raise RuntimeError("渠道 %s 没有可读名称" % x.get("type"))
        return "%d 种渠道" % len(types)

    check("通知渠道元数据", f_notify_types)

    if args.json:
        print(json.dumps(RESULTS, ensure_ascii=False, indent=2))
    bad = [r for r in RESULTS if not r["ok"] and r.get("required", True)]
    print("== %d 项检查，失败 %d 项 ==" % (len([r for r in RESULTS if r["name"] != "__abort__"]), len(bad)))
    return 1 if bad else 0


def _engine(c):
    d = c.json("/api/core/status")
    if not d.get("running"):
        raise RuntimeError("引擎进程未运行")
    return "pid=%s ec=%s" % (d.get("pid"), d.get("ec"))


def _transfers(c, kind):
    d = c.json("/api/transfers?type=" + kind)
    need(d, "items", "summary", "total")
    need(d["summary"], "count", "active", "paused", "waiting", "complete", "down", "up")
    return "%d 项 / 活动 %s" % (len(d["items"]), d["summary"]["active"])


def _servers(c):
    d = c.json("/api/servers")
    need(d, "items", "current", "ed2k_connected")
    if d["items"]:
        need(d["items"][0], "ip", "port", "name", "priority")
    return "%d 台 / 当前 %s" % (len(d["items"]), (d.get("current") or {}).get("name") or "-")


def _kad(c):
    d = c.json("/api/kad")
    need(d, "connected", "firewalled", "nodes")
    return "connected=%s nodes=%s" % (d["connected"], d["nodes"])


def _shared(c):
    d = c.json("/api/shared")
    need(d, "items", "total")
    return "%d 个共享文件" % len(d["items"])


def _stats(c):
    d = c.json("/api/stats")
    need(d, "items")
    if not isinstance(d["items"], list):
        raise RuntimeError("stats.items 不是数组")
    return "%d 行" % len(d["items"])


def _logs(c):
    d = c.json("/api/log?limit=50")
    need(d, "items")
    return "%d 行日志" % len(d["items"])


def _settings_get(c):
    d = c.json("/api/settings")
    need(d, "settings")
    s = d["settings"]
    need(s, "panel", "engine", "notify")
    return "port=%s tcp=%s" % (s["panel"].get("port"), s["engine"].get("tcp_port"))


def _prefs(c):
    d = c.json("/api/prefs")
    need(d, "tcp_port", "udp_port", "incoming_dir")
    return "tcp=%s udp=%s" % (d["tcp_port"], d["udp_port"])


def _notify(c):
    d = c.json("/api/notify")
    need(d, "settings")
    return "enabled=%s" % (d["settings"] or {}).get("enabled")


def _backup(c):
    d = c.json("/api/backup/status")
    need(d, "items")
    return "%d 份备份" % len(d["items"])


def _update(c):
    d = c.json("/api/update/check")
    need(d, "available", "current", "state")
    return "state=%s current=%s" % (d.get("state"), d.get("current"))


def _static(c):
    st, raw = c.req("/")
    if st != 200:
        raise RuntimeError("首页 HTTP %s" % st)
    text = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
    if "emule" not in text.lower():
        raise RuntimeError("首页里没有 eMule 字样（可能被别的服务占了端口）")
    return "%d bytes" % len(text)


def _static_assets(c):
    for path in ("/style.css", "/js/app.js", "/js/i18n.js", "/lib/vue.global.prod.js"):
        st, raw = c.req(path)
        if st != 200 or len(raw or b"") < 500:
            raise RuntimeError("%s -> HTTP %s (%d bytes)" % (path, st, len(raw or b"")))
    return "4 个资源文件正常"


if __name__ == "__main__":
    sys.exit(main())
