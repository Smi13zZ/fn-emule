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
    settings: svg('<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.6a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>'),
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
  /* 页面开着的时候每隔这么久刷新一次更新状态；后端有 900 秒缓存，
     真正打到 GitHub 的请求最多每 15 分钟一次，不会把匿名额度耗光。 */
  const UPDATE_CHECK_MS = 30 * 60 * 1000;
  /* 与后端 /api/log 的上限（2000）对齐 */
  const LOG_FETCH_LIMIT = 2000;
  const BACKUP_ROWS = 5;
  /* 投递记录卡片只锁前 5 行的高度，再多就在卡片内滚 */
  const NOTIFY_LOG_ROWS = 5;
  const NOTIFY_LOG_GAP = 8;

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
      notify: { enabled: false, channels: [], events: { complete: true, error: true, update: true } },
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

        search: "",
        filter: "all",
        filters: ["all", "downloading", "uploading", "waiting", "paused", "complete", "error"],
        sortKeys: ["added", "kind", "name", "size", "percent", "speed", "eta"],
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
        // 默认「全局」（服务器 + Kad）。服务器不回应时后端会自动补搜一次 Kad，
        // 结果照样显示，只是上面多一条说明。
        searchKind: "global",
        searchKinds: ["server", "kad", "global"],
        searchMethod: "name",
        searchMethods: ["name", "hash"],
        searchId: "",
        searchWarn: "",
        searchCounts: { total: 0, local: 0, queued: 0 },
        searchRunning: false,
        searchProgress: 0,
        searchResults: [],
        searchStarted: false,
        resultSelection: [],
        downloadingResults: false,
        searchTimer: null,

        sharedData: { items: [], total: 0, scan: {}, progress: {} },
        sharedReloading: false,
        // 扫描进行中时后台轮询进度用
        sharedScanTimer: null,
        sharedProgress: { running: false, engine_count: 0, shared_total: 0, scan_dirs: 0 },

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
        /* 换了临时目录后，旧目录里还留着已有任务的 .part；非空就在设置页给出迁移入口 */
        tempMigrateFrom: "",
        tempMigrating: false,
        bootstrapping: false,

        notifyChannels: [],
        notifyTypes: ["bark", "serverchan", "pushplus", "wxpusher", "webhook"],
        notifyTypeMeta: {},
        channelForm: null,
        savingChannel: false,
        testingChannel: "",
        /* 投递记录：最新在前，来自 var/history/notify-log.json */
        notifyLog: [],
        notifyLogTotal: 0,
        notifyLogMax: 500,
        notifyLogLoading: false,
        notifyLogFilter: "all",
        clearingNotifyLog: false,
        notifyLogHeight: 0,

        autoStatus: {},
        autoForm: { enabled: false, interval: 24, retention: 7 },
        backupFile: null,
        backupsVisible: BACKUP_ROWS,

        storageData: { items: [], total: 0, updates: [] },
        storageLoading: false,
        storageBusy: "",

        updateInfo: null,
        updateChecking: false,
        updateInstalling: false,
        updateError: "",
        updateInstallDetail: "",
        /* 安装日志尾部：服务端每次轮询都带着它。只在失败时展示 —— 升级途中
           这堆输出用户看不懂也帮不上忙，失败时它是唯一能说清卡在哪一步的证据。 */
        updateInstallLog: "",
        /* 全局失败提示条：从任意页面发起更新都可能失败，那时用户不在设置页，
           只在设置卡片里显示等于什么都没说。带「查看详情」并单独可关。 */
        updateFailText: "",
        /* 全局更新提示条：发现新版本后在每个页面顶部提示，关掉后本次会话不再出现 */
        updateBanner: true,
        /* 一键更新的下载进度（后台任务轮询回来的） */
        updateProgress: { percent: 0, phase: "idle", received: 0, total: 0 },
        /* 阶段单调性只在同一轮尝试内成立：attempt 变了就要整体重置，
           否则上一轮停在 installing、这一轮从 checking 开始会被判成后退。 */
        updateMonoAttempt: -1,
        /* 自动重试刷新超过 10 次后放出的自救按钮：浏览器若已停在错误页上，
           自动重试是回不来的，至少留一个能自己点的入口。 */
        updateReloadReady: false,
        /* 服务端每次尝试递增的编号。失败状态在服务端会一直留着，界面靠它
           区分「上一轮的死信」与「本轮真的失败了」。 */
        updateAttempt: 0,
        /* 这次升级有没有备好回滚包。false 时提示不能继续承诺「会自动回滚」。 */
        updateRollbackReady: false,
        /* 上一次发起版本检查的时刻（毫秒）。切回窗口时按它判断要不要补查 */
        lastUpdateCheckAt: 0,
        /* 正在更新到的目标版本号，用于弹窗标题 */
        updateTargetVersion: "",
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
          { id: "backup", label: t("settings.tab.maintenance") },
          { id: "storage", label: t("settings.tab.storage") },
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
      visibleTasks: function () {
        const self = this;
        const q = this.search.trim().toLowerCase();
        let list = this.tasks.filter(function (it) {
          if (q && (it.name || "").toLowerCase().indexOf(q) < 0 &&
              (it.category || "").toLowerCase().indexOf(q) < 0) return false;
          // 「全部」= 我添加过的所有下载任务（下载中/等待/暂停/完成/出错），
          // 不含上传：上传列表里一条 = 一个正在从我这拿数据的 peer 会话，
          // 不是任务，混进来只会让列表看着一堆莫名其妙的空档。
          if (self.filter === "all") return it.kind !== "upload";
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
          // "kind" groups every download together and every upload together,
          // which is what people expect from one merged list.
          if (key === "kind") { x = a.kind === "upload" ? 1 : 0; y = b.kind === "upload" ? 1 : 0; }
          else if (key === "added") { x = a.added; y = b.added; }
          else { x = a[key]; y = b[key]; }
          return ((Number(x) || 0) - (Number(y) || 0)) * dir;
        });
        return list;
      },
      /* Only download rows carry a checkbox: an upload row is a peer session that
         is currently pulling from us, not a queued job that can be paused or
         deleted. Mixing them into select-all made the header checkbox look
         half-broken, so the selectable set is downloads-only. */
      selectableTasks: function () {
        return this.visibleTasks.filter(function (it) { return it.kind !== "upload"; });
      },
      allSelected: function () {
        const list = this.selectableTasks;
        return list.length > 0 && this.selection.length === list.length;
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
          { key: "uploading", label: t("tasks.filter.uploading"), color: CHART.cssVar("--ul", "#02b8cc"), n: 0 },
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
        // logs 已是「最新在上」顺序，最近 6 条就是头 6 条
        return this.logs.slice(0, 6);
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
      /* ---- 投递记录筛选 ---- */
      notifyLogShown: function () {
        const f = this.notifyLogFilter;
        if (f === "ok") return this.notifyLog.filter(function (r) { return r.ok; });
        if (f === "fail") return this.notifyLog.filter(function (r) { return !r.ok; });
        return this.notifyLog;
      },
      notifyLogFailed: function () {
        return this.notifyLog.filter(function (r) { return !r.ok; }).length;
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
      /* 有没有可测的总字节数：下载阶段有，安装/等待重启阶段没有 */
      updateProgressKnown: function () {
        return this.updateProgress.total > 0;
      },
      /* 已下载字节占总量的百分比，落到 0..100 的整数 */
      updateProgressPct: function () {
        const total = this.updateProgress.total;
        if (!total) return 0;
        const raw = (this.updateProgress.received / total) * 100;
        return Math.round(Math.max(0, Math.min(100, raw)));
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
      settingsTab: function (v) {
        if (v === "update" && !this.updateInfo) this.checkUpdate(false);
        if (v === "notify") {
          if (!this.notifyChannels.length) this.loadNotify();
          this.loadNotifyLog();
        }
        if (v === "backup") this.loadBackupStatus();
        if (v === "storage") this.loadStorage();
      },
      notifyLogFilter: function () { this.$nextTick(this.measureNotifyLog); },
      lang: function () { this.$nextTick(this.measureNotifyLog); },
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
      /* 面板一直开着也要能跟上版本：定时刷新 + 切回窗口时按需补查。
         两者都走非强制检查（checkUpdate(false)），命中后端缓存就不发网络请求。 */
      this._updateTimer = setInterval(() => { this.checkUpdate(false); }, UPDATE_CHECK_MS);
      this._onVisibility = () => {
        if (document.hidden) return;
        const since = Date.now() - (this.lastUpdateCheckAt || 0);
        if (since >= UPDATE_CHECK_MS) this.checkUpdate(false);
      };
      document.addEventListener("visibilitychange", this._onVisibility);
    },

    beforeUnmount: function () {
      clearInterval(this._sparkTimer);
      clearInterval(this._tickTimer);
      clearInterval(this.searchTimer);
      clearInterval(this.installTimer);
      clearInterval(this._updateTimer);
      this.stopSharedScanWatch();
      document.removeEventListener("visibilitychange", this._onVisibility);
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
        this._tickTimer = setInterval(this.tick, 1000);
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
          const tasks = await window.EMU_API.transfers();
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
        // 离开搜索页就停掉结果核对轮询：它每轮都要按结果条数去共享列表
        // 核对磁盘，留在后台空转只会白白打引擎。回到搜索页时若搜索已结束
        // 且有结果，重新拉一次即可（数据本身没变，只是状态核对）。
        if (id !== "search" && !this.searchRunning && this.searchTimer) {
          clearInterval(this.searchTimer);
          this.searchTimer = null;
        }
        if (id === "search" && !this.searchRunning && !this.searchTimer && this.searchResults.length) {
          this.searchTimer = setInterval(this.pollSearch, 8000);
        }
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
      setSort: function (key) {
        if (this.sortKey === key) this.sortAsc = !this.sortAsc;
        else { this.sortKey = key; this.sortAsc = key === "name"; }
      },
      toggleAll: function (checked) {
        this.selection = checked ? this.selectableTasks.map((it) => it.hash) : [];
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

      /* Deleting a transfer is not the same thing as cancelling it: the .part
         data can stay on disk so the same eD2k link picks up where it left off.
         The checkbox in the confirm box is therefore opt-in (unchecked = keep). */
      askDelete: function (list) {
        if (!list || !list.length) return;
        const self = this;
        this.confirmBox = {
          title: this.t("delete.title"),
          text: list.length > 1
            ? this.t("delete.many", { n: list.length })
            : this.t("delete.one", { name: list[0].name }),
          check: {
            label: this.t("delete.withData"),
            hint: this.t("delete.keepHint"),
            value: false,
          },
          okText: this.t("delete.ok"),
          onOk: function (box) {
            self.confirmBox = null;
            const withData = !!(box && box.check && box.check.value);
            self.doDelete(list, withData);
          },
        };
      },
      doDelete: async function (list, withData) {
        const hashes = list.map(function (x) { return x.hash; });
        try {
          const r = await window.EMU_API.transferDelete(hashes, !!withData);
          const n = (r && r.count) || hashes.length;
          // 删完立刻把搜索结果对一遍：删的那个文件马上变回「下载」，
          // 不用切页、不用重搜、不用刷新。
          this.refreshSearchQuiet();
          // When the data is kept the backend reports the folder it moved the
          // .part files into; one hint is enough, no per-row listing.
          const kept = (r && r.results || []).filter(function (x) { return x && x.kept; })[0];
          const msg = this.t("delete.done", { n: n });
          this.toast(kept ? msg + " · " + this.t("delete.kept", { path: kept.kept }) : msg);
          this.selection = [];
          if (this.detail && list.some((x) => x.hash === this.detail.hash)) this.closeDetail();
          await this.refresh();
        } catch (e) {
          this.fail("err.deleteFailed", e);
        }
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
        // An upload row is a peer session, not a partfile: /transfers/{hash} only
        // knows download entries, so asking it would just fail and blank the
        // drawer. Everything worth showing is already on the row itself.
        if (it.kind !== "upload") this.loadDetail(hash, false);
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
        this.searchWarn = "";
        this.searchCounts = { total: 0, local: 0, queued: 0 };
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
          // 后端会带 warn（server_no_response / search_stalled_no_result）。
          // 必须让用户看见，否则「搜不到」会被当成软件坏了。
          this.searchWarn = d && d.warn ? String(d.warn) : "";
          this.searchCounts = (d && d.counts) || { total: 0, local: 0, queued: 0 };
          const prev = {};
          this.searchResults.forEach(function (r) { prev[r.hash] = r; });
          this.searchResults = ((d && d.results) || []).map(function (r) {
            const old = prev[r.hash];
            return Object.assign({}, r, { adding: old ? !!old.adding : false });
          });
          if (d && d.done) {
            this.searchProgress = 100;
            this.searchRunning = false;
            // 搜索结束≠结果冻结：用户可能去任务页把某个文件删了再回来。
            // 所以不停止轮询，改成低频继续核对 —— 删掉之后这里会自动
            // 变回「下载」，不用重新搜索，也不用刷新页面。
            // 但只在「搜索页正开着、且确实有结果」时才继续：每条结果都要跟
            // 共享列表核对一次，空页面或切走之后继续打引擎纯属浪费。
            if (this.searchTimer) {
              clearInterval(this.searchTimer);
              this.searchTimer = null;
              if (this.searchResults.length) {
                this.searchTimer = setInterval(this.pollSearch, 8000);
              }
            }
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
      // 复制本地文件路径。页面是 http 访问的（不是 https），navigator.clipboard
      // 在非安全上下文里不可用，所以必须带一个临时输入框的兜底写法。
      // 极端兜底：所有复制方式都失败时，才弹框让用户自己按 Ctrl+C
      manualCopy: function (text) {
        try {
          const r = window.prompt(this.t("search.copyPathManual"), text);
          // prompt 在部分内嵌 WebView / 无头环境下直接返回 null 且不抛异常，
          // 用户会以为已经复制了。这时退回 toast，把路径本身显示出来。
          if (r === null || r === undefined) this.toast(text, "warn");
        } catch (e) {
          this.toast(text, "warn");
        }
      },
      copyLocalPath: function (r) {
        const text = (r && (r.local_path || r.name)) || "";
        if (!text) { this.toast(this.t("search.copyEmpty"), "warn"); return; }
        const done = () => this.ok("search.pathCopied");
        // 局域网 http 页面属于「非安全上下文」：navigator.clipboard 是 undefined。
        // 但旧的 execCommand("copy") 在这种页面里仍然有效 —— 前提是它必须在
        // 用户点击的回调里**同步**执行。
        const legacy = () => {
          let ta = null;
          try {
            ta = document.createElement("textarea");
            ta.value = text;
            ta.setAttribute("readonly", "");
            ta.style.cssText = "position:fixed;left:-9999px;top:0;opacity:0";
            document.body.appendChild(ta);
            ta.focus();
            ta.select();
            ta.setSelectionRange(0, text.length);
            const okCopy = document.execCommand("copy");
            if (okCopy) done();
            else this.manualCopy(text);
          } catch (e) {
            this.manualCopy(text);
          } finally {
            if (ta && ta.parentNode) ta.parentNode.removeChild(ta);
          }
        };
        if (navigator.clipboard && window.isSecureContext) {
          navigator.clipboard.writeText(text).then(done).catch(legacy);
        } else {
          legacy();
        }
      },
      // 静默重取一次搜索结果（只更新状态，不弹提示、不动进度条）
      refreshSearchQuiet: async function () {
        if (!this.searchId || !this.searchResults.length) return;
        try {
          const d = await window.EMU_API.searchState(this.searchId);
          if (!d || !d.results) return;
          const prev = {};
          this.searchResults.forEach(function (x) { prev[x.hash] = x; });
          this.searchResults = d.results.map(function (x) {
            const old = prev[x.hash];
            return Object.assign({}, x, { adding: old ? !!old.adding : false });
          });
          this.searchCounts = d.counts || this.searchCounts;
          if (d.warn !== undefined) this.searchWarn = d.warn ? String(d.warn) : "";
        } catch (e) {
          // 静默失败：不能因为刷新状态出错就去打扰用户。
          // 但会话过期（后端返回「搜索会话不存在」）时旧告警会一直挂在页面上，
          // 那是一条已经失效的提示，跟着结果一起清掉更诚实。
          this.searchWarn = "";
        }
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
      loadShared: async function (force) {
        try {
          const d = await window.EMU_API.shared(!!force);
          this.sharedData = d || { items: [], total: 0, scan: {}, progress: {} };
          this.sharedProgress = (d && d.progress) || { running: false };
          // 后台扫描还在跑就跟着轮询，页面自己会看到条数往上涨
          if (this.sharedProgress.running) this.startSharedScanWatch();
        } catch (e) {
          this.fail("err.loadFailed", e);
        }
      },
      reloadShared: async function () {
        if (this.sharedReloading) return;
        this.sharedReloading = true;
        try {
          const r = await window.EMU_API.sharedReload();
          // 后端已经改成「发完就返回」，扫描在后台继续。这里必须自己轮询进度：
          // 以前固定等 2 秒再拉一次列表就再也不管了，目录一大用户看到的就是
          // 「点了没反应」「数字一直不动」。
          this.sharedProgress = {
            running: true,
            scan_dirs: (r && r.scan_dirs) || 0,
            shared_dirs: (r && r.shared_dirs) || 0,
          };
          this.ok("shared.scanStarted");
          await this.loadShared(true);
          this.startSharedScanWatch();
        } catch (e) {
          // 失败必须留痕：以前这里只弹一个转瞬即逝的提示，用户以为「点了没反应」
          this.sharedProgress = {
            running: false,
            error: String((e && (e.message || e.detail)) || e || "重新载入失败"),
            scan_dirs: 0,
            shared_dirs: 0,
          };
          this.fail("err.opFailed", e);
        } finally {
          this.sharedReloading = false;
        }
      },
      startSharedScanWatch: function () {
        if (this.sharedScanTimer) return;
        const self = this;
        this.sharedScanTimer = setInterval(async function () {
          try {
            const p = await window.EMU_API.sharedProgress();
            self.sharedProgress = p || { running: false };
            if (p && p.running) {
              // 扫描期间把列表一起刷新，用户能直接看到文件一个个进来
              const d = await window.EMU_API.shared(true);
              if (d) self.sharedData = d;
            } else {
              self.stopSharedScanWatch();
              // 收尾再取一次完整列表（最后一次快照可能还没落缓存）
              await self.loadShared(true);
            }
          } catch (e) {
            self.stopSharedScanWatch();
          }
        }, 4000);
      },
      stopSharedScanWatch: function () {
        if (this.sharedScanTimer) {
          clearInterval(this.sharedScanTimer);
          this.sharedScanTimer = null;
        }
      },
      refreshShared: async function () {
        await this.loadShared(true);
        this.ok("shared.reloadOk");
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
          // 日志一律「最新在上」：后端按时间正序给，这里翻一下，
          // 打开就能看到刚发生的事，不用滚到最底下。
          this.logs = this.logs.slice().reverse();
        } catch (e) {
          if (!silent) this.logs = [];
        } finally {
          this.logsLoading = false;
        }
      },
      /* 「清屏」以前只把浏览器内存里那个数组清空，刷新一下就原样回来，
         用户点了几次都以为坏了。现在它真的清磁盘上的日志文件
         （引擎日志就地截断，面板日志直接删），清完再重新拉一次列表。 */
      clearLogs: function () {
        const self = this;
        this.confirmBox = {
          title: this.t("logs.clearTitle"),
          text: this.t("logs.clearText"),
          okText: this.t("logs.clear"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              const r = await window.EMU_API.maintenanceCleanup("logs", { which: "all" });
              const freed = (r && Number(r.freed)) || 0;
              self.logs = [];
              self.logCleared = true;
              await self.loadLogs(true);
              self.toast(self.t("logs.clearedDisk", { v: self.fmt.fmtBytes(freed) }));
            } catch (e) {
              self.fail("logs.clearFailed", e);
            }
          },
        };
      },
      /* 「回到最新」按钮：无条件滚到顶。日志是最新在上，顶部就是最新。 */
      scrollLogTop: function () {
        const box = this.$refs.logBox;
        if (box) box.scrollTop = 0;
      },
      /* 自动刷新用：只在用户还停在顶部时才保持顶部，往下翻了他自己看，
         不硬把他拽回去。 */
      jumpToLogEnd: function () {
        const box = this.$refs.logBox;
        if (box && box.scrollTop <= 24) box.scrollTop = 0;
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
          merged.notify.events = Object.assign({ complete: true, error: true, update: true },
            (s.notify && s.notify.events) || {});
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
          // 只提交面板分区：整份 draft 里带着被后端打码过的通道密钥，原样回传会让
          // 服务端把 "__SET__" 当成新密钥存下来（这条路径就是改主题/切语言）。
          await window.EMU_API.saveSettings({ panel: this.draft.panel });
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
        const prevTemp = String((this.saved && this.saved.engine && this.saved.engine.temp_dir) || "");
        const nextTemp = String((this.draft && this.draft.engine && this.draft.engine.temp_dir) || "");
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
          // 临时目录变了：已有任务的 .part 还在旧目录，引擎按新目录找不到它们。
          // 不自动搬（搬家要停引擎，会打断所有下载），交给用户在页面上点一下。
          if (prevTemp && nextTemp && prevTemp !== nextTemp) {
            this.tempMigrateFrom = prevTemp;
          }
          const restart = (res && res.restart_required !== undefined) ? !!res.restart_required : localRestart;
          if (restart) {
            // 后端已经把「停引擎 → 起引擎」排到后台线程（停要等 partfile 落盘，
            // 起要等 EC 端口就绪，加起来超过一个 /api 请求的预算）。这里只负责
            // 提示并轮询到真的回来；以前没有人去重启，这段轮询等于空转 20 秒。
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
                // 停 20 秒 + 起 40 秒的余量，给够 60 轮
                if (n >= 60) { clearInterval(poll); }
              }, 1000);
            }); }, 2000);
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
      /* 把旧临时目录里的 .part 搬到当前目录。后端先停引擎、搬完再起引擎；
         搬不动就整批回滚并报错，不会留下半套文件。全程是后台任务，这里轮询结果。 */
      migrateTemp: async function () {
        if (this.tempMigrating) return;
        const from = this.tempMigrateFrom;
        const to = String((this.draft.engine && this.draft.engine.temp_dir) || "");
        if (!from || !to) return;
        this.tempMigrating = true;
        try {
          await window.EMU_API.migrateTemp(from, to);
          // 停引擎要等 partfile 落盘、起引擎要等 EC 就绪，一次请求装不下，
          // 所以起完之后轮询状态；最多等 3 分钟。
          const result = await this.pollMigrate();
          if (result.error) {
            this.toast(result.error, "err");
          } else if (result.warning) {
            this.tempMigrateFrom = "";
            this.toast(result.warning, "err");
          } else {
            this.tempMigrateFrom = "";
            this.ok("settings.dirs.migDone", { n: String(result.count || 0) });
          }
          await this.bootstrapPanel();
        } catch (e) {
          this.fail("settings.dirs.migFailed", e);
        } finally {
          this.tempMigrating = false;
        }
      },
      pollMigrate: async function () {
        for (let i = 0; i < 90; i++) {
          await new Promise((r) => setTimeout(r, 2000));
          const st = await window.EMU_API.migrateTempState();
          if (!st || !st.running) return st || {};
        }
        return { error: this.t("settings.dirs.migTimeout") };
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

      /* ---------------- 投递记录 ---------------- */
      /* 一条推送一行，成功失败都记；静默失败的 webhook 在这里能直接看出来。 */
      loadNotifyLog: async function () {
        if (this.notifyLogLoading) return;
        this.notifyLogLoading = true;
        try {
          const r = await window.EMU_API.notifyLog(120);
          this.notifyLog = (r && r.records) || [];
          this.notifyLogTotal = r && r.total !== undefined ? r.total : this.notifyLog.length;
          if (r && r.max) this.notifyLogMax = r.max;
        } catch (e) { /* 保留已在屏上的记录 */ }
        finally {
          this.notifyLogLoading = false;
          this.$nextTick(this.measureNotifyLog);
        }
      },
      /* 把列表高度锁在前 5 行的实测高度上，多余的在卡片内滚动 */
      measureNotifyLog: function () {
        const box = this.$refs.notifyLogList;
        if (!box) return;
        const rows = Array.prototype.slice.call(box.children, 0, NOTIFY_LOG_ROWS);
        if (!rows.length) {
          this.notifyLogHeight = 0;
          return;
        }
        let h = 0;
        rows.forEach(function (row) { h += row.getBoundingClientRect().height; });
        h += NOTIFY_LOG_GAP * (rows.length - 1);
        this.notifyLogHeight = Math.ceil(h);
      },
      notifyEventLabel: function (event) {
        const key = "notifyLog.event." + (event || "manual");
        const label = this.t(key);
        return label === key ? (event || "") : label;
      },
      askClearNotifyLog: function () {
        if (!this.notifyLog.length) return;
        const self = this;
        this.confirmBox = {
          title: this.t("notifyLog.clear"),
          text: this.t("notifyLog.clearConfirm"),
          okText: this.t("notifyLog.clear"),
          onOk: async function () {
            self.confirmBox = null;
            self.clearingNotifyLog = true;
            try {
              await window.EMU_API.clearNotifyLog();
              self.notifyLog = [];
              self.notifyLogTotal = 0;
              self.toast(self.t("notifyLog.cleared"));
            } catch (e) {
              self.toast(e.message, "err");
            } finally {
              self.clearingNotifyLog = false;
            }
          },
        };
      },

      /* ---------------- maintenance: export / import / auto backup ------- */
      loadBackupStatus: async function () {
        try {
          const s = await window.EMU_API.backupStatus();
          this.autoStatus = s || {};
          this.autoForm = {
            enabled: !!s.enabled,
            interval: s.interval_hours || 24,
            retention: s.retention || 7,
          };
        } catch (e) { /* keep previous values */ }
      },

      exportToFolder: async function () {
        try {
          const r = await window.EMU_API.backupToFolder();
          this.toast(this.t("backup.folderWritten", { path: (r && r.path) || "?" }));
          await this.loadBackupStatus();
        } catch (e) {
          this.toast(this.t("backup.exportFailed", { v: e.message }), "err");
        }
      },

      /* 桌面用 fetch+blob 拿到真实错误提示；手机 WebView 的下载监听收不到
         blob: URL，直接导航到附件地址让系统下载管理器接管。 */
      exportBackup: async function () {
        if (this.isMobile) {
          window.location.href = window.EMU_API.exportUrl;
          this.toast(this.t("backup.downloadStarted"));
          return;
        }
        try {
          const resp = await fetch(window.EMU_API.exportUrl,
            { credentials: "same-origin", cache: "no-store" });
          if (!resp.ok) throw new Error("HTTP " + resp.status);
          const dispo = resp.headers.get("content-disposition") || "";
          const m = dispo.match(/filename="?([^"]+)"?/);
          const name = (m && m[1]) || "emule-config.json";
          const blob = await resp.blob();
          const url = URL.createObjectURL(blob);
          const a = document.createElement("a");
          a.href = url; a.download = name; a.style.display = "none";
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(url); }, 1000);
          this.toast(this.t("msg.saved"));
        } catch (e) {
          this.toast(this.t("backup.exportFailed", { v: e.message }), "err");
        }
      },

      onPickBackup: function (ev) {
        const f = ev.target.files && ev.target.files[0];
        this.backupFile = f || null;
      },

      doImport: async function () {
        if (!this.backupFile) return;
        this.busy = true;
        try {
          await window.EMU_API.backupImport(this.backupFile);
          this.toast(this.t("backup.importOk"));
          setTimeout(function () { location.reload(); }, 900);
        } catch (e) {
          this.toast(e.status === 400 ? this.t("backup.invalid")
            : this.t("backup.importFailed", { v: e.message }), "err");
        } finally {
          this.busy = false;
        }
      },

      /* 手机上文件名前缀占掉三分之一行，只留日期时间那截才不省略。 */
      backupLabel: function (name) {
        const s = String(name || "");
        const m = s.match(/(\d{8}-\d{6}.*)$/);
        return m ? m[1] : s;
      },

      saveAuto: async function () {
        const st = this.autoStatus || {};
        const iv = Number(this.autoForm.interval) || 0;
        const rt = Number(this.autoForm.retention) || 0;
        if (iv < (st.interval_min || 1) || iv > (st.interval_max || 8760) ||
            rt < (st.retention_min || 1) || rt > (st.retention_max || 60)) {
          this.toast(this.t("auto.rangeError"), "err");
          return;
        }
        const patch = {
          backup: {
            enabled: !!this.autoForm.enabled,
            auto: !!this.autoForm.enabled,
            interval_hours: iv,
            retention: rt,
          },
        };
        try {
          await window.EMU_API.saveSettings(patch);
          this.toast(this.t("auto.saved"));
          await this.loadBackupStatus();
        } catch (e) {
          this.toast(this.t("err.saveFailed", { v: e.message }), "err");
        }
      },

      runBackupNow: async function () {
        try {
          const r = await window.EMU_API.backupRun();
          const name = r && r.path ? String(r.path).split(/[\\/]/).pop() : "";
          this.toast(this.t("auto.ran", { name: name }));
          await this.loadBackupStatus();
        } catch (e) {
          this.toast(this.t("backup.exportFailed", { v: e.message }), "err");
        }
      },

      askRestore: function (b) {
        const self = this;
        this.confirmBox = {
          title: this.t("backup.restore"),
          text: this.t("backup.confirmRestore", { name: b.name }),
          okText: this.t("backup.restore"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.backupRestore(b.name);
              self.toast(self.t("backup.restoreOk"));
              setTimeout(function () { location.reload(); }, 900);
            } catch (e) {
              self.toast(self.t("backup.importFailed", { v: e.message }), "err");
            }
          },
        };
      },

      askDeleteBackup: function (b) {
        const self = this;
        this.confirmBox = {
          title: this.t("backup.delete"),
          text: b.name,
          okText: this.t("backup.delete"),
          onOk: async function () {
            self.confirmBox = null;
            try {
              await window.EMU_API.backupDelete(b.name);
              self.toast(self.t("backup.deleted"));
              await self.loadBackupStatus();
            } catch (e) {
              self.toast(self.t("err.deleteFailed", { v: e.message }), "err");
            }
          },
        };
      },

      /* ---------------- 维护 / 存储 ---------------- */
      loadStorage: async function () {
        this.storageLoading = true;
        try {
          const d = await window.EMU_API.maintenanceStorage();
          this.storageData = d || { items: [], total: 0, updates: [] };
        } catch (e) {
          if (!this.storageData || !this.storageData.items) {
            this.storageData = { items: [], total: 0, updates: [] };
          }
        } finally {
          this.storageLoading = false;
        }
      },
      /* 清理按钮统一走这里：先确认，再调接口，最后刷新统计。
         target = updates（更新包）/ logs（日志）/ all（两者都清）。 */
      askCleanup: function (target) {
        const self = this;
        const titles = {
          updates: "settings.storage.cleanUpdates",
          logs: "settings.storage.cleanLogs",
          all: "settings.storage.cleanAll",
        };
        const texts = {
          updates: "settings.storage.cleanUpdatesText",
          logs: "settings.storage.cleanLogsText",
          all: "settings.storage.cleanAllText",
        };
        const freed = this.storageTotalFor(target);
        this.confirmBox = {
          title: this.t(titles[target] || titles.all),
          text: this.t(texts[target] || texts.all, { v: this.fmt.fmtBytes(freed) }),
          okText: this.t("settings.storage.cleanOk"),
          onOk: async function () {
            self.confirmBox = null;
            await self.runCleanup(target);
          },
        };
      },
      /* 清理时实际会释放多少：更新包那边要扣掉"当前版本"那个包
         （后端会保护它，不算进可回收空间），否则确认框里报的数字偏大。 */
      storageTotalFor: function (target) {
        const items = (this.storageData && this.storageData.items) || [];
        const pick = (keys) => items
          .filter(function (it) { return keys.indexOf(it.key) >= 0; })
          .reduce(function (sum, it) { return sum + (Number(it.bytes) || 0); }, 0);
        let updates = pick(["updates"]);
        // 当前版本那个包不会被删，从可回收空间里扣掉
        const cur = (this.storageData && this.storageData.current_version) || "";
        if (cur) {
          ((this.storageData && this.storageData.updates) || []).forEach(function (u) {
            if (u && !u.partial && String(u.name || "").indexOf(cur) >= 0) {
              updates = Math.max(0, updates - (Number(u.bytes) || 0));
            }
          });
        }
        const logs = pick(["amuled_log", "amuled_log1", "panel_log", "panel_log1", "update_log"]);
        if (target === "updates") return updates;
        if (target === "logs") return logs;
        return updates + logs;
      },
      runCleanup: async function (target) {
        if (this.storageBusy) return;
        this.storageBusy = target;
        try {
          const payload = { target: target };
          if (target === "updates" || target === "all") {
            payload.keep = Number(this.storageData.updates_keep) || 2;
          }
          if (target === "logs" || target === "all") payload.which = "all";
          const r = await window.EMU_API.maintenanceCleanup(target, payload);
          const freed = (r && Number(r.freed)) || 0;
          this.toast(this.t("settings.storage.cleaned", { v: this.fmt.fmtBytes(freed) }));
          if (r && r.warnings && r.warnings.length) {
            this.toast(String(r.warnings[0]), "err");
          }
          await this.loadStorage();
          // 清完日志，日志页的缓存也过期了，下次进去重新拉
          this.logCleared = false;
        } catch (e) {
          this.fail("settings.storage.cleanFailed", e);
        } finally {
          this.storageBusy = "";
        }
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
      /* Release 正文是 Markdown，渲染成 HTML 给 v-html。md.js 会先把整段
         转义再套标签，所以正文里的 <script> / javascript: 都执行不了。
         md.js 没加载上时退回纯文本 —— 排版可以丢，不能把原文当 HTML 插进去。 */
      updateNotesHtml: function () {
        const info = this.updateInfo || {};
        const raw = info.notes || "";
        if (!raw) return "";
        if (window.MD) return window.MD.render(raw);
        return String(raw)
          .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
          .replace(/\r?\n/g, "<br>");
      },
      checkUpdate: async function (force) {
        /* 手动点「检查更新」时如果正好有一次自动检查在飞，别把它丢掉：
           挂个标记，等这一轮结束后再按用户意图强制重查一次。 */
        if (this.updateChecking) {
          if (force) this._updateCheckQueued = true;
          return;
        }
        this.updateChecking = true;
        this.updateError = "";
        try {
          const r = await window.EMU_API.updateCheck(!!force);
          this.updateInfo = r || null;
          /* 只有「查成功了」才把时钟拨到当前：一次断网失败不该让切回窗口的补查
             再迟 30 分钟才发生。 */
          if (r && !r.error) this.lastUpdateCheckAt = Date.now();
          if (r && r.error) {
            this.updateError = this.t("settings.update.failed", { v: r.error });
          }
          // 发现新版本不再弹小提示框：页面顶部已有常驻的更新横幅，
          // 通知通道也会推送，再弹一条 toast 属于同一件事提示三次。
        } catch (e) {
          this.updateError = this.t("settings.update.failed", { v: (e && e.message) || "" });
        } finally {
          this.updateChecking = false;
          if (this._updateCheckQueued) {
            this._updateCheckQueued = false;
            this.checkUpdate(true);
          }
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
      dismissUpdateFail: function () {
        this.updateFailText = "";
      },
      runInstall: async function () {
        if (this.updateInstalling) return;
        this.updateInstalling = true;
        this.updateError = "";
        this.updateFailText = "";
        this.updateInstallLog = "";
        this.updateProgress = { percent: 0, phase: "checking", received: 0, total: 0 };
        this.updateInstallDetail = this.t("settings.update.checking");
        this.updateTargetVersion = (this.updateInfo && this.updateInfo.latest) || "";
        this._updateFromVersion = this.appVersion;
        /* 一开机就轮询，第一次读到的还可能是上一轮留下的 failed；只有真的看到过
           下载/安装过程，后面的 idle 才能当成「装完又退回来了」。 */
        this._updateSawActive = false;
        /* 上一次尝试的失败状态还在服务端存着（它不会自己回 idle），而这一轮
           的安装请求要先把阶段置成 checking 才改编号。不记住旧编号的话，第一个
           轮询就会读到上一轮的死信，弹窗当场关掉、报的还是上次的原因。
           这里先单独读一次编号当基线：页面刚打开时内存里还没有任何编号，
           靠安装请求的返回值又太晚。 */
        this._updateIgnoreAttempt = this.updateAttempt || 0;
        try {
          const base = await window.EMU_API.updateProgress();
          if (base && typeof base.attempt === "number") {
            this._updateIgnoreAttempt = base.attempt;
            this.updateAttempt = base.attempt;
          }
        } catch (e) { /* 读不到就退回内存里的值 */ }
        /* 轮询必须先起来，再发安装请求：后端在这个请求之后才在后台线程里干活，
           await 期间一个字节都不会回报，等它返回才转向询的话，下载阶段
           一个进度都看不到。 */
        this.pollUpdateProgress(this._updateFromVersion);
        try {
          const r = await window.EMU_API.installUpdate(this.updateInfo || null);
          if (r && r.ok === false) throw this._refusal(r);
          if (typeof r.attempt === "number") this.updateAttempt = r.attempt;
          /* 不解安装响应里的 task：那是后端刚置成 downloading 的一帧快照，
             total 还是 0。拿它绘制会把已经跑起来的进度条打回「准备中」，
             紧接着就是 20 秒停机窗口 —— 用户看到的就是一个冻住的遮罩。
             进度只认轮询，这里只取编号与回滚包信息。 */
          if (r && typeof r.rollback === "boolean") this.updateRollbackReady = r.rollback;
        } catch (e) {
          clearTimeout(this.installTimer);
          this.updateInstalling = false;
          /* api.js 把非 2xx 的响应体挂在 err.payload 上，服务端的 code 在那里 */
          const body = (e && e.payload) || {};
          this.failInstall({
            code: (e && e.code) || body.code || "",
            arg: (e && e.arg) || body.latest || "",
            rollback: body.rollback,
            message: (e && e.message) || "",
          });
        }
      },
      /* 服务端拒绝时下发的是语言中立的 code，界面自己翻译；只给中文文本的
         旧服务端仍按原文显示。 */
      _refusal: function (res) {
        const err = new Error((res && res.error) || "install failed");
        err.code = (res && res.code) || "";
        err.arg = (res && res.latest) || "";
        err.rollback = !!(res && res.rollback);
        return err;
      },
      /* 统一的失败收尾：把提示同时交给设置页与全局失败条，并记下安装脚本
         有没有回滚包可退（没有就别说「已回滚」）。 */
      failInstall: function (err) {
        const code = (err && err.code) || "";
        const text = code
          ? this.t("settings.update.code." + code, { v: (err && err.arg) || "" })
          : (err && err.message) || "";
        this.updateError = this.t("settings.update.installFailed", { v: text });
        this.updateFailText = this.updateError;
        this.updateInstallDetail = "";
        if (err && typeof err.rollback === "boolean") this.updateRollbackReady = err.rollback;
      },
      /* 服务端进度是瞬时快照，网速快时两次轮询之间能差几十个百分点。
         三条收敛规则缺一不可，否则界面会被旧快照打回去：

         1. 阶段只允许前进。checking < downloading < verifying < installing，
            后退的快照整帧丢弃 —— 快照来自另一个更早的时刻，它描述的
            「进度」已经过时了。
         2. total 只增不减，但只在 downloading 分支内。进入安装/校验后
            总量本来就没有意义，那里清零是**有意**的，不能算「减少」。
         3. 单调性只在同一 attempt 内成立。attempt 变了说明是新一轮，
            必须整体重置：上一轮停在 installing、total 是 10 MB，
            而这一轮从 checking、3 MB 的包开始，不重置就永远动不了。 */
      applyUpdateTask: function (task) {
        if (!task) return;
        const ORDER = { checking: 0, downloading: 1, verifying: 2, installing: 3 };
        const rawPhase = String(task.phase || "downloading");
        const attempt = typeof task.attempt === "number" ? task.attempt : 0;

        if (attempt !== this.updateMonoAttempt) {
          this.updateMonoAttempt = attempt;
          this.updateProgress = { percent: 0, phase: "idle", received: 0, total: 0 };
        }

        const prev = this.updateProgress || {};
        const prevRank = ORDER[String(prev.phase || "idle")];
        const nextRank = ORDER[rawPhase];
        // 认不出的阶段（旧后端 / 新加的值）不参与比较，原样接受
        if (prevRank !== undefined && nextRank !== undefined && nextRank < prevRank) {
          return;
        }

        const phase = rawPhase;
        const nextPct = Number(task.percent) || 0;
        const nextTotal = Number(task.total) || 0;
        const nextReceived = Number(task.received) || 0;

        const progress = {
          percent: Math.max(Number(prev.percent) || 0, nextPct),
          phase: phase,
          received: Math.max(Number(prev.received) || 0, nextReceived),
          total: nextTotal,
        };
        // total 只增：仅在下载阶段累积。校验/安装阶段没有可测总量，
        // 保持服务端给的 0，让进度区退回「准备中」而不是继续假装百分比。
        if (phase === "downloading") {
          progress.total = Math.max(Number(prev.total) || 0, nextTotal);
        } else {
          progress.total = 0;
        }
        this.updateProgress = progress;

        /* 阶段文案一律由前端按当前语言拼：服务端的 detail 只在失败时才有
           意义（翻译好的原因），成功路径上是空串，直接回显会让英文界面
           冒出中文。 */
        if (phase === "checking") {
          this.updateInstallDetail = this.t("settings.update.checking");
        } else if (phase === "downloading") {
          this.updateInstallDetail = this.t("settings.update.installingDownload");
        } else if (phase === "verifying") {
          this.updateInstallDetail = this.t("settings.update.installingVerify");
        } else if (phase === "installing") {
          this.updateInstallDetail = this.t("settings.update.installingReady");
        }
        if (phase === "downloading" || phase === "verifying" || phase === "installing") {
          this._updateSawActive = true;
        }
      },
      pollUpdateProgress: function (fromVersion) {
        const self = this;
        let misses = 0;
        const tick = async function () {
          // 面板被卸载/重启期间接口会连续失败若干次，这是升级的正常过程，
          // 不能一失败就当出错 —— 只要它还会回来，就继续等。
          try {
            const r = await window.EMU_API.updateProgress();
            misses = 0;
            if (r && typeof r.attempt === "number") self.updateAttempt = r.attempt;
            if (r && typeof r.rollback === "boolean") self.updateRollbackReady = r.rollback;
            /* 日志尾部每次都收下，但只在失败时展示（模版按 updateError 判断）。
               下载阶段文件里还是上一次的记录，收下也无妨 —— 那一帧还没有
               updateError，不会被显示出来。 */
            if (r && typeof r.log === "string") self.updateInstallLog = r.log;
            const task = (r && r.task) || {};
            if (task.phase === "failed") {
              /* 服务端不会自己回到 idle，重试的头几百毫秒读到的还是上一次的
                 失败状态。编号没变就说明这条死信不属于本轮，等新一轮开始。 */
              if (typeof r.attempt === "number" && r.attempt <= self._updateIgnoreAttempt) {
                self.installTimer = setTimeout(tick, 400);
                return;
              }
              /* 下载/校验阶段的失败：此时安装脚本还没跑过，日志里留着的是
                 上一次的记录，贴出来只会把人引到别的原因上，所以只报原因本身。 */
              self.updateInstalling = false;
              self.failInstall({ code: task.code || "", message: task.detail || "" });
              return;
            }
            /* 新版本已上线：面板报告的版本号不再等于安装前那个。
               用「与起始版本不同」判断，比精确匹配目标版本号更耐得住
               tag 带前缀、或资产名与版本号不完全一致的情况。 */
            if (r && r.version && fromVersion && r.version !== fromVersion) {
              self.finishUpdate(r.version);
              return;
            }
            /* 升级中途面板被换掉、新版本却没起来时，脚本会装回旧包再启动。
               于是回到这里的是「同一个版本 + 全新的 idle 状态」，而内存里的
               updateInstalling 还是 true —— 原先会一直轮询下去，弹窗永远
               不消失。看到安装过程已经结束（idle）且版本没变就按失败处理，
               并把脚本日志里的回滚记录留给卡片。 */
            if (task.phase === "idle" && self._updateSawActive) {
              const tail = (r && r.log) || "";
              /* 只有脚本真的进了回滚分支才说「已回滚」；进程被别的原因重启、
                 或装机超时，日志里没有这一行，就该提示去应用中心确认。 */
              const rolled = /rolling back/.test(tail);
              self.updateInstalling = false;
              self.updateError = self.t("settings.update.installFailed", {
                v: self.t(rolled ? "settings.update.rolledBack" : "settings.update.timeout"),
              });
              self.updateFailText = self.updateError;
              self.updateInstallDetail = "";
              return;
            }
            self.applyUpdateTask(task);
          } catch (e) {
            misses += 1;
            // 面板可能正在被替换，期间连不上是正常的；超时太久才报错
            if (misses > 180) {
              self.updateInstalling = false;
              self.updateError = self.t("settings.update.installFailed",
                { v: self.t("settings.update.timeout") });
              self.updateFailText = self.updateError;
              return;
            }
          }
          // 400ms 轮询：更新包通常几 MB，在千兆内网不到 1 秒就下完，
          // 间隔太长只能抓到一两个中间值，看起来像"直接跳到完成"。
          self.installTimer = setTimeout(tick, 400);
        };
        this.installTimer = setTimeout(tick, 400);
      },
      /* 新版本装好了：给个提示，然后整体重新加载页面。
         面板在升级过程中被卸载重装，前端的内存状态（版本号、设置、路由）
         都还是旧的，只刷新数据不够 —— 重载一次让页面跑在新版本上。

         这里的计数器是字节数，不是百分比：塞 100/100 会让界面显示成
         「100 B / 100 B」。下载结束后真实总量本来就在，保持不动。 */
      finishUpdate: function (version) {
        const self = this;
        /* 遮罩上那行已经把「已更新到 vX，正在刷新…」写全了，这里不再另弹一条
           右下角提示：同样的字出现两次，而且遮罩一关它就没有上下文了。 */
        this.updateInstallDetail = this.t("settings.update.done", { v: version || "" });
        setTimeout(function () {
          self.updateInstalling = false;
          // 面板刚从卸载重装里回来，等它把引擎也拉起来
          self.bootstrapPanel().catch(function () {});
          self.reloadWhenBack(0);
        }, 1500);
      },

      /* 装完后的自动刷新要等面板真的回来再刷。
         升级脚本是「停服务 → 卸载 → 安装 → 启动」，成功结论出现的那一刻服务
         往往正要停：这时立刻 location.reload() 等于主动撞进离线空窗，
         浏览器停在错误页上再也回不来 —— 用户看到的就是「更新完卡住刷不出来」。
         所以改成先探一次 health（能答上来说明新进程已经在服务），拿不到就退避重试。 */
      /* 自救按钮：浏览器若已停在断网错误页上，只有用户自己点一下才回得来。
         模板里不能写 location.reload()（in-DOM 模板取不到 location），
         所以包一层方法。 */
      reloadNow: function () {
        try { location.reload(); } catch (e) { /* ignore */ }
      },

      reloadWhenBack: function (attempt) {
        const self = this;
        const n = Number(attempt) || 0;
        window.EMU_API.health().then(function () {
          try { location.reload(); } catch (e) { /* ignore */ }
        }).catch(function () {
          // 等太久就把「立即重新加载」放出来：万一浏览器已经停在断网错误页上，
          // 自动重试是回不来的，用户至少有一个按钮可以自己再试一次。
          if (n >= 10) {
            self.updateReloadReady = true;
          }
          if (n >= 100) { try { location.reload(); } catch (e) { /* ignore */ } return; }
          setTimeout(function () { self.reloadWhenBack(n + 1); }, 800);
        });
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
