/* fn-emule - application logic (Vue 3 in-DOM template, no build step) */
(function () {
  "use strict";

  const FMT = window.EMU_FMT;
  const CHART = window.EMU_CHART;
  const I18N = window.EMU_I18N;

  /* ---------- inline svg icons (lucide-style, 1.8px stroke) ---------- */
  const S = 'fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"';
  const svg = (body, size) =>
    '<svg width="' + (size || 18) + '" height="' + (size || 18) + '" viewBox="0 0 24 24" ' + S + '>' + body + '</svg>';

  const ICONS = {
    dash: svg('<rect x="3" y="3" width="7.5" height="9" rx="1.6"/><rect x="13.5" y="3" width="7.5" height="5.5" rx="1.6"/><rect x="13.5" y="12" width="7.5" height="9" rx="1.6"/><rect x="3" y="15.5" width="7.5" height="5.5" rx="1.6"/>'),
    tasks: svg('<path d="M4 6h16M4 12h16M4 18h10"/>'),
    servers: svg('<rect x="3" y="4" width="18" height="7" rx="2"/><rect x="3" y="13" width="18" height="7" rx="2"/><path d="M7.5 7.5h.01M7.5 16.5h.01"/>'),
    search: svg('<circle cx="11" cy="11" r="7"/><path d="m20 20-3.6-3.6"/>'),
    shared: svg('<path d="M3 7a2 2 0 0 1 2-2h3.6l2 2.5H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'),
    stats: svg('<path d="M4 19V5"/><path d="M4 19h16"/><path d="M8 16l3-4 3 2 4-6"/>'),
    logs: svg('<path d="M5 3h10l4 4v14H5z"/><path d="M15 3v4h4"/><path d="M8 12h8M8 16h5"/>'),
    settings: svg('<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M4.2 4.2l2.1 2.1M17.7 17.7l2.1 2.1M2 12h3M19 12h3M4.2 19.8l2.1-2.1M17.7 6.3l2.1-2.1"/>'),
    menu: svg('<path d="M4 7h16M4 12h16M4 17h16"/>'),
    sun: svg('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/>'),
    moon: svg('<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a7 7 0 0 0 10.5 10.5z"/>'),
    monitor: svg('<rect x="2" y="3" width="20" height="14" rx="2"/><path d="M8 21h8M12 17v4"/>'),
    lang: svg('<path d="m5 8 6 6"/><path d="m4 14 6-6 2-3"/><path d="M2 5h12"/><path d="M7 2h1"/><path d="m22 22-5-10-5 10"/><path d="M14 18h6"/>'),
    globe: svg('<circle cx="12" cy="12" r="9"/><path d="M3 12h18"/><path d="M12 3a15 15 0 0 1 0 18a15 15 0 0 1 0-18z"/>', 14),
    collapse: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="m16 15-3-3 3-3"/>'),
    expand: svg('<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/><path d="m14 9 3 3-3 3"/>'),
    refresh: svg('<path d="M20 11A8 8 0 0 0 6.3 6.3L4 8.5"/><path d="M4 4v4.5h4.5"/><path d="M4 13a8 8 0 0 0 13.7 4.7L20 15.5"/><path d="M20 20v-4.5h-4.5"/>'),
    plus: svg('<path d="M12 5v14M5 12h14"/>', 16),
    down: svg('<path d="M12 4v14"/><path d="M6 13l6 6 6-6"/>', 16),
    up: svg('<path d="M12 20V6"/><path d="M6 11l6-6 6 6"/>', 16),
    list: svg('<path d="M8 6h12M8 12h12M8 18h12"/><path d="M4 6h.01M4 12h.01M4 18h.01"/>'),
    hdd: svg('<rect x="3" y="5" width="18" height="6" rx="1.6"/><rect x="3" y="13" width="18" height="6" rx="1.6"/><path d="M7 8h.01M7 16h.01"/>', 16),
    play: svg('<path d="M7 5l12 7-12 7z"/>', 15),
    pause: svg('<path d="M9 5v14M15 5v14"/>', 15),
    trash: svg('<path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="M6 7l1 13h10l1-13"/>', 15),
    close: svg('<path d="M6 6l12 12M18 6L6 18"/>'),
    spark: svg('<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/><path d="M18 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8z"/>', 20),
    bell: svg('<path d="M6 8a6 6 0 1 1 12 0c0 5 2 6 2 6H4s2-1 2-6"/><path d="M10.3 20a2 2 0 0 0 3.4 0"/>', 18),
    arrowRight: svg('<path d="M5 12h14"/><path d="m13 6 6 6-6 6"/>', 20),
    sortAsc: svg('<path d="M12 19V5"/><path d="M6 11l6-6 6 6"/>', 16),
    sortDesc: svg('<path d="M12 5v14"/><path d="M6 13l6 6 6-6"/>', 16),
    download: svg('<path d="M12 3v12"/><path d="m7 11 5 5 5-5"/><path d="M4 20h16"/>', 16),
    folder: svg('<path d="M3 7a2 2 0 0 1 2-2h3.6l2 2.5H19a2 2 0 0 1 2 2V17a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>', 16),
    plug: svg('<path d="M9 3v6M15 3v6"/><path d="M6 9h12v3a6 6 0 0 1-12 0z"/><path d="M12 18v3"/>', 20),
    check: svg('<path d="m4 12 5 5L20 6"/>', 16),
    pulse: svg('<path d="M3 12h4l2.5-7 4 14 2.5-7h5"/>', 18),
    alert: svg('<path d="M12 3 2.5 20h19z"/><path d="M12 9v5M12 17.5h.01"/>', 16),
  };

  const THEME_ORDER = ["dark", "light", "auto"];
  const PRIORITIES = ["low", "normal", "high", "auto"];
  /* fallback field list when /api/notify does not describe a type */
  const CHANNEL_FIELDS = {
    bark: ["server", "key"],
    serverchan: ["sendkey"],
    pushplus: ["token"],
    wxpusher: ["app_token", "uids", "topics"],
    telegram: ["bot_token", "chat_id", "api_base"],
    wecom: ["key"],
    dingtalk: ["url", "secret"],
    slack: ["url"],
    webhook: ["url", "headers"],
  };

  const POLL_MS = 2500;
  const LOG_POLL_MS = 5000;
  /* 与后端 /api/log 的上限（2000）对齐 */
  const LOG_FETCH_LIMIT = 2000;
  const BACKUP_ROWS = 5;

  function clone(o) {
    return JSON.parse(JSON.stringify(o || {}));
  }

  function emptySettings() {
    return {
      panel: { port: 17581, theme: "auto", lang: "zh" },
      engine: {
        ec_port: 4712, ec_password: "", tcp_port: 4662, udp_port: 4672, nick: "fnOS@eMule",
        incoming_dir: "", temp_dir: "", shared_dirs: [],
        max_download: 0, max_upload: 0, max_connections: 500, max_sources: 300,
        autoconnect: true, connect_ed2k: true, connect_kad: true,
        add_paused: false, ich: true, aich: true, upnp: false, ipfilter: true,
      },
      bootstrap: { server_met_url: "", nodes_dat_url: "", auto_hours: 24, last_update: 0 },
      notify: { enabled: false, channels: [], events: { complete: true, error: true } },
      backup: { auto: false, keep: 7, last: 0 },
      update: { repo: "Smi13zZ/fn-emule", check: true, last: 0, latest: "" },
    };
  }

  /* keys whose change makes the backend restart amuled */
  const RESTART_PATHS = [
    "engine.tcp_port", "engine.udp_port", "engine.ec_port",
    "engine.incoming_dir", "engine.temp_dir", "engine.shared_dirs",
  ];
  const FORM_TABS = ["panel", "network", "bandwidth", "dirs", "bootstrap"];

  function getPath(obj, path) {
    return path.split(".").reduce(function (o, k) {
      return o === undefined || o === null ? undefined : o[k];
    }, obj);
  }

  Vue.createApp({
    data: function () {
      return {
        fmt: Object.assign({}, FMT),

        loaded: false,
        busy: false,
        navOpen: false,
        view: "dash",
        collapsed: false,
        lang: "zh",
        theme: "dark",
        themeOverride: "",
        isMobile: false,

        appVersion: "1.0.0",
        engineVersion: "",
        health: {},
        panelDown: false,
        coreStarting: false,

        overview: {},
        transfersData: { items: [], summary: {}, total: 0 },
        kind: "download",
        kinds: ["download", "upload"],

        search: "",
        filter: "all",
        filters: ["all", "downloading", "waiting", "paused", "complete", "error"],
        sortKeys: ["added", "name", "size", "percent", "speed", "eta"],
        sortKey: "added",
        sortAsc: false,
        selection: [],
        priorities: PRIORITIES,

        detail: null,
        detailTab: "info",
        detailTabs: ["info", "sources", "chunks"],
        detailData: { file: null, sources: [], chunks: [] },
        detailLoading: false,
        detailHash: "",

        serversData: { items: [], current: null, ed2k_connected: false, total: 0, working: 0 },
        serversUpdating: false,
        connectingKey: "",
        serverForm: null,
        savingServer: false,

        query: "",
        searchKind: "server",
        searchKinds: ["server", "kad", "global"],
        searchMethod: "name",
        searchMethods: ["name", "hash"],
        searchId: "",
        searchRunning: false,
        searchProgress: 0,
        searchResults: [],
        searchStarted: false,
        resultSelection: [],
        downloadingResults: false,
        searchTimer: null,

        sharedData: { items: [], total: 0 },
        sharedReloading: false,

        statsData: { groups: [], items: [] },
        diag: null,
        diagLoading: false,
        diagError: "",
        diagHow: false,
        statsLoading: false,

        logs: [],
        logsLoading: false,
        logLevel: "all",
        logLevels: ["all", "info", "warn", "error"],
        logSource: "all",
        logSources: ["all", "engine", "panel"],
        logAuto: false,
        logCleared: false,

        settings: emptySettings(),
        saved: emptySettings(),
        draft: emptySettings(),
        settingsTab: "panel",
        settingsSaving: false,
        newSharedDir: "",
        bootstrapping: false,

        notifyChannels: [],
        notifyTypes: ["bark", "serverchan", "pushplus", "wxpusher", "webhook"],
        notifyTypeMeta: {},
        channelForm: null,
        savingChannel: false,
        testingChannel: "",

        backupData: { items: [] },
        backupRunning: false,

        updateInfo: null,
        updateChecking: false,
        updateInstalling: false,
        updateError: "",
        updateInstallDetail: "",
        /* 全局更新提示条：发现新版本后在每个页面顶部提示，关掉后本次会话不再出现 */
        updateBanner: true,
        /* 一键更新的下载进度（后台任务轮询回来的） */
        updateProgress: { percent: 0, phase: "idle", received: 0, total: 0 },
        installTimer: null,

        addOpen: false,
        addForm: { links: "", category: "", paused: false },
        adding: false,

        confirmBox: null,
        toasts: [],
        pickerState: null,
      };
    },

    computed: {
      navItems: function () {
        const t = this.t;
        return [
          { id: "dash", icon: "dash", key: "nav.overview", label: t("nav.overview") },
          { id: "tasks", icon: "tasks", key: "nav.tasks", label: t("nav.tasks") },
          { id: "servers", icon: "servers", key: "nav.servers", label: t("nav.servers") },
          { id: "search", icon: "search", key: "nav.search", label: t("nav.search") },
          { id: "shared", icon: "shared", key: "nav.shared", label: t("nav.shared") },
          { id: "stats", icon: "stats", key: "nav.stats", label: t("nav.stats") },
          { id: "logs", icon: "logs", key: "nav.logs", label: t("nav.logs") },
          { id: "diagnostics", icon: "pulse", key: "nav.diagnostics", label: t("nav.diagnostics") },
          { id: "settings", icon: "settings", key: "nav.settings", label: t("nav.settings") },
        ];
      },
      pageTitle: function () {
        const item = this.navItems.filter((n) => n.id === this.view)[0];
        return item ? item.label : this.t("app.name");
      },
      settingsTabs: function () {
        const t = this.t;
        return [
          { id: "panel", label: t("settings.tab.panel") },
          { id: "network", label: t("settings.tab.network") },
          { id: "bandwidth", label: t("settings.tab.bandwidth") },
          { id: "dirs", label: t("settings.tab.dirs") },
          { id: "bootstrap", label: t("settings.tab.bootstrap") },
          { id: "notify", label: t("settings.tab.notify") },
          { id: "backup", label: t("settings.tab.backup") },
          { id: "update", label: t("settings.tab.update") },
          { id: "about", label: t("settings.tab.about") },
        ];
      },
      themeMode: function () {
        return this.themeOverride || (this.draft.panel && this.draft.panel.theme) || "auto";
      },
      themeIcon: function () {
        const m = this.themeMode;
        return m === "dark" ? "moon" : m === "light" ? "sun" : "monitor";
      },
      themeTooltip: function () {
        const m = this.themeMode;
        const next = THEME_ORDER[(THEME_ORDER.indexOf(m) + 1) % THEME_ORDER.length];
        return this.t("side.theme." + (next === "auto" ? "system" : next));
      },
      engine: function () { return this.overview.engine || {}; },
      ed2k: function () { return this.overview.ed2k || {}; },
      kad: function () { return this.overview.kad || {}; },
      speed: function () { return this.overview.speed || {}; },
      session: function () { return this.overview.session || {}; },
      counters: function () { return this.overview.counters || {}; },
      disk: function () { return this.overview.disk || {}; },
      /* health.engine.phase (idle|missing|preparing|starting|running|stopped|failed)
         is the authoritative lifecycle signal; running alone is not enough during
         the cold start, where the panel must say "starting", not "offline". */
      enginePhase: function () {
        const h = this.health || {};
        if (h.engine && h.engine.phase) return String(h.engine.phase);
        if (h.amule && h.amule.running === false) return "stopped";
        if (this.overview.engine && this.overview.engine.running === true) return "running";
        return "";
      },
      engineStarting: function () {
        return ["preparing", "starting"].indexOf(this.enginePhase) >= 0;
      },
      engineRunning: function () {
        if (this.health && this.health.amule) return !!this.health.amule.running;
        return false;
      },
      engineVersionText: function () {
        return (this.health && this.health.amule && this.health.amule.version) || "";
      },
      engineUptimeText: function () {
        const st = this.health && this.health.engine || {};
        return st.uptime ? this.fmt.fmtDuration(st.uptime) : "";
      },
      engineDotClass: function () {
        if (this.engineStarting) return "warn";
        return this.engineRunning ? "on" : "err";
      },
      engineStatusText: function () {
        if (this.coreWorking) return this.t("engine.working");
        if (this.engineStarting) return this.t("engine.banner.startText");
        if (this.engineRunning) return this.t("engine.state.running");
        return this.t("engine.state.stopped");
      },
      engineBarVisible: function () {
        return this.loaded && !this.panelDown;
      },
      engineDown: function () {
        if (!this.loaded) return false;
        if (this.engineStarting) return false;
        if (this.overview.engine && this.overview.engine.running === false) return true;
        if (this.health && this.health.amule && this.health.amule.running === false) return true;
        const phase = this.enginePhase;
        return ["idle", "missing", "stopped", "failed"].indexOf(phase) >= 0;
      },
      engineBannerText: function () {
        if (this.engineStarting) return this.t("engine.banner.startText");
        const detail = (this.health && this.health.engine && this.health.engine.detail) || "";
        if (this.enginePhase === "failed" && detail) return this.t("engine.banner.failed", { v: detail });
        return this.t("engine.banner.text");
      },
      ecDown: function () {
        return !!(!this.engineDown && this.overview.engine &&
          this.overview.engine.running === true && this.overview.engine.ec === false);
      },
      connOK: function () {
        if (this.engineDown || this.ecDown) return false;
        return !!(this.ed2k.connected || this.kad.connected);
      },
      tasks: function () {
        return this.transfersData.items || [];
      },
      taskCount: function () { return this.tasks.length; },
      visibleTasks: function () {
        const self = this;
        const q = this.search.trim().toLowerCase();
        let list = this.tasks.filter(function (it) {
          if (q && (it.name || "").toLowerCase().indexOf(q) < 0 &&
              (it.category || "").toLowerCase().indexOf(q) < 0) return false;
          if (self.filter === "all") return true;
          return FMT.stateInfo(it.status).group === self.filter;
        });
        const key = this.sortKey;
        const dir = this.sortAsc ? 1 : -1;
        list = list.slice().sort(function (a, b) {
          let x, y;
          if (key === "name") {
            x = String(a.name || "");
            y = String(b.name || "");
            return x.localeCompare(y) * dir;
          }
          if (key === "added") { x = a.added; y = b.added; }
          else { x = a[key]; y = b[key]; }
          return ((Number(x) || 0) - (Number(y) || 0)) * dir;
        });
        return list;
      },
      allSelected: function () {
        return this.visibleTasks.length > 0 && this.selection.length === this.visibleTasks.length;
      },
      selectedTasks: function () {
        const set = {};
        this.selection.forEach(function (h) { set[h] = true; });
        return this.tasks.filter(function (it) { return set[it.hash]; });
      },
      statusSegments: function () {
        const t = this.t;
        const buckets = [
          { key: "downloading", label: t("tasks.filter.downloading"), color: CHART.cssVar("--dl", "#2563eb"), n: 0 },
          { key: "waiting", label: t("tasks.filter.waiting"), color: CHART.cssVar("--warn", "#f59e0b"), n: 0 },
          { key: "paused", label: t("tasks.filter.paused"), color: CHART.cssVar("--idle", "#a3a3a3"), n: 0 },
          { key: "complete", label: t("tasks.filter.complete"), color: CHART.cssVar("--ok", "#16a34a"), n: 0 },
          { key: "error", label: t("tasks.filter.error"), color: CHART.cssVar("--err", "#e7000b"), n: 0 },
        ];
        const map = {};
        buckets.forEach(function (b) { map[b.key] = b; });
        this.tasks.forEach(function (it) {
          const g = FMT.stateInfo(it.status).group;
          const b = map[g] || map.paused;
          b.n += 1;
        });
        return buckets
          .filter(function (b) { return b.n > 0 || b.key === "downloading" || b.key === "complete"; })
          .map(function (b) { return { key: b.key, label: b.label, value: b.n, color: b.color }; });
      },
      recentLogs: function () {
        return this.logs.slice(-6);
      },
      visibleLogs: function () {
        const self = this;
        return this.logs.filter(function (l) {
          if (self.logLevel !== "all" && (l.level || "info") !== self.logLevel) return false;
          const src = l.source || "engine";
          if (self.logSource !== "all" && src !== self.logSource) return false;
          return true;
        });
      },
      statsGroups: function () {
        const items = this.statsData.items || [];
        const order = (this.statsData.groups || []).slice();
        const map = {};
        items.forEach((row) => {
          const key = row.group || '';
          if (!map[key]) map[key] = { key: key, label: this.statGroupLabel(row), items: [] };
          map[key].items.push(row);
        });
        const keys = Object.keys(map);
        keys.sort((a, b) => {
          const ia = order.indexOf(a), ib = order.indexOf(b);
          return (ia < 0 ? 999 : ia) - (ib < 0 ? 999 : ib);
        });
        return keys.map((k) => map[k]);
      },
      /* ---- diagnostics ---- */
      diagGrade: function () {
        const g = (this.diag && this.diag.summary && this.diag.summary.grade) || 'ok';
        return g === 'error' ? 'error' : g === 'warn' ? 'warn' : 'ok';
      },
      diagGradeDot: function () {
        return this.diagGrade === 'ok' ? 'on' : this.diagGrade === 'warn' ? 'warn' : 'err';
      },
      diagEngine: function () {
        const e = (this.diag && this.diag.engine) || {};
        const kad = e.kad || {};
        const server = e.server || null;
        return {
          connected: !!e.ed2k_connected,
          lowId: !!e.low_id,
          server: server,
          kadConnected: !!kad.connected,
          kadFirewalled: !!kad.firewalled,
          kadNodes: Number(kad.nodes) || 0,
          tcpPort: e.tcp_port || 0,
          udpPort: e.udp_port || 0,
          inbound: Number(e.inbound_connections) || 0,
          running: e.running !== false,
        };
      },
      diagHost: function () { return (this.diag && this.diag.host) || {}; },
      diagPorts: function () { return (this.diag && this.diag.ports) || {}; },
      diagOffline: function () { return !!(this.diag && this.diag.engine && this.diag.engine.running === false); },
      diagEd2kLabel: function () {
        if (!this.diagEngine.connected) return this.t('top.disconnected');
        return this.diagEngine.lowId ? this.t('diag.id.low') : this.t('diag.id.high');
      },
      diagServerLabel: function () {
        const s = this.diagEngine.server;
        if (!s) return this.t('diag.metric.noServer');
        return (s.name || '') + (s.ip ? ' · ' + s.ip + ':' + s.port : '');
      },
      diagKadLabel: function () {
        if (!this.diagEngine.kadConnected) return this.t('top.disconnected');
        return this.diagEngine.kadFirewalled ? this.t('diag.metric.firewalled') : this.t('diag.metric.open');
      },
      channelFields: function () {
        const f = this.channelForm;
        if (!f) return [];
        const meta = this.notifyTypeMeta[f.type];
        let names = (meta && meta.fields && meta.fields.length) ? meta.fields.slice() : (CHANNEL_FIELDS[f.type] || []);
        const secrets = (meta && meta.secrets) || [];
        let out = names.map((n) => ({ name: n, secret: secrets.indexOf(n) >= 0 }));
        if (!out.length) {
          const cfg = f.config || {};
          out = Object.keys(cfg).filter((k) => cfg[k] !== undefined).map((k) => ({ name: k, secret: false }));
        }
        return out;
      },
      updateNew: function () {
        return !!(this.updateInfo && (this.updateInfo.available || this.updateInfo.has_update));
      },
      chunkCells: function () {
        const cs = (this.detailData && this.detailData.chunks) || [];
        if (!cs.length) return [];
        const stateOf = function (c) {
          return c.state === "done" ? "done" : c.state === "pending" ? "pending" : "missing";
        };
        const MAX = 320;
        if (cs.length <= MAX) return cs.map(stateOf);
        const ratio = cs.length / MAX;
        const out = [];
        for (let i = 0; i < MAX; i++) {
          const a = Math.floor(i * ratio);
          const b = Math.max(a + 1, Math.floor((i + 1) * ratio));
          let done = 0, pend = 0, tot = 0;
          for (let k = a; k < b && k < cs.length; k++) {
            tot++;
            if (cs[k].state === "done") done++;
            else if (cs[k].state === "pending") pend++;
          }
          out.push(done === tot ? "done" : (done + pend > 0 ? "pending" : "missing"));
        }
        return out;
      },
      chunkTotal: function () {
        return ((this.detailData && this.detailData.chunks) || []).length;
      },
      allResultsSelected: function () {
        return this.searchResults.length > 0 && this.resultSelection.length === this.searchResults.length;
      },
      selectedResults: function () {
        const set = {};
        this.resultSelection.forEach(function (h) { set[h] = true; });
        return this.searchResults.filter(function (r) { return set[r.hash]; });
      },
      dirty: function () {
        return JSON.stringify(this.draft) !== JSON.stringify(this.saved);
      },
      restartNeeded: function () {
        return RESTART_PATHS.some((p) => JSON.stringify(getPath(this.draft, p)) !== JSON.stringify(getPath(this.saved, p)));
      },
    },

    watch: {
      logAuto: function (v) {
        if (v) {
          this.logCleared = false;
          this.loadLogs();
          this.$nextTick(this.jumpToLogEnd);
        }
      },
      filter: function () { this.selection = []; },
      kind: function () { this.selection = []; },
      settingsTab: function (v) {
        if (v === "update" && !this.updateInfo) this.checkUpdate(false);
        if (v === "notify" && !this.notifyChannels.length) this.loadNotify();
        if (v === "backup") this.loadBackup();
      },
      "channelForm.type": function (type) {
        if (type) this.ensureChannelFields(type);
      },
    },

    mounted: function () {
      this.init();
      this._sparkTimer = setInterval(this.sparkTick, 1000);
      this._onResize = () => { this.drawCharts(); };
      window.addEventListener("resize", this._onResize);
      this._mq = window.matchMedia ? window.matchMedia("(prefers-color-scheme: dark)") : null;
      if (this._mq) {
        this._onScheme = () => { this.applyTheme(); };
        if (this._mq.addEventListener) this._mq.addEventListener("change", this._onScheme);
        else if (this._mq.addListener) this._mq.addListener(this._onScheme);
      }
      this._mmq = window.matchMedia ? window.matchMedia("(max-width: 720px)") : null;
      if (this._mmq) {
        this._onViewport = () => { this.isMobile = !!this._mmq.matches; this.$nextTick(this.drawCharts); };
        this._onViewport();
        if (this._mmq.addEventListener) this._mmq.addEventListener("change", this._onViewport);
        else if (this._mmq.addListener) this._mmq.addListener(this._onViewport);
      }
    },

    beforeUnmount: function () {
      clearInterval(this._sparkTimer);
      clearInterval(this.searchTimer);
      clearInterval(this.installTimer);
      window.removeEventListener("resize", this._onResize);
      if (this._mq && this._onScheme) {
        if (this._mq.removeEventListener) this._mq.removeEventListener("change", this._onScheme);
        else if (this._mq.removeListener) this._mq.removeListener(this._onScheme);
      }
      if (this._mmq && this._onViewport) {
        if (this._mmq.removeEventListener) this._mmq.removeEventListener("change", this._onViewport);
        else if (this._mmq.removeListener) this._mmq.removeListener(this._onViewport);
      }
    },

    methods: {
      ic: function (name) { return ICONS[name] || ""; },

      t: function (key, vars) {
        if (!this._tc || this._tlang !== this.lang) {
          this._tc = I18N.makeT(this.lang);
          this._tlang = this.lang;
        }
        return this._tc(key, vars);
      },

      /* ---- status helpers ---- */
      stLabel: function (status) {
        const info = FMT.stateInfo(status);
        const key = "state." + info.key;
        const label = this.t(key);
        return { label: label === key ? (status || this.t("state.unknown")) : label, tone: info.tone, group: info.group };
      },
      sourceStateLabel: function (state) {
        const key = "detail.sourceState." + String(state || "idle");
        const out = this.t(key);
        return out === key ? String(state || "—") : out;
      },
      progressClass: function (it) {
        if (!it) return "";
        if (FMT.isError(it)) return "err";
        if (Number(it.percent) >= 1) return "done";
        if (FMT.isPaused(it)) return "paused";
        return "";
      },
      /* ec-core upload items carry uploaded + client{name,software,version}, the
         download items only carry done; render both shapes without branching in
         the template. */
      uploadedOf: function (it) {
        const v = it && (it.uploaded !== undefined && it.uploaded !== null ? it.uploaded : it.done);
        return Number(v) || 0;
      },
      clientLabel: function (it) {
        const c = it && it.client;
        if (!c) return "";
        const name = c.name || c.software || "";
        const ver = c.version ? " " + c.version : "";
        return (name + ver).trim();
      },
      queueOf: function (it) {
        if (!it) return "—";
        const v = it.waiting_position !== undefined && it.waiting_position !== null
          ? it.waiting_position : it.queue_rank;
        return (v === undefined || v === null) ? "—" : this.fmt.fmtNum(v);
      },
      serverAddr: function () {
        const s = this.ed2k && this.ed2k.server;
        return s ? s.name + " · " + s.ip + ":" + s.port : "";
      },
      isCurrent: function (s) {
        const cur = this.serversData.current;
        return !!(cur && cur.ip === s.ip && Number(cur.port) === Number(s.port));
      },

      /* ---- toast / picker ---- */
      toast: function (text, kind) {
        const id = Date.now() + Math.random();
        this.toasts.push({ id: id, text: text, kind: kind || "" });
        const self = this;
        setTimeout(function () {
          self.toasts = self.toasts.filter(function (x) { return x.id !== id; });
        }, kind === "err" ? 6000 : 3000);
      },
      ok: function (key, vars) { this.toast(this.t(key, vars)); },
      fail: function (key, e, vars) {
        const v = (e && e.message) || this.t("err.unknown");
        const merged = Object.assign({ v: v }, vars || {});
        this.toast(this.t(key, merged), "err");
      },
      openPicker: function (cfg) { this.pickerState = cfg; },
      closePicker: function (val) {
        const p = this.pickerState;
        this.pickerState = null;
        if (val !== undefined && p && typeof p.onPick === "function") p.onPick(val);
      },

      /* ---------------- bootstrap ---------------- */
      init: async function () {
        const params = new URLSearchParams(location.search);
        const wanted = params.get("view");
        if (wanted && this.navItems.some((n) => n.id === wanted)) this.view = wanted;

        const wantedTheme = params.get("theme");
        if (wantedTheme === "light" || wantedTheme === "dark" || wantedTheme === "system" || wantedTheme === "auto") {
          this.themeOverride = wantedTheme === "system" ? "auto" : wantedTheme;
        }
        const wantedLang = params.get("lang");
        if (wantedLang === "en" || wantedLang === "zh") this.lang = wantedLang;
        this._tc = I18N.makeT(this.lang);
        this._tlang = this.lang;
        document.documentElement.setAttribute("lang", this.lang === "zh" ? "zh-CN" : "en");

        await this.bootstrapPanel();
        setInterval(this.tick, 1000);
        setTimeout(() => { this.checkUpdate(false); }, 1800);
      },

      bootstrapPanel: async function () {
        try {
          const health = await window.EMU_API.health();
          this.health = health || {};
          this.panelDown = false;
          this.appVersion = (health && health.version) || this.appVersion;
        } catch (e) {
          this.panelDown = true;
          this.loaded = true;
          return;
        }
        await this.loadSettings();
        this.applyTheme();
        this.loaded = true;
        await this.refresh(true);
        await this.loadLogs(true);
        if (this.view === "servers") this.loadServers();
        if (this.view === "shared") this.loadShared();
        if (this.view === "stats") this.loadStats();
        if (this.view === "logs") this.loadLogs();
        if (this.view === "diagnostics") this.loadDiagnostics();
        if (this.view === "settings") this.loadNotify();
      },

      /* ---------------- theme / language / sidebar ---------------- */
      applyTheme: function () {
        const mode = this.themeMode;
        let eff = mode;
        if (mode === "auto" || mode === "system") {
          eff = (window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
        }
        this.theme = eff;
        document.documentElement.setAttribute("data-theme", eff);
        this.$nextTick(this.drawCharts);
      },

      cycleTheme: function () {
        const cur = this.themeMode;
        const next = THEME_ORDER[(THEME_ORDER.indexOf(cur) + 1) % THEME_ORDER.length];
        this.themeOverride = "";
        this.draft.panel.theme = next;
        this.applyTheme();
        this.persistDraft();
        this.toast(this.t(next === "dark" ? "msg.themeDark" : next === "light" ? "msg.themeLight" : "msg.themeSystem"));
      },

      setThemeMode: function (mode) {
        this.draft.panel.theme = mode;
        this.applyTheme();
        this.persistDraft();
      },

      toggleLang: function () {
        this.setLang(this.lang === "zh" ? "en" : "zh");
      },

      setLang: function (lang) {
        this.lang = (lang === "en") ? "en" : "zh";
        this.draft.panel.lang = this.lang;
        this._tc = I18N.makeT(this.lang);
        this._tlang = this.lang;
        document.documentElement.setAttribute("lang", this.lang === "zh" ? "zh-CN" : "en");
        this.persistDraft();
        this.toast(this.t("msg.langSwitched"));
      },

      toggleCollapse: function () {
        this.collapsed = !this.collapsed;
        this.$nextTick(this.drawCharts);
      },

      /* ---------------- polling ---------------- */
      tick: function () {
        if (this.panelDown) return;
        const now = Date.now();
        if (!this._lastPoll || now - this._lastPoll >= POLL_MS) {
          this._lastPoll = now;
          this.refresh();
        }
        const logView = this.view === "logs" || this.view === "dash";
        if (logView && (this.logAuto || this.view === "dash") &&
            (!this._lastLog || now - this._lastLog >= LOG_POLL_MS)) {
          this._lastLog = now;
          this.loadLogs(true);
        }
      },

      refresh: async function (force) {
        if (force) this.busy = true;
        try {
          const tasks = await window.EMU_API.transfers(this.kind);
          this.connected = true;
          this.connError = "";
          this.transfersData = tasks || { items: [], summary: {} };
          const alive = {};
          (this.transfersData.items || []).forEach(function (it) { alive[it.hash] = true; });
          this.selection = this.selection.filter(function (h) { return alive[h]; });
          if (this.detail) {
            const fresh = (this.transfersData.items || []).filter((x) => x.hash === this.detail.hash)[0];
            if (fresh) this.detail = fresh;
          }
        } catch (e) {
          this.connError = (e && e.message) || "";
        }
        try {
          const ov = await window.EMU_API.overview();
          this.overview = ov || {};
          this.engineVersion = (ov && ov.engine && ov.engine.version) || this.engineVersion;
          if (!this._chartSeeded && ov && ov.history && ov.history.length && this.speedChart) {
            this._chartSeeded = true;
            this.speedChart.load(ov.history);
          }
        } catch (e) {
          /* keep the previous numbers; the banner explains why */
          if (e && e.offline) this.panelDown = true;
        }
        if (this.view === "servers") this.loadServers(true);
        if (this.view === "shared" && !force) { /* the list is static, reload on demand */ }
        if (this.detail) this.loadDetail(this.detail.hash, true);
        if (this.view === "dash" || this.view === "stats") this.drawCharts();
        if (force) this.busy = false;
      },

      go: function (id) {
        this.view = id;
        this.navOpen = false;
        if (id === "logs") { this.logCleared = false; this.loadLogs(); }
        if (id === "diagnostics") this.loadDiagnostics();
        if (id === "settings") { this.loadNotify(); }
        if (id === "servers") this.loadServers();
        if (id === "shared") this.loadShared();
        if (id === "stats") this.loadStats();
        if (id === "dash" || id === "stats") this.$nextTick(this.drawCharts);
      },

      goSettingsTab: function (tab) {
        this.settingsTab = tab;
        this.go("settings");
      },

      /* ---------------- engine control ---------------- */
      restartEngine: async function () {
        if (this.coreWorking) return;
        this.coreWorking = true;
        this.engineBarNote = "";
        const op = this.engineRunning ? "restart" : "start";
        try {
          await window.EMU_API.core(op);
          this.ok(op === "restart" ? "engine.restarted" : "engine.banner.started");
          // 引擎起 EC 要几秒，轮询 health 直到 running:true 或超时
          let up = false;
          for (let i = 0; i < 20; i++) {
            await new Promise((r) => setTimeout(r, 1000));
            try {
              const h = await window.EMU_API.health();
              this.health = h || {};
              if (h && h.amule && h.amule.running && h.amule.ec) { up = true; break; }
            } catch (e) { /* 面板忙，继续等 */ }
          }
          if (up) {
            this.engineBarNote = "";
            this.ok("engine.state.running");
          } else {
            this.engineBarNote = (this.health && this.health.engine && this.health.engine.detail) ||
              this.t("engine.slowStart");
          }
          await this.bootstrapPanel();
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.coreWorking = false;
        }
      },

      startEngine: async function () {
        if (this.coreStarting) return;
        this.coreStarting = true;
        try {
          await window.EMU_API.core("start");
          this.ok("engine.banner.started");
          await new Promise((r) => setTimeout(r, 1200));
          await this.bootstrapPanel();
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.coreStarting = false;
        }
      },

      /* ---------------- tasks ---------------- */
      switchKind: function (k) {
        if (this.kind === k) return;
        this.kind = k;
        this.transfersData = { items: [], summary: {}, total: 0 };
        this.refresh(true);
      },
      setSort: function (key) {
        if (this.sortKey === key) this.sortAsc = !this.sortAsc;
        else { this.sortKey = key; this.sortAsc = key === "name"; }
      },
      toggleAll: function (checked) {
        this.selection = checked ? this.visibleTasks.map((it) => it.hash) : [];
      },
      togglePause: async function (it) {
        const action = FMT.isPaused(it) ? "resume" : "pause";
        try {
          await window.EMU_API.transferAction(it.hash, action);
          this.toast(this.t(action === "pause" ? "msg.paused" : "msg.resumed"));
          await this.refresh();
        } catch (e) {
          this.fail("err.opFailed", e);
        }
      },
      setPriority: async function (it, priority) {
        try {
          await window.EMU_API.transferAction(it.hash, "priority", priority);
          it.priority = priority;
          this.ok("msg.priorityUpdated");
        } catch (e) {
          this.fail("err.opFailed", e);
        }
      },
      bulk: async function (action) {
        const hashes = this.selection.slice();
        if (!hashes.length) return;
        try {
          await window.EMU_API.transferApply(hashes, action);
          this.toast(this.t("msg.submitted", { n: hashes.length }));
          this.selection = [];
          await this.refresh();
        } catch (e) {
          this.fail("err.opFailed", e);
        }
      },
      askCancel: function (list) {
        if (!list || !list.length) return;
        const self = this;
        this.confirmBox = {
          title: this.t("confirm.cancelTask"),
          text: list.length > 1
            ? this.t("confirm.many", { n: list.length })
            : this.t("confirm.one", { name: list[0].name }),
          okText: this.t("confirm.cancelTask"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.transferApply(list.map((x) => x.hash), "cancel");
              self.toast(self.t("msg.cancelled", { n: list.length }));
              self.selection = [];
              if (self.detail && list.some((x) => x.hash === self.detail.hash)) self.closeDetail();
              await self.refresh();
            } catch (e) {
              self.fail("err.opFailed", e);
            }
          },
        };
      },

      /* ---------------- add links ---------------- */
      openAdd: function () {
        this.addForm = { links: "", category: "", paused: !!(this.draft.engine && this.draft.engine.add_paused) };
        this.addOpen = true;
      },
      submitAdd: async function () {
        const links = (this.addForm.links || "").split(/\s*\n\s*/).map((s) => s.trim()).filter(Boolean);
        if (!links.length) { this.toast(this.t("add.empty"), "err"); return; }
        this.adding = true;
        try {
          const r = await window.EMU_API.addLinks(links, this.addForm.category, this.addForm.paused);
          const n = (r && r.added && r.added.length) || links.length;
          this.addOpen = false;
          this.toast(this.t("add.done", { n: n }));
          await this.refresh(true);
        } catch (e) {
          this.fail("add.failed", e);
        } finally {
          this.adding = false;
        }
      },

      /* ---------------- detail ---------------- */
      openDetail: function (hash) {
        const it = this.tasks.filter((x) => x.hash === hash)[0];
        if (!it) return;
        this.detail = it;
        this.detailHash = hash;
        this.detailTab = "info";
        this.detailData = { file: it, sources: [], chunks: [] };
        this.loadDetail(hash, false);
      },
      closeDetail: function () {
        this.detail = null;
        this.detailHash = "";
        this.detailData = { file: null, sources: [], chunks: [] };
      },
      selectDetailTab: function (tab) {
        this.detailTab = tab;
        if (this.detail && !(this.detailData.chunks || []).length) this.loadDetail(this.detail.hash, false);
      },
      loadDetail: async function (hash, silent) {
        if (!silent) this.detailLoading = true;
        try {
          const d = await window.EMU_API.transferDetail(hash);
          if (!d || this.detailHash !== hash) return;
          this.detailData = {
            file: (d && d.file) || this.detail,
            sources: (d && d.sources) || [],
            chunks: (d && d.chunks) || [],
          };
          if (d && d.file) this.detail = Object.assign({}, this.detail, d.file);
        } catch (e) {
          if (!silent) this.detailData = { file: this.detail, sources: [], chunks: [] };
        } finally {
          if (!silent) this.detailLoading = false;
        }
      },

      /* ---------------- servers ---------------- */
      loadServers: async function (silent) {
        try {
          const d = await window.EMU_API.servers();
          this.serversData = d || { items: [], current: null, total: 0, working: 0 };
        } catch (e) {
          if (!silent) this.fail("err.loadFailed", e);
        }
      },
      updateServerMet: async function () {
        if (this.serversUpdating) return;
        this.serversUpdating = true;
        try {
          await window.EMU_API.serversUpdate();
          await this.loadServers();
          this.toast(this.t("servers.updateOk", { n: this.serversData.total || 0 }));
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.serversUpdating = false;
        }
      },
      connectServer: async function (s) {
        const key = s.ip + ":" + s.port;
        this.connectingKey = key;
        try {
          await window.EMU_API.serverConnect(s.ip, s.port);
          await this.loadServers(true);
          await this.refresh();
          this.ok("msg.applied");
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.connectingKey = "";
        }
      },
      setServerPriority: async function (s, priority) {
        try {
          await window.EMU_API.serverPriority(s.ip, s.port, priority);
          s.priority = priority;
          this.ok("msg.priorityUpdated");
        } catch (e) {
          this.fail("err.opFailed", e);
        }
      },
      askRemoveServer: function (s) {
        const self = this;
        this.confirmBox = {
          title: this.t("servers.removeTitle"),
          text: this.t("servers.removeText", { name: s.name || s.ip, ip: s.ip, port: s.port }),
          okText: this.t("servers.remove"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.serverRemove(s.ip, s.port);
              await self.loadServers();
              self.ok("msg.saved");
            } catch (e) {
              self.fail("err.deleteFailed", e);
            }
          },
        };
      },
      openServerForm: function () {
        this.serverForm = { ip: "", port: 6082, name: "" };
      },
      saveServer: async function () {
        const f = this.serverForm;
        const ip = (f.ip || "").trim();
        const port = Number(f.port);
        if (!/^\d{1,3}(\.\d{1,3}){3}$/.test(ip)) { this.toast(this.t("err.needIp"), "err"); return; }
        if (!port || port < 1 || port > 65535) { this.toast(this.t("err.needPort"), "err"); return; }
        this.savingServer = true;
        try {
          await window.EMU_API.serverAdd(ip, port, (f.name || "").trim());
          this.serverForm = null;
          await this.loadServers();
          this.ok("msg.saved");
        } catch (e) {
          this.fail("err.saveFailed", e);
        } finally {
          this.savingServer = false;
        }
      },

      /* ---------------- search ---------------- */
      startSearch: async function () {
        const q = (this.query || "").trim();
        if (!q) { this.toast(this.t("err.needQuery"), "err"); return; }
        clearInterval(this.searchTimer);
        this.searchRunning = true;
        this.searchStarted = true;
        this.searchProgress = 0;
        this.searchResults = [];
        this.resultSelection = [];
        try {
          const r = await window.EMU_API.searchStart(q, this.searchKind, this.searchMethod);
          this.searchId = (r && r.search_id) || "";
          if (!this.searchId) throw new Error(this.t("search.startFailed"));
          this.searchTimer = setInterval(this.pollSearch, 1200);
        } catch (e) {
          this.searchRunning = false;
          this.fail("err.opFailed", e);
        }
      },
      pollSearch: async function () {
        if (!this.searchId) return;
        try {
          const d = await window.EMU_API.searchState(this.searchId);
          this.searchProgress = Math.max(0, Math.min(100, Number(d && d.progress) || 0));
          const prev = {};
          this.searchResults.forEach(function (r) { prev[r.hash] = r; });
          this.searchResults = ((d && d.results) || []).map(function (r) {
            const old = prev[r.hash];
            return Object.assign({}, r, { adding: old ? !!old.adding : false });
          });
          if (d && d.done) {
            this.searchProgress = 100;
            this.searchRunning = false;
            clearInterval(this.searchTimer);
            this.searchTimer = null;
          }
        } catch (e) {
          this.searchRunning = false;
          clearInterval(this.searchTimer);
          this.searchTimer = null;
        }
      },
      stopSearch: async function () {
        clearInterval(this.searchTimer);
        this.searchTimer = null;
        this.searchRunning = false;
        if (!this.searchId) return;
        try {
          await window.EMU_API.searchStop(this.searchId);
          this.ok("search.stopOk");
        } catch (e) {
          this.fail("err.opFailed", e);
        }
      },
      toggleAllResults: function () {
        if (this.allResultsSelected) this.resultSelection = [];
        else this.resultSelection = this.searchResults.filter((r) => !r.already).map((r) => r.hash);
      },
      downloadResult: async function (r) {
        if (r.already || r.adding) return;
        r.adding = true;
        try {
          await window.EMU_API.searchDownload(this.searchId, r.hash);
          r.already = true;
          this.ok("search.added");
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          r.adding = false;
        }
      },
      downloadSelectedResults: async function () {
        const list = this.selectedResults.filter((r) => !r.already);
        if (!list.length) return;
        this.downloadingResults = true;
        let okCount = 0;
        for (let i = 0; i < list.length; i++) {
          try {
            await window.EMU_API.searchDownload(this.searchId, list[i].hash);
            list[i].already = true;
            okCount++;
          } catch (e) { /* keep going, report at the end */ }
        }
        this.resultSelection = [];
        this.downloadingResults = false;
        this.toast(this.t("add.done", { n: okCount }));
      },

      /* ---------------- shared ---------------- */
      loadShared: async function () {
        try {
          const d = await window.EMU_API.shared();
          this.sharedData = d || { items: [], total: 0 };
        } catch (e) {
          this.fail("err.loadFailed", e);
        }
      },
      reloadShared: async function () {
        if (this.sharedReloading) return;
        this.sharedReloading = true;
        try {
          await window.EMU_API.sharedReload();
          await this.loadShared();
          this.ok("shared.reloadOk");
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.sharedReloading = false;
        }
      },

      /* ---------------- stats ---------------- */
      loadStats: async function () {
        this.statsLoading = true;
        try {
          const d = await window.EMU_API.stats();
          this.statsData = d || { groups: [], items: [] };
        } catch (e) {
          this.statsData = { groups: [], items: [] };
        } finally {
          this.statsLoading = false;
          this.$nextTick(this.drawCharts);
        }
      },

      /* ---------------- diagnostics ---------------- */
      loadDiagnostics: async function (force) {
        if (this.diagLoading) return;
        if (force) this.diagError = "";
        this.diagLoading = true;
        try {
          const d = await window.EMU_API.diagnostics();
          this.diag = d || null;
          this.diagError = "";
        } catch (e) {
          this.diagError = (e && e.message) || this.t("err.unknown");
          if (!this.diag) this.diag = null;
        } finally {
          this.diagLoading = false;
        }
      },
      checkIcon: function (level) {
        return level === "ok" ? "check" : level === "error" ? "close" : "alert";
      },
      firewallLabel: function () {
        const f = this.diagPorts.firewall || "unknown";
        const key = "diag.firewall." + f;
        const out = this.t(key);
        return out === key ? this.t("diag.firewall.unknown") : out;
      },
      /* clipboard API is unavailable over plain http on some WebViews, so fall
         back to a hidden textarea + execCommand and finally to a visible hint */
      copyText: async function (text) {
        const s = text === undefined || text === null ? "" : String(text);
        try {
          if (navigator.clipboard && navigator.clipboard.writeText) {
            await navigator.clipboard.writeText(s);
            this.toast(this.t("diag.copied"));
            return true;
          }
        } catch (e) { /* fall through to the legacy path */ }
        try {
          const ta = document.createElement("textarea");
          ta.value = s;
          ta.setAttribute("readonly", "");
          ta.style.position = "fixed";
          ta.style.top = "-1000px";
          ta.style.opacity = "0";
          document.body.appendChild(ta);
          ta.select();
          const ok = document.execCommand && document.execCommand("copy");
          document.body.removeChild(ta);
          if (ok) { this.toast(this.t("diag.copied")); return true; }
        } catch (e) { /* ignore */ }
        this.toast(this.t("diag.copyFailed"), "err");
        return false;
      },
      copyDiagReport: function () {
        const d = this.diag;
        if (!d) return;
        const s = d.summary || {};
        const e = this.diagEngine;
        const h = this.diagHost;
        const p = this.diagPorts;
        const L = [];
        L.push(this.t("diag.report.head") + " v" + (d.version || this.appVersion));
        if (d.checked_at) L.push(this.t("diag.report.checkedAt") + ": " + this.fmt.fmtDate(d.checked_at));
        L.push("");
        L.push(this.t("diag.report.summary") + ": " + (s.title || "") + (s.detail ? " - " + s.detail : ""));
        L.push("");
        L.push(this.t("diag.report.metrics") + ":");
        L.push("  " + this.t("diag.report.id") + ": " + this.diagEd2kLabel);
        L.push("  " + this.t("diag.report.server") + ": " + this.diagServerLabel);
        L.push("  " + this.t("diag.report.kad") + ": " + this.diagKadLabel + ", " + this.t("diag.metric.nodes", { n: this.fmt.fmtNum(e.kadNodes) }));
        L.push("  " + this.t("diag.report.tcp") + ": " + (e.tcpPort || "-") + " (" + (p.tcp_listening ? this.t("diag.metric.listening") : this.t("diag.metric.closed")) + ")");
        L.push("  " + this.t("diag.report.udp") + ": " + (e.udpPort || "-"));
        L.push("  " + this.t("diag.report.inbound") + ": " + e.inbound);
        L.push("  " + this.t("diag.lanIp") + ": " + (h.lan_ip || "-") + " / " + this.t("diag.gateway") + ": " + (h.gateway || "-"));
        L.push("  " + this.t("diag.publicIp") + ": " + (h.public_ip || h.public_ip_error || "-"));
        L.push("  " + this.t("diag.firewall") + ": " + this.firewallLabel() + (p.firewall_detail ? " (" + p.firewall_detail + ")" : ""));
        L.push("");
        L.push(this.t("diag.report.checks") + ":");
        (d.checks || []).forEach(function (c) {
          L.push("[" + String(c.level || "").toUpperCase() + "] " + (c.title || "") +
            (c.detail ? " - " + c.detail : "") + (c.action ? " => " + c.action : ""));
        });
        if ((d.suggestions || []).length) {
          L.push("");
          L.push(this.t("diag.report.suggestions") + ":");
          d.suggestions.forEach(function (sg, i) { L.push((i + 1) + ". " + sg); });
        }
        this.copyText(L.join("\n"));
      },
      /* aMule hands back raw numbers for counters; plain integers with 4+ digits
         read much better grouped, everything with a unit/time/ratio stays as-is */
      statValue: function (row) {
        const raw = row ? row.value : "";
        const s = raw === undefined || raw === null ? "" : String(raw);
        if (/^\d{4,}$/.test(s)) {
          const n = Number(s);
          if (isFinite(n)) return n.toLocaleString("zh-CN");
        }
        return s;
      },
      statName: function (row) {
        let s = row && (row.name_zh || row.name) ? (row.name_zh || row.name) : "";
        s = String(s).replace(/\s*:\s*%s\s*$/, "").replace(/%s/g, "").replace(/\s*:\s*$/, "");
        return s.trim();
      },
      statGroupLabel: function (row) {
        const raw = String((row && (row.group_zh || row.group)) || "");
        if (!raw) return this.t("stats.groupRoot");
        if (raw.indexOf(" / ") < 0) return raw;
        const parts = raw.split(" / ");
        if (parts[0] === "Statistics" || parts[0] === "\u7edf\u8ba1") parts.shift();
        return parts.length ? parts.join(" / ") : this.t("stats.groupRoot");
      },
      notifyTypeLabel: function (type) {
        if (!type) return "";
        const meta = this.notifyTypeMeta[type];
        if (meta) {
          const lab = (this.lang === "en") ? (meta.label_en || meta.label) : (meta.label_zh || meta.label);
          if (lab) return lab;
        }
        const key = "settings.notify.type." + type;
        const out = this.t(key);
        return out === key ? type : out;
      },
      /* ---------------- logs ---------------- */
      loadLogs: async function (silent) {
        if (this.logsLoading) return;
        this.logsLoading = true;
        try {
          // 取后端允许的上限，而不是固定 200：更早的记录本来就在服务端，
          // 拿得回来却只请求 200 条，等于人为把历史截断。
          const d = await window.EMU_API.logs(LOG_FETCH_LIMIT);
          const items = (d && d.items) || (Array.isArray(d) ? d : []);
          this.logs = items.map(function (l) {
            return {
              t: l.t || l.timestamp || 0,
              level: (l.level || "info").toLowerCase(),
              text: l.text || l.message || "",
              source: l.source || "engine",
            };
          });
          if (this.logAuto) this.$nextTick(this.jumpToLogEnd);
        } catch (e) {
          if (!silent) this.logs = [];
        } finally {
          this.logsLoading = false;
        }
      },
      clearLogs: function () {
        this.logs = [];
        this.logCleared = true;
        this.ok("logs.cleared");
      },
      jumpToLogEnd: function () {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = box.scrollHeight;
      },

      /* ---------------- settings ---------------- */
      loadSettings: async function () {
        try {
          const d = await window.EMU_API.settings();
          const s = (d && d.settings) || d || {};
          const base = emptySettings();
          const merged = Object.assign(base, s);
          merged.panel = Object.assign(base.panel, s.panel || {});
          merged.engine = Object.assign(base.engine, s.engine || {});
          merged.bootstrap = Object.assign(base.bootstrap, s.bootstrap || {});
          merged.notify = Object.assign(base.notify, s.notify || {});
          merged.notify.events = Object.assign({ complete: true, error: true }, (s.notify && s.notify.events) || {});
          merged.backup = Object.assign(base.backup, s.backup || {});
          merged.update = Object.assign(base.update, s.update || {});
          if (!Array.isArray(merged.engine.shared_dirs)) merged.engine.shared_dirs = [];
          this.settings = clone(merged);
          this.saved = clone(merged);
          this.draft = clone(merged);
          if (merged.panel.lang === "en" || merged.panel.lang === "zh") {
            if (!new URLSearchParams(location.search).get("lang")) {
              this.lang = merged.panel.lang;
              this._tc = I18N.makeT(this.lang);
              this._tlang = this.lang;
              document.documentElement.setAttribute("lang", this.lang === "zh" ? "zh-CN" : "en");
            }
          }
          this.draft.panel.lang = this.lang;
        } catch (e) {
          this.fail("settings.loadFailed", e);
        }
      },
      /* 主题 / 语言这类即时生效的偏好，切换后静默落盘。
         调用方各自会弹自己的提示（"已切换到夜间模式""界面语言已切换"），
         这里再弹一条"设置已保存"就是同一动作两条提示。 */
      persistDraft: async function () {
        try {
          this.settingsSaving = true;
          await window.EMU_API.saveSettings(this.draft);
          this.settings = clone(this.draft);
          this.saved = clone(this.draft);
          this.applyTheme();
        } catch (e) {
          this.fail("settings.saveFailed", e);
        } finally {
          this.settingsSaving = false;
          this.coreWorking = false;
          this.engineBarNote = "";
        }
      },
      saveSettingsDraft: async function () {
        if (this.settingsSaving) return;
        const localRestart = this.restartNeeded;
        this.settingsSaving = true;
        try {
          const res = await window.EMU_API.saveSettings(this.draft);
          if (res && res.settings) {
            this.settings = res.settings;
            this.saved = clone(res.settings);
            this.draft = clone(res.settings);
          } else {
            this.settings = clone(this.draft);
            this.saved = clone(this.draft);
          }
          this.applyTheme();
          if (res && res.warnings && res.warnings.length) {
            this.toast(String(res.warnings[0]), "err");
          }
          const restart = (res && res.restart_required !== undefined) ? !!res.restart_required : localRestart;
          if (restart) {
            this.ok("settings.restartHint");
            this.engineBarNote = this.t("settings.restartWatch");
            setTimeout(() => { this.bootstrapPanel().then(() => {
              // 引擎重启是异步的，2.5s 往往还没就绪，继续轮询到 running
              let n = 0;
              const poll = setInterval(async () => {
                n++;
                try {
                  const h = await window.EMU_API.health();
                  this.health = h || {};
                  if (h && h.amule && h.amule.running && h.amule.ec) {
                    clearInterval(poll);
                    this.engineBarNote = "";
                    this.ok("engine.state.running");
                  }
                } catch (e) { /* ignore */ }
                if (n >= 20) { clearInterval(poll); }
              }, 1000);
            }); }, 2500);
          } else {
            this.ok("settings.saved");
            this.engineBarNote = "";
          }
          await this.loadPrefs();
        } catch (e) {
          this.fail("settings.saveFailed", e);
        } finally {
          this.settingsSaving = false;
        }
      },
      resetSettings: function () {
        this.draft = clone(this.saved);
        this.applyTheme();
      },
      addSharedDir: function () {
        const v = (this.newSharedDir || "").trim();
        if (!v) return;
        if (this.draft.engine.shared_dirs.indexOf(v) < 0) this.draft.engine.shared_dirs.push(v);
        this.newSharedDir = "";
      },
      removeSharedDir: function (i) {
        this.draft.engine.shared_dirs.splice(i, 1);
      },
      loadPrefs: async function () {
        try {
          this.prefs = await window.EMU_API.prefs();
        } catch (e) { /* prefs are advisory only */ }
      },
      updateBootstrap: async function () {
        if (this.bootstrapping) return;
        this.bootstrapping = true;
        try {
          await window.EMU_API.serversUpdate();
          try { await window.EMU_API.kadBootstrap(); } catch (e) { /* kad may be disabled */ }
          this.draft.bootstrap.last_update = Math.floor(Date.now() / 1000);
          this.saved.bootstrap.last_update = this.draft.bootstrap.last_update;
          this.ok("settings.boot.updateOk");
          await this.refresh(true);
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.bootstrapping = false;
        }
      },

      /* ---------------- notifications ---------------- */
      loadNotify: async function () {
        try {
          const r = await window.EMU_API.notify();
          if (r && r.settings) {
            this.draft.notify = Object.assign({}, this.draft.notify, r.settings);
            this.saved.notify = clone(this.draft.notify);
          }
          this.notifyChannels = (r && r.channels) || [];
          if (r && r.types && r.types.length) {
            this.notifyTypes = r.types.map(function (x) { return typeof x === "string" ? x : x.type; })
              .filter(function (x) { return !!x; });
            this.notifyTypeMeta = {};
            const self = this;
            r.types.forEach(function (x) {
              if (x && x.type) self.notifyTypeMeta[x.type] = x;
            });
          }
        } catch (e) { /* the section stays empty */ }
      },
      saveNotifyFlag: async function (key, val) {
        this.draft.notify[key] = val;
        try {
          const r = await window.EMU_API.notifySettings(this.draft.notify);
          if (r && r.settings) this.draft.notify = Object.assign({}, this.draft.notify, r.settings);
          this.saved.notify = clone(this.draft.notify);
          this.ok("msg.saved");
        } catch (e) {
          this.fail("err.saveFailed", e);
        }
      },
      saveNotifyEvent: async function (key, val) {
        this.draft.notify.events = Object.assign({}, this.draft.notify.events);
        this.draft.notify.events[key] = val;
        await this.saveNotifyFlag("events", this.draft.notify.events);
      },
      openChannelForm: function (ch) {
        const type = ch ? ch.type : (this.notifyTypes[0] || "bark");
        const cfg = {};
        (CHANNEL_FIELDS[type] || []).forEach(function (k) { cfg[k] = ""; });
        if (ch && ch.config) Object.keys(cfg).forEach(function (k) { if (ch.config[k]) cfg[k] = ch.config[k]; });
        this.channelForm = {
          id: ch ? ch.id : "",
          name: ch ? ch.name : "",
          type: type,
          enabled: ch ? ch.enabled !== false : true,
          config: cfg,
        };
        this.ensureChannelFields(type);
      },
      ensureChannelFields: function (type) {
        if (!this.channelForm) return;
        const meta = this.notifyTypeMeta[type];
        const names = (meta && meta.fields && meta.fields.length) ? meta.fields : (CHANNEL_FIELDS[type] || []);
        const cfg = this.channelForm.config;
        names.forEach(function (k) {
          if (cfg[k] === undefined || cfg[k] === null) cfg[k] = "";
        });
      },
      saveChannel: async function () {
        if (this.savingChannel || !this.channelForm) return;
        this.savingChannel = true;
        const f = this.channelForm;
        try {
          await window.EMU_API.notifyChannel({
            id: f.id, name: f.name, type: f.type, enabled: f.enabled, config: f.config,
          });
          this.channelForm = null;
          await this.loadNotify();
          this.ok("msg.saved");
        } catch (e) {
          this.fail("err.saveFailed", e);
        } finally {
          this.savingChannel = false;
        }
      },
      testChannel: async function (ch) {
        this.testingChannel = ch.id;
        try {
          const r = await window.EMU_API.notifyTest(ch.id);
          if (r && r.ok === false) throw new Error((r && r.error) || this.t("err.unknown"));
          this.toast(this.t("settings.notify.testOk", { name: ch.name }));
        } catch (e) {
          this.fail("settings.notify.testFail", e);
        } finally {
          this.testingChannel = "";
        }
      },
      askRemoveChannel: function (ch) {
        const self = this;
        this.confirmBox = {
          title: this.t("settings.notify.removeTitle"),
          text: this.t("settings.notify.removeText", { name: ch.name }),
          okText: this.t("settings.notify.remove"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.notifyChannel({ id: ch.id, remove: true });
              await self.loadNotify();
              self.ok("msg.saved");
            } catch (e) {
              self.fail("err.deleteFailed", e);
            }
          },
        };
      },

      /* ---------------- backup ---------------- */
      loadBackup: async function () {
        try {
          const d = await window.EMU_API.backupStatus();
          this.backupData = d || { items: [] };
        } catch (e) { /* keep the previous list */ }
      },
      runBackup: async function () {
        if (this.backupRunning) return;
        this.backupRunning = true;
        try {
          const r = await window.EMU_API.backupRun();
          const name = (r && (r.name || r.path)) ? String(r.name || r.path).split(/[\\/]/).pop() : "";
          this.toast(this.t("settings.backup.done", { name: name }));
          await this.loadBackup();
        } catch (e) {
          this.fail("err.opFailed", e);
        } finally {
          this.backupRunning = false;
        }
      },
      askRestoreBackup: function (b) {
        const self = this;
        this.confirmBox = {
          title: this.t("settings.backup.restoreTitle"),
          text: this.t("settings.backup.restoreText", { name: b.name }),
          okText: this.t("settings.backup.restore"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.backupRestore(b.name);
              self.ok("settings.backup.restoreOk");
              setTimeout(function () { location.reload(); }, 1200);
            } catch (e) {
              self.fail("err.opFailed", e);
            }
          },
        };
      },
      askDeleteBackup: function (b) {
        const self = this;
        this.confirmBox = {
          title: this.t("settings.backup.deleteTitle"),
          text: this.t("settings.backup.deleteText", { name: b.name }),
          okText: this.t("settings.backup.delete"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.backupDelete(b.name);
              self.ok("settings.backup.deleted");
              await self.loadBackup();
            } catch (e) {
              self.fail("err.deleteFailed", e);
            }
          },
        };
      },

      /* ---------------- update ---------------- */
      /* 跳到设置页的更新分区（全局提示条的"查看详情"） */
      openUpdateSection: function () {
        this.goSettingsTab("update");
      },
      /* 关掉全局更新提示条：只在本次会话生效，重新打开面板会再提示 */
      dismissUpdateBanner: function () {
        this.updateBanner = false;
      },
      /* 发布仓库名，取自设置里的 update.repo；拿不到就退回默认值 */
      updateRepoLabel: function () {
        const fromInfo = this.updateInfo && this.updateInfo.repo;
        const fromCfg = this.draft && this.draft.update && this.draft.update.repo;
        return fromInfo || fromCfg || "Smi13zZ/fn-emule";
      },
      checkUpdate: async function (force) {
        if (this.updateChecking) return;
        this.updateChecking = true;
        this.updateError = "";
        try {
          const r = await window.EMU_API.updateCheck(!!force);
          this.updateInfo = r || null;
          if (r && r.error) this.updateError = this.t("settings.update.failed", { v: r.error });
        } catch (e) {
          this.updateError = this.t("settings.update.failed", { v: (e && e.message) || "" });
        } finally {
          this.updateChecking = false;
        }
      },
      askInstallUpdate: function () {
        const self = this;
        const v = (this.updateInfo && this.updateInfo.latest) || "";
        this.confirmBox = {
          title: this.t("settings.update.install"),
          text: this.t("settings.update.confirm", { v: v }),
          okText: this.t("settings.update.install"),
          onOk: async function () {
            self.confirmBox = null;
            self.runInstall();
          },
        };
      },
      /* 一键更新：面板在后台下载 + 校验 + 生成升级脚本，这里轮询进度。
         弹窗一直留着，直到面板被新版本替换、页面自动重连成功为止。 */
      runInstall: async function () {
        if (this.updateInstalling) return;
        this.updateInstalling = true;
        this.updateError = "";
        this.updateDownloaded = null;
        this.updateProgress = { percent: 0, phase: "downloading", received: 0, total: 0 };
        this.updateInstallDetail = this.t("settings.update.installingDownload");
        this._updateFromVersion = this.appVersion;
        try {
          const r = await window.EMU_API.installUpdate();
          if (r && r.ok === false) throw new Error(r.error || "");
          if (r && r.task) this.applyUpdateTask(r.task);
          this.pollUpdateProgress(r && r.version ? r.version : "");
        } catch (e) {
          this.updateInstalling = false;
          this.updateError = this.t("settings.update.installFailed", { v: (e && e.message) || "" });
        }
      },
      applyUpdateTask: function (task) {
        if (!task) return;
        this.updateProgress = {
          percent: Number(task.percent) || 0,
          phase: task.phase || "downloading",
          received: Number(task.received) || 0,
          total: Number(task.total) || 0,
        };
        const pct = this.updateProgress.percent;
        if (task.phase === "downloading") {
          this.updateInstallDetail = this.t("settings.update.installingDownload") + " " + pct + "%";
        } else if (task.phase === "verifying") {
          this.updateInstallDetail = this.t("settings.update.verifying");
        } else if (task.phase === "installing" || task.phase === "restarting") {
          this.updateInstallDetail = this.t("settings.update.installingWait");
        }
      },
      pollUpdateProgress: function (targetVersion) {
        const self = this;
        let misses = 0;
        const tick = async function () {
          // 面板被卸载/重启期间接口会连续失败若干次，这是升级的正常过程，
          // 不能一失败就当出错 —— 只要它还会回来，就继续等。
          try {
            const r = await window.EMU_API.updateProgress();
            misses = 0;
            self.applyUpdateTask(r && r.task);
            const task = (r && r.task) || {};
            if (task.phase === "error") {
              self.updateInstalling = false;
              self.updateError = self.t("settings.update.installFailed",
                { v: task.error || "" });
              return;
            }
            // 新版本已上线：面板报告的版本号已经不再是安装前那个版本了。
            // 用"和起始版本不同"判断，比依赖精确匹配目标版本号更耐得住
            // Release 里 tag 带前缀、或资产名与版本号不完全一致的情况。
            if (r && r.version && self._updateFromVersion &&
                r.version !== self._updateFromVersion) {
              self.finishUpdate(r.version);
              return;
            }
          } catch (e) {
            misses += 1;
            // 面板可能正在被替换，期间连不上是正常的；超时太久才报错
            if (misses > 180) {
              self.updateInstalling = false;
              self.updateError = self.t("settings.update.installFailed",
                { v: self.t("settings.update.timeout") });
              return;
            }
          }
          setTimeout(tick, 1000);
        };
        setTimeout(tick, 800);
      },
      /* 新版本装好了：进度拉满、给个提示，然后整体重新加载页面。
         面板在升级过程中被卸载重装，前端的内存状态（版本号、设置、路由）
         都还是旧的，只刷新数据不够 —— 重载一次让页面跑在新版本上。 */
      finishUpdate: function (version) {
        const self = this;
        this.updateProgress.percent = 100;
        this.updateInstallDetail = this.t("settings.update.done", { v: version || "" });
        this.ok("settings.update.done", { v: version || "" });
        setTimeout(function () {
          self.updateInstalling = false;
          // 面板刚从卸载重装里回来，等它把引擎也拉起来
          self.bootstrapPanel().catch(function () {});
          setTimeout(function () { location.reload(); }, 1500);
        }, 1500);
      },

      /* ---------------- charts ---------------- */
      sparkTick: function () {
        if (this.view === "dash" || this.view === "stats") {
          const s = this.speed;
          this.pushChart(this.view === "dash" ? this.speedChart : this.statsChart,
            s.down || 0, s.up || 0);
          this.drawCharts();
        }
      },
      pushChart: function (chart, dl, ul) {
        if (chart) chart.push(dl, ul);
      },
      drawCharts: function () {
        if (this.view === "dash") {
          if (this.$refs.speedCanvas) {
            if (!this.speedChart) this.speedChart = new CHART.SpeedChart(this.$refs.speedCanvas, 90);
            else this.speedChart.attach(this.$refs.speedCanvas);
            this.speedChart.draw();
          }
          if (this.$refs.donutCanvas) {
            CHART.drawDonut(this.$refs.donutCanvas, this.statusSegments,
              this.counters.downloads || 0, this.t("nav.tasks"));
          }
        }
        if (this.view === "stats") {
          if (this.$refs.statsCanvas) {
            if (!this.statsChart) this.statsChart = new CHART.SpeedChart(this.$refs.statsCanvas, 90);
            else this.statsChart.attach(this.$refs.statsCanvas);
            this.statsChart.draw();
          }
        }
      },
    },
  }).mount("#app");
})();
