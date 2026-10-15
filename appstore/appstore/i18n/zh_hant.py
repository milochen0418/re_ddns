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
    "st_stopped": "已停止",
    "badge_platform": "平台",
    "restarts": "重啟 {count} 次",
    "cpu": "CPU",
    "no_limit": "無上限",
    "act_limit": "上限",
    "act_restart": "重啟",
    "act_stop": "停止",

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
}
