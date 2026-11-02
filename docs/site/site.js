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
      watch: "Watch a video about {n}",
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
      watch: "看 {n} 的影片",
      play: "播放影片：{t}", other: "English version", empty: "沒有符合「{q}」的 App。"
    }
  };

  // Videos on the channel. Where both exist, "zh" is the Chinese version of the same video.
  // "img" is a 16:9 picture for videos whose YouTube thumbnail does not read well on the card:
  // one path, or { en, zh } when the picture has words on it.
  // "appOnly" keeps a video out of the Videos section: it shows only from its app's card.
  var VIDEOS = [
    { id: { en: "jR9b1qqIzzM", zh: "Y_98JTrUKoY" }, dur: { en: "3:43", zh: "3:40" },
      t: { en: "AI × CAD: say it, build it, walk in", zh: "AI × CAD：說出來，蓋出來，走進去" },
      d: { en: "Claude Code builds landmarks in Codoc in CAD through the AI Hub, and people walk into them together in CAD Roam.",
           zh: "Claude Code 透過 AI Hub 在 Codoc in CAD 蓋出地標建築，大家再一起走進 CAD Roam 參觀。" } },
    { id: { en: "zJGloh9EZJw", zh: "hfAp2pW_FUE" }, dur: { en: "3:33", zh: "3:23" },
      img: { en: "site/img/videos/userforms.en.webp", zh: "site/img/videos/userforms.zh.webp" },
      t: { en: "Your UserForms, online, in a document you write together", zh: "UserForm 上線了，放進大家一起寫的文件" },
      d: { en: "The forms your company already uses, with nothing to rewrite: their rules still run and the numbers follow the workbook. Two people send at the same moment and both rows land in the same table, with AI helping on the same page.",
           zh: "公司用了好幾年的 UserForm，不用重寫：規則照跑，數字跟著活頁簿走。兩個人同時送出，兩筆都進同一張表，AI 也在同一頁幫忙。" } },
    { id: { en: "cbQX8jrl_Nc", zh: "vOeiArqsMJI" }, dur: { en: "3:04", zh: "2:58" },
      t: { en: "CoDoc in MD: one link, everyone writes", zh: "CoDoc in MD：一個連結，大家一起寫" },
      d: { en: "A Markdown document you write together: everyone has a color and a name tag, and one line of text puts a video, a PDF or a flowchart on the page. For meetings, classes, design docs and shared notes.",
           zh: "一起寫的 Markdown 文件：每個人有自己的顏色和名牌，打一行字就能放進 YouTube 影片、PDF、流程圖。開會、上課、寫規格、共筆都好用。" } },
    { id: { en: "hrBlC-gHpss", zh: "Oy-pKn_2G3s" }, dur: { en: "2:15", zh: "2:10" },
      t: { en: "Codoc in VecDraw: one picture, always the latest", zh: "Codoc in VecDraw：一張圖，永遠是最新的" },
      d: { en: "Send a link instead of a screenshot: the card in Relack and the picture in a CoDoc in MD document follow the drawing. Draw together, each with your own tools, and tell the AI what to draw.",
           zh: "傳連結，不傳截圖：Relack 的卡片和 CoDoc in MD 文件裡的圖都跟著這張圖變。大家一起畫，工具各用各的，跟 AI 說一聲它也會畫。" } },
    { id: { en: "196pWZceyas" }, dur: { en: "3:18" }, img: "site/img/videos/reflexgrid-intro.webp",
      t: { en: "ReflexGrid: the online Excel that runs your macros", zh: "ReflexGrid：能跑巨集的線上 Excel" },
      d: { en: "Real Excel files, VBA macros and UserForms in the browser, editing together, and AI that changes nothing until you press Accept.",
           zh: "真正的 Excel 檔、在瀏覽器裡跑的 VBA 巨集和 UserForm、多人一起編輯，還有你按下 Accept 才會動手的 AI。" } },
    { id: { en: "J60fVC0Y5Ys" }, dur: { en: "3:21" }, img: "site/img/videos/relack-own.webp",
      t: { en: "Relack: own your team's chat", zh: "Relack：團隊聊天，自己作主" },
      d: { en: "What happened on Slack, why a team's chat belongs on its own machine, and Relack at work, up to a real install from the store.",
           zh: "Slack 發生了哪些事、為什麼團隊聊天該放在自己的機器上，再看 Relack 實際運作，一路到從商店安裝。" } },
    { id: { en: "dTvia4_5Iaw" }, dur: { en: "2:27" }, img: "site/img/videos/apexline-intro.webp",
      t: { en: "Apexline: race an AI that thinks", zh: "Apexline 極速對決：跟會思考的 AI 賽車" },
      d: { en: "You on the left, a real language model on the right. It plans a speed for every corner, hears how each lap went and changes the plan.",
           zh: "左邊是你，右邊是真正的語言模型。它替每個彎訂速度，每跑完一圈就聽取結果、修改計畫。" } },
    { id: { en: "NLCrHKpTJ5U" }, dur: { en: "2:49" }, img: "site/img/videos/snake-duel-intro.webp",
      t: { en: "Snake Duel: the snake game that talks back", zh: "雙蛇搶食：會回嘴的貪食蛇" },
      d: { en: "Up to five snakes on one board: friends take the seats and AI snakes that ask a real language model fill the rest.",
           zh: "同一塊場地最多 5 條蛇：朋友先坐位子，其餘由真正問語言模型的 AI 蛇補滿。" } },
    { id: { en: "DC_OD47kK3U", zh: "MoPO9Jv4l1I" }, dur: { en: "3:22", zh: "3:27" }, img: "site/img/videos/mixer-promo.webp",
      t: { en: "Video Audio Mixer: put the music in the right place", zh: "Video Audio Mixer：把音樂放對地方" },
      d: { en: "What research says about music under video, then the timeline at work: turn a song down under a voice, trim it, fade into the next.",
           zh: "研究怎麼說影片配樂，再看時間軸實際操作：講話時把音樂壓低、裁出想用的段落、淡入下一首。" } },
    { id: { en: "cHdsxtrEHtg" }, dur: { en: "3:46" }, img: "site/img/videos/cellora-intro.webp",
      t: { en: "Cellora: Python notebooks, together", zh: "Cellora：一起寫的 Python 筆記本" },
      d: { en: "A class learns imaging code on one machine: get a CT from a practice PACS, view it together, write the code in a shared notebook with AI, and send the result back to the PACS. A demonstration; not for diagnosis.",
           zh: "一堂課在一台機器上學影像程式：從練習用 PACS 取得 CT、一起看片、在共用筆記本裡和 AI 一起寫程式，再把結果存回 PACS。示範情境，不作診斷用途。" } },
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
           zh: "在瀏覽器裡、相容 Excel 的試算表，能執行 VBA 巨集，也能多人同時編輯。" } },
    { id: { en: "8U_jHWmAXmA" }, dur: { en: "8:56" }, appOnly: true,
      t: { en: "Codoc in CAD: people and AI agents design together", zh: "Codoc in CAD：人和 AI agent 一起做機構設計" } },
    { id: { en: "qPKxzscEXRo" }, dur: { en: "3:36" }, appOnly: true,
      t: { en: "Codoc in VecDraw: draw together, with ChatGPT Atlas", zh: "Codoc in VecDraw：一起畫圖，ChatGPT Atlas 也能畫" } },
    { id: { en: "I5rBceuf1tM" }, dur: { en: "1:51" }, appOnly: true,
      t: { en: "ReflexGrid v1.0: a first look", zh: "ReflexGrid v1.0 簡介" } }
  ];

  // Videos about each app, by subdomain, the most direct one first: [English id, second to start at,
  // and the second in the Chinese version when it is not the same].
  // List a video here only if it really shows the app. An app without a video gets no icon.
  var APP_VIDEOS = {
    "ai": [["jR9b1qqIzzM"], ["zJGloh9EZJw", 119, 112], ["cbQX8jrl_Nc", 122, 118], ["hrBlC-gHpss", 56, 55]],
    "md": [["cbQX8jrl_Nc"], ["zJGloh9EZJw"], ["hrBlC-gHpss", 76, 74]],
    "plantuml": [["dbz7ta0M1TM", 61]],
    "vecdraw": [["hrBlC-gHpss"], ["qPKxzscEXRo"]],
    "cad": [["jR9b1qqIzzM"], ["8U_jHWmAXmA"]],
    "cad-roam": [["jR9b1qqIzzM", 54]],
    "dicom-data-explorer": [["HZKiZ_LepIs", 179], ["cHdsxtrEHtg", 63], ["4q_QHQv0wrI", 57], ["xwQz1Xm6ZZk", 60]],
    "dicom-viewer": [["xwQz1Xm6ZZk"], ["cHdsxtrEHtg", 91], ["4q_QHQv0wrI", 68]],
    "pacs-lab": [["HZKiZ_LepIs"], ["cHdsxtrEHtg", 70]],
    "video-segment-splitter": [["dbz7ta0M1TM", 257]],
    "video-audio-mixer": [["DC_OD47kK3U"]],
    "relack": [["J60fVC0Y5Ys"], ["hrBlC-gHpss", 13, 14], ["xwQz1Xm6ZZk", 32], ["Y5YKXsWkrxg", 100]],
    "livekit": [["cbQX8jrl_Nc", 46], ["hrBlC-gHpss", 101, 99], ["Y5YKXsWkrxg", 43]],
    "video-chat": [["Y5YKXsWkrxg", 43]],
    "avatar-chat": [["cHdsxtrEHtg", 155], ["Y5YKXsWkrxg", 43]],
    "english-chat": [["Y5YKXsWkrxg", 43]],
    "nooklane": [["jKJ8QdtrUs4"]],
    "cellora": [["cHdsxtrEHtg"]],
    "chipova": [["Zt3voGhKGOk"]],
    "snake-duel": [["NLCrHKpTJ5U"]],
    "apexline": [["dTvia4_5Iaw"]],
    "grid": [["196pWZceyas"], ["zJGloh9EZJw", 62, 60], ["Zl0tysSTTOI"], ["I5rBceuf1tM"]]
  };

  var CHIPS = ["all", "ai", "create", "health", "meet", "play", "tools"];
  var GITHUB = '<svg class="b" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.3-5.466-1.332-5.466-5.93 0-1.31.465-2.38 1.235-3.22-.135-.303-.54-1.523.105-3.176 0 0 1.005-.322 3.3 1.23.96-.267 1.98-.399 3-.405 1.02.006 2.04.138 3 .405 2.28-1.552 3.285-1.23 3.285-1.23.645 1.653.24 2.873.12 3.176.765.84 1.23 1.91 1.23 3.22 0 4.61-2.805 5.625-5.475 5.92.42.36.81 1.096.81 2.22 0 1.606-.015 2.896-.015 3.286 0 .315.21.69.825.57C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12"/></svg>';
  var PLAY = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5z"/></svg>';
  var YOUTUBE = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#f00" d="M23.498 6.186a3.016 3.016 0 0 0-2.122-2.136C19.505 3.545 12 3.545 12 3.545s-7.505 0-9.377.505A3.017 3.017 0 0 0 .502 6.186C0 8.07 0 12 0 12s0 3.93.502 5.814a3.016 3.016 0 0 0 2.122 2.136c1.871.505 9.376.505 9.376.505s7.505 0 9.377-.505a3.015 3.015 0 0 0 2.122-2.136C24 15.93 24 12 24 12s0-3.93-.502-5.814z"/><path fill="#fff" d="M9.545 15.568V8.432L15.818 12l-6.273 3.568z"/></svg>';

  var state = { chip: "all", q: "" };
  var $ = function (id) { return document.getElementById(id); };
  var grid = $("app-grid"), empty = $("app-empty"), filters = $("filters"), search = $("app-search");
  var videoGrid = $("video-grid"), langBtn = $("lang-btn");
  var dialog = $("video-dialog"), vdPlayer = $("vd-player"), vdList = $("vd-list"), vdNote = $("vd-note"), vdLink = $("vd-link");
  var dialogVideos = [], player = null, playerApi = null, slowTimer = 0, playing = 0;

  function k() { return document.documentElement.lang === "zh-Hant" ? "zh" : "en"; }
  function esc(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function fill(s, vars) { return s.replace(/\{(\w)\}/g, function (_, v) { return vars[v]; }); }
  function videosOf(sub, lang) {
    return (APP_VIDEOS[sub] || []).map(function (e) {
      var v = VIDEOS.filter(function (x) { return x.id.en === e[0]; })[0];
      var at = lang === "zh" && e[2] !== undefined ? e[2] : e[1];
      return { v: v, id: v.id[lang] || v.id.en, at: at || 0 };
    });
  }
  function poster(v, lang) { return v.img && (v.img[lang] || v.img); }
  function watchUrl(item) { return YT + item.id + (item.at ? "&t=" + item.at + "s" : ""); }
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
    var vids = videosOf(a.sub, lang), watch = esc(fill(t.watch, { n: a.name }));
    return '<article class="app">' + media +
      (vids.length ? '<a class="app-video" href="' + esc(watchUrl(vids[0])) + '" target="_blank" rel="noopener" data-sub="' + esc(a.sub) + '" title="' + watch + '" aria-label="' + watch + '">' + YOUTUBE + "</a>" : "") +
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
        '<img src="' + (poster(v, lang) || "https://i.ytimg.com/vi/" + id + "/sddefault.jpg") + '" alt="" loading="lazy" decoding="async">' +
        '<span class="play">' + PLAY + '</span><span class="dur">' + dur + "</span>" +
      "</button>" +
      "<h3>" + esc(title) + "</h3><p>" + esc(v.d[lang]) + "</p>" +
      (other ? '<p class="alt"><a href="' + YT + other + '">' + t.other + "</a></p>" : "") +
      "</article>";
  }

  function renderVideos() {
    var lang = k(), t = T[lang];
    videoGrid.innerHTML = VIDEOS.filter(function (v) { return !v.appOnly; })
      .map(function (v) { return videoCard(v, lang, t); }).join("");
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

  // YouTube's player API, loaded on the first click: unlike a plain iframe it reports a video
  // that cannot play here.
  function loadPlayerApi() {
    if (!playerApi) playerApi = new Promise(function (ok, fail) {
      var s = document.createElement("script");
      s.src = "https://www.youtube.com/iframe_api";
      s.onerror = function () { playerApi = null; fail(); };
      window.onYouTubeIframeAPIReady = ok;
      document.head.appendChild(s);
    });
    return playerApi;
  }

  function stopDialogVideo() {
    playing++;
    clearTimeout(slowTimer);
    if (player) player.destroy();
    player = null;
    vdPlayer.textContent = "";
    vdNote.hidden = true;
  }

  // A video that cannot play in the dialog opens in a window of its own. The browser may block
  // that window when the click is a while ago; the dialog then shows the link to press instead.
  function playInWindow() {
    var w = window.open(vdLink.href, "_blank");
    if (w) { w.opener = null; dialog.close(); } else vdNote.hidden = false;
  }

  function showInDialog(i) {
    var item = dialogVideos[i], slot = document.createElement("div");
    stopDialogVideo();
    var mine = playing;
    function failed() {
      if (mine !== playing) return;
      clearTimeout(slowTimer);
      playInWindow();
    }
    $("vd-title").textContent = item.v.t[k()];
    vdLink.href = vdNote.href = watchUrl(item);
    vdList.querySelectorAll("button").forEach(function (b, n) { b.setAttribute("aria-current", String(n === i)); });
    vdPlayer.appendChild(slot);
    slowTimer = setTimeout(function () { vdNote.hidden = false; }, 12000);
    loadPlayerApi().then(function () {
      if (mine !== playing) return;
      player = new window.YT.Player(slot, {
        host: "https://www.youtube-nocookie.com",
        videoId: item.id,
        playerVars: { autoplay: 1, rel: 0, playsinline: 1, start: item.at },
        events: {
          onReady: function () { clearTimeout(slowTimer); vdNote.hidden = true; },
          onError: failed
        }
      });
    }).catch(failed);
  }

  function openVideos(sub) {
    var lang = k();
    dialogVideos = videosOf(sub, lang);
    vdList.hidden = dialogVideos.length < 2;
    vdList.innerHTML = vdList.hidden ? "" : dialogVideos.map(function (item, i) {
      return '<li><button type="button" data-i="' + i + '">' +
        '<img src="' + (poster(item.v, lang) || "https://i.ytimg.com/vi/" + item.id + "/mqdefault.jpg") + '" alt="" width="96" height="54">' +
        "<span>" + esc(item.v.t[lang]) + "<small>" + (item.v.dur[lang] || item.v.dur.en) + "</small></span></button></li>";
    }).join("");
    dialog.showModal();
    showInDialog(0);
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
    // Ctrl/Cmd/Shift-click, or a browser without <dialog>, keeps the link: YouTube in a new window.
    var w = e.target.closest(".app-video");
    if (w && dialog.showModal && !e.ctrlKey && !e.metaKey && !e.shiftKey) {
      e.preventDefault();
      openVideos(w.getAttribute("data-sub"));
    }
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
  dialog.addEventListener("click", function (e) {
    if (e.target === dialog) { dialog.close(); return; }  // the area around the box
    var b = e.target.closest("[data-i]");
    if (b) showInDialog(Number(b.getAttribute("data-i")));
  });
  dialog.addEventListener("close", stopDialogVideo);
  $("vd-close").addEventListener("click", function () { dialog.close(); });
  var resizeTimer;
  window.addEventListener("resize", function () { clearTimeout(resizeTimer); resizeTimer = setTimeout(markLong, 150); });
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(markLong);

  apply();
})();
