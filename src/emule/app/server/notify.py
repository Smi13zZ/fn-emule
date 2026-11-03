#!/usr/bin/env python3
"""fn-emule : 通知通道。

每个通道都是一个小适配器，把 (title, body) 变成一次 HTTP 请求；只用标准库，
和面板其余部分保持一致。

从 qbpanel 的 notify.py 迁移而来，字段与行为保持兼容：
* 老通道（Bark / Server 酱 / PushPlus / WxPusher / 自定义 Webhook）的
  CHANNEL_TYPES 键名、config 字段名、SECRET_MARK 语义一字未改，
  老用户的通知配置直接搬过来就能发。
* 新增 Telegram / 企业微信机器人 / 钉钉机器人 / Slack 四个通道。

密钥处理：SECRET_FIELDS 里的字段永远不回传浏览器。公开视图把已保存的密钥换成
字面量 SECRET_MARK，而保存时提交 SECRET_MARK（或空串）表示「保持原值」。
"""
import base64
import hashlib
import hmac
import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

SECRET_MARK = "__SET__"

# type -> (label_zh, label_en, secret field names, field order)
CHANNEL_TYPES = {
    "bark": {
        "label_zh": "Bark",
        "label_en": "Bark",
        "secrets": ("key",),
        "fields": ("server", "key"),
    },
    "serverchan": {
        "label_zh": "Server 酱",
        "label_en": "ServerChan",
        "secrets": ("sendkey",),
        "fields": ("sendkey",),
    },
    "pushplus": {
        "label_zh": "PushPlus",
        "label_en": "PushPlus",
        "secrets": ("token",),
        "fields": ("token",),
    },
    "wxpusher": {
        "label_zh": "WxPusher",
        "label_en": "WxPusher",
        "secrets": ("app_token",),
        "fields": ("app_token", "uids", "topics"),
    },
    "telegram": {
        "label_zh": "Telegram",
        "label_en": "Telegram",
        "secrets": ("bot_token",),
        "fields": ("bot_token", "chat_id", "api_base"),
    },
    "wecom": {
        "label_zh": "企业微信机器人",
        "label_en": "WeCom bot",
        "secrets": ("key",),
        "fields": ("key",),
    },
    "dingtalk": {
        "label_zh": "钉钉机器人",
        "label_en": "DingTalk bot",
        "secrets": ("url", "secret"),
        "fields": ("url", "secret"),
    },
    "slack": {
        "label_zh": "Slack",
        "label_en": "Slack",
        "secrets": ("url",),
        "fields": ("url",),
    },
    "webhook": {
        "label_zh": "自定义 Webhook",
        "label_en": "Custom webhook",
        "secrets": ("headers",),
        "fields": ("url", "headers"),
    },
}

DEFAULT_TIMEOUT = 8
SOURCE_NAME = "fn-emule"


def type_list(lang="zh"):
    """GET /api/notify 的 types 字段：给前端渲染「添加通道」下拉用。"""
    out = []
    for key, meta in CHANNEL_TYPES.items():
        out.append({
            "type": key,
            "label": meta["label_zh"] if lang != "en" else meta["label_en"],
            "label_zh": meta["label_zh"],
            "label_en": meta["label_en"],
            "fields": list(meta["fields"]),
            "secrets": list(meta["secrets"]),
        })
    return out


def channel_public(ch):
    """Channel shape for the browser - stored secrets are replaced by a mark."""
    meta = CHANNEL_TYPES.get(ch.get("type") or "", {"secrets": (), "fields": ()})
    cfg = ch.get("config") or {}
    out = {}
    for key in meta["fields"]:
        val = cfg.get(key)
        if key in meta["secrets"]:
            out[key] = SECRET_MARK if val else ""
        else:
            out[key] = val if val is not None else ""
    return {
        "id": ch.get("id") or "",
        "name": ch.get("name") or "",
        "type": ch.get("type") or "",
        "enabled": bool(ch.get("enabled", True)),
        "config": out,
        "fields": list(meta["fields"]),
        "secrets": list(meta["secrets"]),
    }


