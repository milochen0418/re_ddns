"""繁體中文。"""

STRINGS: dict[str, str] = {
    # ── 頁面外框 ──
    "page_title": "容器記憶體",
    "subtitle": (
        "每 {seconds} 秒取樣一次。記憶體用的是 working set（扣掉可回收的檔案快取），"
        "與 docker stats 相同。"
    ),
    "auto_on": "自動更新中",
    "auto_off": "已暫停",
    "refresh": "更新",
    "back_to_store": "App Store",
    "loading_rows": "讀取容器資料…",
    "language": "語言",

    # ── Docker VM ──
    "vm_title": "Docker VM 記憶體",
    "vm_containers": "{count} 個容器",
    "vm_used": "已用",
    "vm_cache": "快取（可回收）",
    "vm_avail": "可用",
    "vm_swap": "Swap",
    "vm_total": "總量",
    "note_ok": "記憶體充足。",
    "note_tight": "可用記憶體只有 {avail} MB：再開一個吃記憶體的 app 就有 OOM 風險。",
    "note_critical": (
        "只剩 {avail} MB 可用：下一次通話或 Whisper 載入（約 1.7 GB）很可能觸發全域 OOM，"
        "殺掉當下最肥的行程（不一定是兇手）。"
    ),
    "socket_error": "Docker socket 無法存取",

    # ── 每個容器 ──
    "st_running": "執行中",
    "st_half_dead": "OOM 半死",
    "st_restarting": "重啟中",
    "st_starting": "啟動中…",
    "st_stopped": "已停止",
    "badge_platform": "平台",
    "restarts": "重啟 {count} 次",
    "cpu": "CPU",
    "no_limit": "無上限",
    "act_limit": "上限",
    "act_stop": "停止",

    # ── Dev / Non-Dev 選單 ──
    "menu_title": "動作",
    "menu_open": "開啟 App 連結",
    "menu_restart": "重啟",
    "menu_restart_hint": "停止後再啟動容器",
    "menu_to_dev": "切換到 Dev",
    "menu_to_dev_hint": "可熱重載；跑 Vite 開發伺服器，較吃記憶體",
    "menu_to_prod": "切換到 Non-Dev",
    "menu_to_prod_hint": "前端預先編譯、不熱重載，省記憶體",
    "mode_dev": "Dev",
    "mode_prod": "Non-Dev",
    "switch_confirm": "要把 {name} 切換到 {mode} 嗎？會用相同設定重建容器並重新安裝 app，約需 1–2 分鐘。volume 和掛載資料夾裡的資料都會保留。",
    "switch_go": "切換",
    "switch_cancel": "取消",
    "switching": "正在重建容器…",
    "msg_switch_working": "正在把 {name} 切換到 {mode}…",
    "msg_switch_started": "{name} 已改用 {mode} 模式，正在重新安裝，約 1–2 分鐘後恢復。",
    "msg_switch_failed": "{name} 切換失敗，已還原成原本的容器：{error}",
    "msg_switch_busy": "另一個切換還在進行中。",

    # ── 記憶體上限 ──
    "limit_placeholder": "MB（留空 = 放寬到 VM 總量）",
    "limit_apply": "套用",
    "limit_cancel": "取消",
    "limit_hint": (
        "目前用量 {mb} MB。有上限時，超量的是這個容器自己被殺，"
        "不會讓 kernel 挑整台 VM 最肥的行程下手。"
    ),

    # ── 訊息 ──
    "msg_read_failed": "讀取失敗：{error}",
    "msg_stop_protected": "{name} 是平台容器，停掉會讓這個頁面無法使用。",
    "msg_restart_protected": "{name} 無法從自己的頁面重啟（這個連線是它提供的）。",
    "msg_stop_ok": "{name} 已停止。",
    "msg_stop_http": "停止 {name} 失敗（HTTP {code}）。",
    "msg_stop_err": "停止 {name} 失敗：{error}",
    "msg_restart_ok": "{name} 已重啟。",
    "msg_restart_http": "重啟 {name} 失敗（HTTP {code}）。",
    "msg_restart_err": "重啟 {name} 失敗：{error}",
    "msg_no_memtotal": "讀不到 VM 總記憶體，無法解除上限。",
    "msg_not_number": "請輸入 MB 數字，或留空代表解除上限。",
    "msg_min_limit": "上限至少 {min} MB。",
    "msg_below_usage": (
        "{name} 目前就用了 {current} MB，上限設 {wanted} MB 會立刻被 OOM 殺掉。"
        "請設在 {suggested} MB 以上。"
    ),
    "msg_released": (
        "{name} 上限放寬到 VM 總量 {mb} MB（等同解除；Docker 無法在不重建容器的情況下"
        "真正移除上限，要完全移除請重新安裝這個 app）。"
    ),
    "msg_limit_set": "{name} 記憶體上限設為 {mb} MB（超過就只殺它自己）。",
    "msg_limit_err": "設定 {name} 上限失敗：{error}",
    "msg_limit_http": "設定 {name} 上限失敗（HTTP {code}）：{detail}",

    # ── 共用 ──
    "cancel": "取消",
    "list_sep": "、",

    # ══ App Store 頁面 ══
    "store_subtitle": "瀏覽、安裝與管理部署在 re-ddns 後面的 Reflex 應用程式。",
    "store_memory": "記憶體",
    "store_empty": "目錄裡還沒有任何應用程式。",
    "store_empty_hint": "請在 data/appstore_catalog.json 新增項目。",

    # ── 應用程式卡片 ──
    "st_not_installed": "未安裝",
    "st_unknown": "未知",
    "store_open": "開啟",
    "store_start": "啟動",
    "store_stop": "停止",
    "store_install": "安裝",
    "store_uninstall": "移除",
    "store_dev": "Dev",
    "store_installing": "安裝中",
    "store_uninstalling": "移除中",
    "store_view_progress": "查看進度",
    "store_install_failed": "安裝失敗",
    "store_uninstall_failed": "移除失敗",

    # ── 訊息 ──
    "store_started": "已啟動 {name}。",
    "store_stopped": "已停止 {name}。",
    "store_no_socket_start": "無法存取 Docker socket，不能啟動容器。",
    "store_no_socket_stop": "無法存取 Docker socket，不能停止容器。",
    "store_not_installed_yet": "{name} 尚未安裝，請先按「安裝」。",
    "store_start_failed": "啟動失敗（HTTP {code}）。",
    "store_stop_failed": "停止失敗（HTTP {code}）。",
    "store_installed": "{name} 安裝完成！",
    "store_uninstalled": "{name} 已移除：容器、DNS 記錄、nginx 設定與 TLS 憑證都清掉了。",

    # ── 設定表單 ──
    "env_title": "設定 {name}",
    "env_intro": "這個應用程式需要一些設定才能運作。這些值會在安裝時注入容器環境變數並寫入 .env。",
    "env_missing": "請填寫必填欄位：{fields}",

    # ── Dev 表單 ──
    "dev_title": "Dev 模式 — {name}",
    "dev_intro": (
        "輸入本機專案的絕對路徑。容器會 bind mount 這個目錄，跳過 git clone，"
        "直接在正確的 Linux 環境中執行你的 app。改 code 後 Reflex 會自動 hot reload。"
    ),
    "dev_path_label": "本機專案路徑",
    "dev_path_placeholder": "輸入 / 或 ~/ 再按 Tab",
    "dev_path_hint": "Docker host 上的絕對路徑（包含 pyproject.toml 的目錄）",
    "dev_path_keys": " · Tab 補齊 · ↑↓ 選擇 · Esc 收起",
    "dev_path_no_browse": " · 看不到主機資料夾，無法自動補齊",
    "dev_more": "…還有 {count} 個，多打幾個字縮小範圍",
    "dev_install": "Dev 安裝",
    "dev_err_empty": "請輸入本機專案路徑",
    "dev_err_missing": "找不到資料夾：{path}",
    "dev_st_relative": "請輸入絕對路徑（以 / 或 ~/ 開頭）",
    "dev_st_outside": "這裡無法自動補齊（只看得到 {root} 底下）；會直接使用此路徑",
    "dev_st_not_found": "找不到這個資料夾",
    "dev_st_reflex": "✓ Reflex 專案：找到 rxconfig.py",
    "dev_st_reflex_sub": "✓ Reflex 專案（子目錄 {sub}）：找到 rxconfig.py",
    "dev_st_python": "✓ 找到 pyproject.toml",
    "dev_st_python_sub": "✓ 找到 pyproject.toml（子目錄 {sub}）",
    "dev_st_none": "這個資料夾沒有 pyproject.toml，繼續往下選",
    "dev_st_none_sub": "這個資料夾（子目錄 {sub}）沒有 pyproject.toml，繼續往下選",

    # ── 移除確認 ──
    "un_title": "移除 {name}",
    "un_body": (
        "會停止並刪除容器 {container}，再移除它的 DNS 記錄、nginx 設定與 TLS 憑證。"
        "移除後它不再佔用記憶體；之後隨時可以重新安裝。"
    ),
    "un_running": "這個應用程式目前正在執行，會先停止再移除。",
    "un_remove_data": "同時刪除資料（volume 與共享 collection 資料夾）",
    "un_keep_hint": "不勾選就保留，重新安裝會沿用這些資料。Dev 模式掛載的本機資料夾一律不會動。",
    "un_confirm": "移除",

    # ── 進度視窗 ──
    "job_title_install": "安裝 {name}",
    "job_title_uninstall": "移除 {name}",
    "job_busy_install": "安裝進行中…（可關閉視窗，安裝會在背景繼續）",
    "job_busy_uninstall": "移除進行中…（可關閉視窗，移除會在背景繼續）",
    "job_done": "完成",
    "job_sending_install": "正在送出安裝請求…",
    "job_sending_dev_install": "正在送出開發模式安裝請求…",
    "job_sending_uninstall": "正在送出移除請求…",
    "job_install_refused": "無法開始安裝（HTTP {code}）：{detail}",
    "job_dev_install_refused": "無法開始開發模式安裝（HTTP {code}）：{detail}",
    "job_uninstall_refused": "無法開始移除（HTTP {code}）：{detail}",
    "job_unreachable": "無法連線 re-ddns：{error}",
    "job_queued": "排隊中…",
    "job_queued_dev": "排隊中（開發模式）…",
    "job_building_image": "首次安裝：正在建置啟動器映像檔（約需數分鐘）…",
    "job_image_context_missing": "找不到啟動器建置內容：{path}",
    "job_image_build_http": "映像檔建置失敗（HTTP {code}）",
    "job_image_build_failed": "映像檔建置失敗：{error}",
    "job_image_build_exception": "映像檔建置發生例外：{error}",
    "job_image_missing": "映像檔建置後仍找不到。",
    "job_creating": "建立 {name} 容器…",
    "job_creating_dev": "建立 {name} 開發容器…",
    "job_create_failed": "建立容器失敗（HTTP {code}）",
    "job_start_failed": "啟動容器失敗（HTTP {code}）：{error}",
    "job_installing": "{name} 安裝中…",
    "job_installing_dev": "{name} 開發模式安裝中…",
    "job_phase": "{name}：{phase}",
    "job_installed": "{name} 安裝完成，已啟動！",
    "job_container_exited": "{name} 容器已結束（exit code {code}）。",
    "job_install_start_failed": "安裝啟動失敗：{error}",
    "job_dev_install_start_failed": "開發模式安裝啟動失敗：{error}",
    "job_storage_invalid": "共享儲存宣告有誤：{error}",
    "job_stop_waiting": "{name}：等待容器結束…（{seconds} 秒）",
    "job_uninstalled": "{name} 已移除。",
    "job_uninstall_failed": "{name} 移除失敗：{error}",
    "phase_queued": "排隊中",
    "phase_preparing_image": "準備啟動器映像檔",
    "phase_building_image": "建置啟動器映像檔",
    "phase_creating": "建立容器",
    "phase_starting_container": "啟動容器",
    "phase_dev_mount": "使用本機掛載的原始碼",
    "phase_apt_packages": "安裝系統套件",
    "phase_cloning": "下載程式碼",
    "phase_cloning_deps": "下載相依套件庫",
    "phase_installing_deps": "安裝相依套件",
    "phase_initializing": "初始化 Reflex",
    "phase_registering": "註冊 DNS / nginx",
    "phase_starting_app": "啟動應用程式",
    "phase_running": "完成，應用程式執行中",
    "phase_stopping": "停止容器",
    "phase_removing_container": "刪除容器",
    "phase_unregistering": "移除註冊與 DNS 記錄",
    "phase_nginx": "更新 nginx 設定",
    "phase_cert": "移除 TLS 憑證",
    "phase_data": "刪除資料 volume",
    "phase_done": "完成，已移除",
}
