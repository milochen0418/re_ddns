/* Agentic App Store website: language switch, app catalog (from apps.js) and videos. */
(function () {
  "use strict";

  var APPS = window.AAS_APPS || [];
  var META = window.AAS_META || { count: APPS.length };
  var YT = "https://www.youtube.com/watch?v=";

  var T = {
    en: {
      title: "Agentic App Store: your own app store, where apps and AI work together",
      langBtn: "中文", langAria: "切換成中文 (Switch to Chinese)",
      search: "Search apps", filters: "Show apps by kind",
      chips: { all: "All", ai: "Works with AI", create: "Create together", health: "Medical imaging",
               meet: "Meet and talk", play: "Play against AI", tools: "Media and tools" },
      ai: "AI", aiTip: "Works with AI through the AI Hub",
      shares: "Shares: ", sharesTip: "Shares files with other apps in the {c} collection",
      setup: "Needs setup", setupTip: "Asks for keys or settings when you install it",
      more: "More", less: "Less", source: "Source on GitHub", shot: "Screenshot of {n}",
      play: "Play video: {t}", other: "中文版", empty: "No app matches “{q}”."
    },
    zh: {
      title: "Agentic App Store：你自己的 App Store，讓 App 和 AI 一起工作",
      langBtn: "EN", langAria: "Switch to English（切換成英文）",
      search: "搜尋 App", filters: "依類別顯示 App",
      chips: { all: "全部", ai: "能和 AI 合作", create: "一起創作", health: "醫學影像",
               meet: "聊天與會議", play: "跟 AI 對戰", tools: "影音與工具" },
      ai: "AI", aiTip: "透過 AI Hub 和 AI 合作",
      shares: "共用：", sharesTip: "透過 {c} collection 跟其他 App 共用檔案",
      setup: "需先設定", setupTip: "安裝時要先填金鑰或設定",
      more: "展開", less: "收合", source: "GitHub 原始碼", shot: "{n} 的畫面",
      play: "播放影片：{t}", other: "English version", empty: "沒有符合「{q}」的 App。"
    }
  };

  // Videos on the channel. Where both exist, "zh" is the Chinese version of the same video.
  var VIDEOS = [
    { id: { en: "jR9b1qqIzzM", zh: "Y_98JTrUKoY" }, dur: { en: "3:43", zh: "3:40" },
      t: { en: "AI × CAD: say it, build it, walk in", zh: "AI × CAD：說出來，蓋出來，走進去" },
      d: { en: "Claude Code builds landmarks in Codoc in CAD through the AI Hub, and people walk into them together in CAD Roam.",
           zh: "Claude Code 透過 AI Hub 在 Codoc in CAD 蓋出地標建築，大家再一起走進 CAD Roam 參觀。" } },
    { id: { en: "J60fVC0Y5Ys" }, dur: { en: "3:21" },
      t: { en: "Relack: own your team's chat", zh: "Relack：團隊聊天，自己作主" },
      d: { en: "What happened on Slack, why a team's chat belongs on its own machine, and Relack at work, up to a real install from the store.",
           zh: "Slack 發生了哪些事、為什麼團隊聊天該放在自己的機器上，再看 Relack 實際運作，一路到從商店安裝。" } },
    { id: { en: "dbz7ta0M1TM" }, dur: { en: "16:44" },
      t: { en: "Agentic App Store: the full demo", zh: "Agentic App Store 完整示範" },
      d: { en: "The whole store in action: installing apps and using them, with sign-in and calls.",
           zh: "整個商店的實際操作：安裝並使用 App，包含登入與通話。" } },
    { id: { en: "Y5YKXsWkrxg" }, dur: { en: "2:21" },
      t: { en: "DDNS Intent: apps open each other", zh: "DDNS Intent：App 互相開啟" },
      d: { en: "How one app opens another app's page as a dialog. This is how Call everyone works.",
           zh: "一個 App 怎麼把另一個 App 的頁面當成對話框打開，Call everyone 就是這樣運作的。" } },
    { id: { en: "4q_QHQv0wrI" }, dur: { en: "1:59" },
      t: { en: "Collections: apps share data", zh: "Collections：App 共用資料" },
      d: { en: "One app downloads, another uses: storage that apps share, on one host or several.",
           zh: "一個 App 下載、另一個 App 使用：App 之間共用的儲存空間，可以跨好幾台主機。" } },
    { id: { en: "xwQz1Xm6ZZk", zh: "RkApttGQEMM" }, dur: { en: "1:36", zh: "1:42" },
      t: { en: "Reviewing radiotherapy contours together", zh: "一起討論放療描線" },
      d: { en: "A link in the chat opens the same DICOM view for everyone, with a call. A demonstration; not for diagnosis.",
           zh: "聊天室裡的一個連結，讓大家打開同一個 DICOM 畫面並通話。示範情境，不作診斷用途。" } },
    { id: { en: "HZKiZ_LepIs" }, dur: { en: "6:09" },
      t: { en: "PACS Lab tutorial", zh: "PACS Lab 教學" },
      d: { en: "Start a practice PACS in Docker, fill it with public images and connect DICOM Data Explorer.",
           zh: "在 Docker 裡開一台練習用 PACS，放進公開影像，再接上 DICOM Data Explorer。" } },
    { id: { en: "Zt3voGhKGOk", zh: "acguG9apTkE" }, dur: { en: "5:50", zh: "5:41" },
      t: { en: "Chipova: a chip design flow", zh: "Chipova：晶片設計流程" },
      d: { en: "From Verilog to a chip layout, with people and AI agents working on the same design.",
           zh: "從 Verilog 到晶片佈局，人和 AI agent 一起做同一份設計。" } },
    { id: { en: "jKJ8QdtrUs4" }, dur: { en: "3:38" },
      t: { en: "Nooklane: a 2D place to meet", zh: "Nooklane：2D 聚會空間" },
      d: { en: "Walk up to someone to talk. Voices and cameras get clearer as you get close.",
           zh: "走到對方身邊就能聊天，靠得越近，聲音和畫面越清楚。" } },
    { id: { en: "Zl0tysSTTOI", zh: "OvGv0PB3UKU" }, dur: { en: "3:20", zh: "3:41" },
      t: { en: "ReflexGrid: co-editing, VBA macros and UserForms", zh: "ReflexGrid：共同編輯、VBA 巨集與 UserForm" },
      d: { en: "An Excel-compatible spreadsheet in the browser that runs VBA macros while people edit together.",
           zh: "在瀏覽器裡、相容 Excel 的試算表，能執行 VBA 巨集，也能多人同時編輯。" } }
  ];

  var CHIPS = ["all", "ai", "create", "health", "meet", "play", "tools"];
  var GITHUB = '<svg class="b" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>';
  var PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>';

  var state = { chip: "all", q: "" };
  var $ = function (id) { return document.getElementById(id); };
  var grid = $("app-grid"), empty = $("app-empty"), filters = $("filters"), search = $("app-search");
  var videoGrid = $("video-grid"), langBtn = $("lang-btn");

  function k() { return document.documentElement.lang === "zh-Hant" ? "zh" : "en"; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fill(s, vars) { return s.replace(/\{(\w)\}/g, function (_, v) { return vars[v]; }); }
  function inChip(a, chip) { return chip === "all" || (chip === "ai" ? a.ai : a.cat === chip); }
  function matches(a, q) {
    if (!q) return true;
    var hay = [a.name, a.sub, a.desc.en, a.desc.zh, a.collections.join(" ")].join(" ").toLowerCase();
    return q.toLowerCase().split(/\s+/).every(function (w) { return hay.indexOf(w) !== -1; });
  }

  function renderChips() {
    var t = T[k()];
    filters.setAttribute("aria-label", t.filters);
    filters.innerHTML = CHIPS.map(function (c) {
      var n = APPS.filter(function (a) { return inChip(a, c); }).length;
      return '<button type="button" class="chip" data-chip="' + c + '" aria-pressed="' + (state.chip === c) + '">' +
        esc(t.chips[c]) + " <small>" + n + "</small></button>";
    }).join("");
  }

  function appCard(a, t, lang) {
    var media = a.img
      ? '<div class="app-media"><img src="' + esc(a.img) + '" width="1280" height="800" loading="lazy" decoding="async" alt="' + esc(fill(t.shot, { n: a.name })) + '"></div>'
      : '<div class="app-media tile" aria-hidden="true">' + a.icon + "</div>";
    var tags = "";
    if (a.ai) tags += '<span class="tag ai" title="' + esc(t.aiTip) + '">' + t.ai + "</span>";
    a.collections.forEach(function (c) {
      tags += '<span class="tag col" title="' + esc(fill(t.sharesTip, { c: c })) + '">' + esc(t.shares + c) + "</span>";
    });
    if (a.setup) tags += '<span class="tag set" title="' + esc(t.setupTip) + '">' + esc(t.setup) + "</span>";
    return '<article class="app">' + media +
      '<div class="app-body">' +
        '<div class="app-title">' + a.icon + "<h3>" + esc(a.name) + "</h3></div>" +
        (tags ? '<div class="tags">' + tags + "</div>" : "") +
        '<p class="app-desc" id="d-' + esc(a.sub) + '">' + esc(a.desc[lang] || a.desc.en) + "</p>" +
        '<button class="more" type="button" aria-expanded="false" aria-controls="d-' + esc(a.sub) + '" hidden>' + t.more + "</button>" +
        '<div class="app-foot"><a href="' + esc(a.repo) + '">' + GITHUB + esc(t.source) + "</a></div>" +
      "</div></article>";
  }

  function renderApps() {
    var t = T[k()], lang = k();
    var list = APPS.filter(function (a) { return inChip(a, state.chip) && matches(a, state.q); });
    grid.innerHTML = list.map(function (a) { return appCard(a, t, lang); }).join("");
    empty.hidden = list.length > 0;
    if (!list.length) empty.textContent = fill(t.empty, { q: state.q });
    markLong();
  }

  // Show "More" only on descriptions that the 4-line clamp actually cuts.
  function markLong() {
    var t = T[k()];
    grid.querySelectorAll(".app").forEach(function (card) {
      var p = card.querySelector(".app-desc"), btn = card.querySelector(".more");
      if (card.classList.contains("open")) { btn.hidden = false; return; }
      btn.hidden = p.scrollHeight <= p.clientHeight + 2;
      btn.textContent = t.more;
    });
  }

  function videoCard(v, lang, t) {
    var id = v.id[lang] || v.id.en, title = v.t[lang], dur = v.dur[lang] || v.dur.en;
    var other = lang === "zh" ? (v.id.zh && v.id.en) : v.id.zh;
    return '<article class="video">' +
      '<button class="yt" type="button" data-id="' + id + '" data-title="' + esc(title) + '" aria-label="' + esc(fill(t.play, { t: title })) + '">' +
        '<img src="https://i.ytimg.com/vi/' + id + '/sddefault.jpg" alt="" loading="lazy" decoding="async">' +
        '<span class="play">' + PLAY + '</span><span class="dur">' + dur + "</span>" +
      "</button>" +
      "<h3>" + esc(title) + "</h3><p>" + esc(v.d[lang]) + "</p>" +
      (other ? '<p class="alt"><a href="' + YT + other + '">' + t.other + "</a></p>" : "") +
      "</article>";
  }

  function renderVideos() {
    var lang = k(), t = T[lang];
    videoGrid.innerHTML = VIDEOS.map(function (v) { return videoCard(v, lang, t); }).join("");
  }

  function playVideo(btn) {
    var box = document.createElement("div");
    box.className = "yt";
    var f = document.createElement("iframe");
    f.src = "https://www.youtube-nocookie.com/embed/" + btn.getAttribute("data-id") + "?autoplay=1&rel=0";
    f.title = btn.getAttribute("data-title");
    f.allow = "accelerometer; autoplay; clipboard-write; encrypted-media; gyroscope; picture-in-picture; web-share";
    f.allowFullscreen = true;
    f.referrerPolicy = "strict-origin-when-cross-origin";
    box.appendChild(f);
    btn.replaceWith(box);
    f.focus();
  }

  function apply() {
    var t = T[k()];
    document.title = t.title;
    langBtn.textContent = t.langBtn;
    langBtn.setAttribute("aria-label", t.langAria);
    search.placeholder = t.search;
    $("app-search-label").textContent = t.search;
    renderChips();
    renderApps();
    renderVideos();
  }

  function setLang(lang) {
    document.documentElement.lang = lang;
    try { localStorage.setItem("aas-lang", lang); } catch (e) { /* storage off: keep it for this visit */ }
    apply();
  }

  document.querySelectorAll("[data-count]").forEach(function (el) { el.textContent = META.count; });

  langBtn.addEventListener("click", function () { setLang(k() === "zh" ? "en" : "zh-Hant"); });
  filters.addEventListener("click", function (e) {
    var b = e.target.closest(".chip");
    if (!b) return;
    state.chip = b.getAttribute("data-chip");
    filters.querySelectorAll(".chip").forEach(function (c) { c.setAttribute("aria-pressed", String(c === b)); });
    renderApps();
  });
  search.addEventListener("input", function () { state.q = search.value.trim(); renderApps(); });
  grid.addEventListener("click", function (e) {
    var b = e.target.closest(".more");
    if (!b) return;
    var card = b.closest(".app"), open = !card.classList.contains("open"), t = T[k()];
    card.classList.toggle("open", open);
    b.setAttribute("aria-expanded", String(open));
    b.textContent = open ? t.less : t.more;
  });
  videoGrid.addEventListener("click", function (e) {
    var b = e.target.closest("button.yt");
    if (b) playVideo(b);
  });
  var resizeTimer;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(markLong, 150); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(markLong);

  apply();
})();