def merge_config(ch_type, incoming, existing):
    """Keep stored secrets when the form echoes the mark or leaves the field blank."""
    meta = CHANNEL_TYPES.get(ch_type or "", {"secrets": (), "fields": ()})
    old = existing or {}
    out = {}
    for key in meta["fields"]:
        val = (incoming or {}).get(key, None)
        if key in meta["secrets"]:
            if val in (None, "", SECRET_MARK, "__KEEP__"):
                out[key] = old.get(key) or ""
            else:
                out[key] = str(val).strip()
        else:
            out[key] = "" if val is None else str(val).strip()
    return out


# --------------------------------------------------------------------------
# transport
# --------------------------------------------------------------------------
def _open(req, timeout, verify=True):
    ctx = None if verify else ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        return resp.status, resp.read(4096).decode("utf-8", "replace")


def _post_json(url, payload, headers=None, timeout=DEFAULT_TIMEOUT):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    h = {
        "Content-Type": "application/json; charset=utf-8",
        "User-Agent": SOURCE_NAME,
    }
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST")
    return _open(req, timeout)


def _post_form(url, fields, timeout=DEFAULT_TIMEOUT):
    data = urllib.parse.urlencode(fields).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "User-Agent": SOURCE_NAME,
    }, method="POST")
    return _open(req, timeout)


def _parse_headers(raw):
    out = {}
    for line in (raw or "").splitlines():
        line = line.strip()
        if not line or ":" not in line:
            continue
        k, v = line.split(":", 1)
        if k.strip():
            out[k.strip()] = v.strip()
    return out


def _fail(msg):
    return {"ok": False, "detail": str(msg)[:300]}


def _result(status, text, expect_json_code=None):
    if status < 200 or status >= 300:
        return _fail("HTTP %d %s" % (status, text[:200]))
    if expect_json_code is not None:
        try:
            data = json.loads(text)
        except Exception:
            return {"ok": True, "detail": text[:120]}
        code = data.get("code")
        if code is not None and int(code) != expect_json_code:
            msg = data.get("message") or data.get("msg") or text[:160]
            return _fail("服务返回 %s：%s" % (code, msg))
        return {"ok": True, "detail": ""}
    return {"ok": True, "detail": text[:120]}


def _result_errcode(status, text):
    """企业微信/钉钉：HTTP 200 但 JSON 里 errcode 非 0 也算失败。"""
    if status < 200 or status >= 300:
        return _fail("HTTP %d %s" % (status, text[:200]))
    try:
        data = json.loads(text)
    except Exception:
        return {"ok": True, "detail": text[:120]}
    code = data.get("errcode")
    if code not in (None, 0, "0"):
        return _fail("服务返回 %s：%s" % (code, data.get("errmsg") or text[:160]))
    return {"ok": True, "detail": ""}


def _dingtalk_url(url, secret):
    """钉钉机器人开启「加签」后必须带 timestamp + sign，否则 400。"""
    secret = (secret or "").strip()
    if not secret:
        return url
    stamp = str(int(time.time() * 1000))
    string_to_sign = "%s\n%s" % (stamp, secret)
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                      digestmod=hashlib.sha256).digest()
    sign = urllib.parse.quote_plus(base64.b64encode(digest))
    joiner = "&" if "?" in url else "?"
    return "%s%stimestamp=%s&sign=%s" % (url, joiner, stamp, sign)


