/* fn-emule - HTTP layer towards the panel backend (CONTRACT.md 3)
 *
 * Every request uses a RELATIVE url on purpose: opened from the fnOS desktop
 * the page lives under /cgi/ThirdParty/fn-emule/index.cgi/, so an absolute
 * "/api/..." would escape the app's CGI mount point. No host or port is ever
 * hard-coded here.
 */
(function () {
  "use strict";

  const BASE = "./api";

  function qs(params) {
    if (!params) return "";
    const p = new URLSearchParams();
    Object.keys(params).forEach(function (k) {
      const v = params[k];
      if (v === undefined || v === null || v === "") return;
      p.append(k, v);
    });
    const s = p.toString();
    return s ? "?" + s : "";
  }

  async function request(path, opts) {
    opts = opts || {};
    const init = {
      method: opts.method || "GET",
      headers: Object.assign({}, opts.headers || {}),
      cache: "no-store",
      credentials: "same-origin",
    };
    if (opts.body !== undefined && opts.body !== null) {
      if (typeof opts.body === "string" || opts.raw) {
        init.body = opts.body;
      } else {
        init.headers["Content-Type"] = "application/json";
        init.body = JSON.stringify(opts.body);
      }
    }
    let resp;
    try {
      resp = await fetch(path, init);
    } catch (e) {
      const err = new Error("network");
      err.offline = true;
      throw err;
    }
    const text = await resp.text();
    let data = null;
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (e) {
        data = text;
      }
    }
    if (!resp.ok) {
      const msg = (data && data.error) || (typeof data === "string" && data) || ("HTTP " + resp.status);
      const err = new Error(typeof msg === "string" ? msg.slice(0, 300) : "request failed");
      err.status = resp.status;
      err.payload = data;
      throw err;
    }
    return data;
  }

  const API = {
    base: BASE,
    request: request,

    /* ---- liveness / engine ---- */
    health: function () { return request(BASE + "/health"); },
    coreStatus: function () { return request(BASE + "/core/status"); },
    core: function (op) { return request(BASE + "/core/" + op, { method: "POST", body: {} }); },

    /* ---- overview ---- */
    overview: function () { return request(BASE + "/overview"); },
    diagnostics: function () { return request(BASE + "/diagnostics"); },

    /* ---- transfers ---- */
    transfers: function (type) { return request(BASE + "/transfers" + qs({ type: type || "download" })); },
    transferDetail: function (hash) { return request(BASE + "/transfers/" + encodeURIComponent(hash)); },
    transferAction: function (hash, action, priority) {
      const body = { action: action };
      if (priority) body.priority = priority;
      return request(BASE + "/transfers/" + encodeURIComponent(hash) + "/action", { method: "POST", body: body });
    },
    transferApply: function (hashes, action, deleteData) {
      const body = { hashes: hashes, action: action };
      // action "delete" only: keep the temp data on disk unless asked otherwise
      if (action === "delete") body.delete_data = !!deleteData;
      return request(BASE + "/transfers/apply", { method: "POST", body: body });
    },
    /* Deleting a transfer always goes through the batch endpoint - a single row
       passes a one-element array, so there is only one code path to keep in sync. */
    transferDelete: function (hashes, deleteData) {
      return this.transferApply(hashes, "delete", !!deleteData);
    },
    addLinks: function (links, category, paused) {
      return request(BASE + "/transfers/add", {
        method: "POST",
        body: { links: links, category: category || "", paused: !!paused },
      });
    },

    /* ---- servers ---- */
    servers: function () { return request(BASE + "/servers"); },
    serverConnect: function (ip, port) {
      return request(BASE + "/servers/connect", { method: "POST", body: { ip: ip, port: port } });
    },
    serverAdd: function (ip, port, name) {
      return request(BASE + "/servers/add", { method: "POST", body: { ip: ip, port: port, name: name || "" } });
    },
    serverRemove: function (ip, port) {
      return request(BASE + "/servers/remove", { method: "POST", body: { ip: ip, port: port } });
    },
    serverPriority: function (ip, port, priority) {
      return request(BASE + "/servers/priority", { method: "POST", body: { ip: ip, port: port, priority: priority } });
    },
    serversUpdate: function () { return request(BASE + "/servers/update", { method: "POST", body: {} }); },

    /* ---- kad ---- */
    kad: function () { return request(BASE + "/kad"); },
    kadBootstrap: function () { return request(BASE + "/kad/bootstrap", { method: "POST", body: {} }); },

    /* ---- shared files ---- */
    shared: function () { return request(BASE + "/shared"); },
    sharedReload: function () { return request(BASE + "/shared/reload", { method: "POST", body: {} }); },

    /* ---- search ---- */
    searchStart: function (q, kind, method) {
      return request(BASE + "/search/start", {
        method: "POST",
        body: { q: q, kind: kind || "server", method: method || "name" },
      });
    },
    searchState: function (id) { return request(BASE + "/search/" + encodeURIComponent(id)); },
    searchStop: function (id) { return request(BASE + "/search/" + encodeURIComponent(id) + "/stop", { method: "POST", body: {} }); },
    searchDownload: function (id, hash) {
      return request(BASE + "/search/" + encodeURIComponent(id) + "/download", { method: "POST", body: { hash: hash } });
    },

    /* ---- stats / logs ---- */
    stats: function () { return request(BASE + "/stats"); },
    logs: function (limit) { return request(BASE + "/log" + qs({ limit: limit || 200 })); },

    /* ---- settings / prefs ---- */
    settings: function () { return request(BASE + "/settings"); },
    saveSettings: function (settings) {
      return request(BASE + "/settings", { method: "POST", body: { settings: settings } });
    },
    prefs: function () { return request(BASE + "/prefs"); },

    /* ---- notifications ---- */
    notify: function () { return request(BASE + "/notify"); },
    notifySettings: function (settings) {
      return request(BASE + "/notify/settings", { method: "POST", body: { settings: settings } });
    },
    notifyChannel: function (channel) {
      return request(BASE + "/notify/channel", { method: "POST", body: channel });
    },
    notifyTest: function (id) {
      return request(BASE + "/notify/test", { method: "POST", body: { id: id } });
    },

    /* ---- backup ---- */
    backupStatus: function () { return request(BASE + "/backup/status"); },
    backupRun: function () { return request(BASE + "/backup/run", { method: "POST", body: {} }); },
    backupRestore: function (name) {
      return request(BASE + "/backup/restore", { method: "POST", body: { name: name } });
    },
    backupDelete: function (name) {
      return request(BASE + "/backup/delete", { method: "POST", body: { name: name } });
    },

    /* ---- update ---- */
    updateCheck: function (force) { return request(BASE + "/update/check" + (force ? "?force=1" : "")); },
    installUpdate: function () { return request(BASE + "/update/install", { method: "POST", body: {} }); },
    updateProgress: function () { return request(BASE + "/update/progress"); },
  };

  window.EMU_API = API;
})();
