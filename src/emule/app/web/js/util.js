/* fn-emule - formatting helpers and eD2k/Kad transfer metadata
 *
 * Numbers use 1024-based byte
 * units (KB/MB/GB/TB), speed as "<size>/s", percentages with two decimals,
 * durations as hh:mm:ss. UI copy lives in i18n.js - this file only carries
 * machine keys and tones.
 */
(function () {
  "use strict";

  const UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];

  function fmtBytes(n, digits) {
    n = Number(n) || 0;
    if (n <= 0) return "0 B";
    let i = 0;
    while (n >= 1024 && i < UNITS.length - 1) {
      n /= 1024;
      i++;
    }
    const d = digits === undefined ? (i === 0 ? 0 : n >= 100 ? 0 : n >= 10 ? 1 : 2) : digits;
    return n.toFixed(d) + " " + UNITS[i];
  }

  /* A speed is always a number: an idle transfer reads "0 B/s" instead of a
     dash, so a 0 download and a 32 B/s upload in the same stat row look alike. */
  function fmtSpeed(n) {
    const v = Number(n) || 0;
    if (v <= 0) return "0 B/s";
    return fmtBytes(v) + "/s";
  }

  /* percent is 0..1 in the API; two decimals as the contract requires */
  function fmtPercent(p, digits) {
    const v = (Number(p) || 0) * 100;
    return v.toFixed(digits === undefined ? 2 : digits) + "%";
  }

  function pad2(x) {
    return String(x).padStart(2, "0");
  }

  /* hh:mm:ss - total hours, so a 30h ETA reads 30:00:00 instead of wrapping */
  function fmtDuration(sec) {
    sec = Math.max(0, Math.floor(Number(sec) || 0));
    const h = Math.floor(sec / 3600);
    const m = Math.floor((sec % 3600) / 60);
    const s = sec % 60;
    return pad2(h) + ":" + pad2(m) + ":" + pad2(s);
  }

  function fmtEta(sec) {
    sec = Number(sec);
    if (!sec || sec <= 0 || sec >= 8640000) return "∞";
    return fmtDuration(sec);
  }

  function fmtDate(unix) {
    const v = Number(unix) || 0;
    if (v <= 0) return "—";
    const d = new Date(v * 1000);
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate()) +
      " " + pad2(d.getHours()) + ":" + pad2(d.getMinutes()) + ":" + pad2(d.getSeconds());
  }

  function fmtDateMin(unix) {
    return fmtDate(unix).slice(0, 16);
  }

  function fmtClock(unix) {
    return fmtDate(unix).slice(11);
  }

  function fmtNum(n) {
    return (Number(n) || 0).toLocaleString();
  }

  /* ---- transfer status ----
   * The vocabulary is fixed by CONTRACT.md 3: downloading | paused | waiting |
   * hashing | error | completing | complete (+ uploading for the share list).
   * group drives the filter tabs, tone drives colour. */
  const STATE_MAP = {
    downloading: { group: "downloading", tone: "dl" },
    waiting: { group: "waiting", tone: "warn" },
    paused: { group: "paused", tone: "idle" },
    hashing: { group: "other", tone: "warn" },
    error: { group: "error", tone: "err" },
    completing: { group: "other", tone: "warn" },
    complete: { group: "complete", tone: "ok" },
    uploading: { group: "uploading", tone: "ul" },
    stopped: { group: "paused", tone: "idle" },
  };

  function stateInfo(state) {
    const s = String(state || "").toLowerCase();
    return Object.assign({ key: s || "unknown" }, STATE_MAP[s] || { group: "other", tone: "idle" });
  }

  const TONE_COLOR = {
    dl: "var(--dl)",
    ul: "var(--ul)",
    ok: "var(--ok)",
    warn: "var(--warn)",
    err: "var(--err)",
    idle: "var(--idle)",
  };

  function toneColor(tone) {
    return TONE_COLOR[tone] || TONE_COLOR.idle;
  }

  function isActive(t) {
    const s = stateInfo(t.status).group;
    return s === "downloading" || s === "waiting";
  }

  function isPaused(t) {
    return stateInfo(t.status).group === "paused";
  }

  function isError(t) {
    return stateInfo(t.status).group === "error";
  }

  function isDone(t) {
    return Number(t.percent) >= 1 || stateInfo(t.status).group === "complete";
  }

  function isUploading(t) {
    return stateInfo(t.status).group === "uploading";
  }

  /* Sources "3 / 120": connected now against everything known */
  function fmtSources(s) {
    s = s || {};
    return fmtNum(s.transferring || 0) + " / " + fmtNum(s.total || 0);
  }

  function fmtPriority(p) {
    const k = { low: "low", normal: "normal", high: "high", auto: "auto" };
    return k[String(p || "").toLowerCase()] || "normal";
  }

  window.EMU_FMT = {
    fmtBytes, fmtSpeed, fmtPercent, fmtDuration, fmtEta, fmtDate, fmtDateMin, fmtClock,
    fmtNum, fmtSources, fmtPriority,
    stateInfo, toneColor, isActive, isPaused, isError, isDone, isUploading,
  };
})();