def send(channel, title, body):
    """Deliver one message. Returns {'ok': bool, 'detail': str}."""
    ctype = (channel.get("type") or "").strip()
    cfg = channel.get("config") or {}
    title = str(title or "")
    body = str(body or "")
    try:
        if ctype == "bark":
            server = (cfg.get("server") or "https://api.day.app").strip().rstrip("/")
            key = (cfg.get("key") or "").strip()
            if not key:
                return _fail("缺少设备 key")
            url = "%s/%s" % (server, urllib.parse.quote(key))
            status, text = _post_json(url, {
                "title": title,
                "body": body,
                "group": SOURCE_NAME,
                "icon": "",
            })
            return _result(status, text, expect_json_code=200)

        if ctype == "serverchan":
            key = (cfg.get("sendkey") or "").strip()
            if not key:
                return _fail("缺少 SendKey")
            # v3 keys look like SCT...; both forms post to sctapi.ftqq.com
            url = "https://sctapi.ftqq.com/%s.send" % key
            status, text = _post_form(url, {"title": title, "desp": body})
            return _result(status, text, expect_json_code=0)

        if ctype == "pushplus":
            token = (cfg.get("token") or "").strip()
            if not token:
                return _fail("缺少 token")
            status, text = _post_json("https://www.pushplus.plus/send", {
                "token": token,
                "title": title,
                "content": body,
                "template": "markdown",
            })
            return _result(status, text, expect_json_code=200)

        if ctype == "wxpusher":
            app_token = (cfg.get("app_token") or "").strip()
            if not app_token:
                return _fail("缺少 appToken")
            uids = [x.strip() for x in (cfg.get("uids") or "").split(",") if x.strip()]
            topics = []
            for x in (cfg.get("topics") or "").split(","):
                x = x.strip()
                if x.isdigit():
                    topics.append(int(x))
            payload = {
                "appToken": app_token,
                "content": body,
                "summary": title[:99],
                "contentType": 1,
            }
            if uids:
                payload["uids"] = uids
            if topics:
                payload["topicIds"] = topics
            status, text = _post_json("https://wxpusher.zjiecode.com/api/send/message", payload)
            return _result(status, text, expect_json_code=1000)

        if ctype == "telegram":
            token = (cfg.get("bot_token") or "").strip()
            chat_id = (cfg.get("chat_id") or "").strip()
            if not token:
                return _fail("缺少 Bot Token")
            if not chat_id:
                return _fail("缺少 Chat ID")
            base = (cfg.get("api_base") or "https://api.telegram.org").strip().rstrip("/")
            url = "%s/bot%s/sendMessage" % (base, token)
            status, text = _post_json(url, {
                "chat_id": chat_id,
                "text": ("%s\n%s" % (title, body)).strip(),
                "disable_web_page_preview": True,
            })
            if status < 200 or status >= 300:
                return _fail("HTTP %d %s" % (status, text[:200]))
            try:
                data = json.loads(text)
            except Exception:
                return {"ok": True, "detail": text[:120]}
            if not data.get("ok"):
                return _fail("Telegram 返回失败：%s" % (data.get("description") or text[:160]))
            return {"ok": True, "detail": ""}

        if ctype == "wecom":
            key = (cfg.get("key") or "").strip()
            if not key:
                return _fail("缺少机器人 key")
            url = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=%s" % urllib.parse.quote(key)
            status, text = _post_json(url, {
                "msgtype": "text",
                "text": {"content": ("%s\n%s" % (title, body)).strip()},
            })
            return _result_errcode(status, text)

        if ctype == "dingtalk":
            url = (cfg.get("url") or "").strip()
            if not url.startswith("http"):
                return _fail("Webhook 地址无效")
            url = _dingtalk_url(url, cfg.get("secret") or "")
            status, text = _post_json(url, {
                "msgtype": "text",
                "text": {"content": ("%s\n%s" % (title, body)).strip()},
            })
            return _result_errcode(status, text)

        if ctype == "slack":
            url = (cfg.get("url") or "").strip()
            if not url.startswith("http"):
                return _fail("Webhook 地址无效")
            text = ("*%s*\n%s" % (title, body)).strip() if title else body
            status, text_out = _post_json(url, {"text": text})
            return _result(status, text_out)

        if ctype == "webhook":
            url = (cfg.get("url") or "").strip()
            if not url.startswith("http"):
                return _fail("Webhook 地址无效")
            status, text = _post_json(url, {
                "title": title,
                "content": body,
                "source": SOURCE_NAME,
            }, _parse_headers(cfg.get("headers") or ""))
            return _result(status, text)

        return _fail("未知渠道类型：%s" % ctype)
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read(300).decode("utf-8", "replace")
        except Exception:
            pass
        return _fail("HTTP %d %s" % (exc.code, detail))
    except urllib.error.URLError as exc:
        return _fail(getattr(exc, "reason", exc))
    except Exception as exc:  # pragma: no cover - defensive
        return _fail(exc)
