"""简体中文。"""

STRINGS: dict[str, str] = {
    # ── 页面外框 ──
    "page_title": "容器内存",
    "subtitle": (
        "每 {seconds} 秒采样一次。内存用的是 working set（扣掉可回收的文件缓存），"
        "与 docker stats 相同。"
    ),
    "auto_on": "自动刷新中",
    "auto_off": "已暂停",
    "refresh": "刷新",
    "back_to_store": "App Store",
    "loading_rows": "读取容器数据…",
    "language": "语言",

    # ── Docker VM ──
    "vm_title": "Docker VM 内存",
    "vm_containers": "{count} 个容器",
    "vm_used": "已用",
    "vm_cache": "缓存（可回收）",
    "vm_avail": "可用",
    "vm_swap": "Swap",
    "vm_total": "总量",
    "note_ok": "内存充足。",
    "note_tight": "可用内存只有 {avail} MB：再开一个吃内存的 app 就有 OOM 风险。",
    "note_critical": (
        "只剩 {avail} MB 可用：下一次通话或 Whisper 加载（约 1.7 GB）很可能触发全局 OOM，"
        "杀掉当下最占内存的进程（不一定是肇事者）。"
    ),
    "socket_error": "Docker socket 无法访问",

    # ── 每个容器 ──
    "st_running": "运行中",
    "st_half_dead": "OOM 半死",
    "st_restarting": "重启中",
    "st_starting": "启动中…",
    "st_stopped": "已停止",
    "badge_platform": "平台",
    "restarts": "重启 {count} 次",
    "cpu": "CPU",
    "no_limit": "无上限",
    "act_limit": "上限",
    "act_stop": "停止",

    # ── Dev / Non-Dev 菜单 ──
    "menu_title": "操作",
    "menu_open": "打开 App 链接",
    "menu_restart": "重启",
    "menu_restart_hint": "停止后再启动容器",
    "menu_to_dev": "切换到 Dev",
    "menu_to_dev_hint": "可热重载；运行 Vite 开发服务器，较占内存",
    "menu_to_prod": "切换到 Non-Dev",
    "menu_to_prod_hint": "前端预先编译、不热重载，省内存",
    "mode_dev": "Dev",
    "mode_prod": "Non-Dev",
    "switch_confirm": "要把 {name} 切换到 {mode} 吗？会用相同设置重建容器并重新安装 app，约需 1–2 分钟。volume 和挂载文件夹里的数据都会保留。",
    "switch_go": "切换",
    "switch_cancel": "取消",
    "switching": "正在重建容器…",
    "msg_switch_working": "正在把 {name} 切换到 {mode}…",
    "msg_switch_started": "{name} 已改用 {mode} 模式，正在重新安装，约 1–2 分钟后恢复。",
    "msg_switch_failed": "{name} 切换失败，已还原为原来的容器：{error}",
    "msg_switch_busy": "另一个切换还在进行中。",

    # ── 内存上限 ──
    "limit_placeholder": "MB（留空 = 放宽到 VM 总量）",
    "limit_apply": "应用",
    "limit_cancel": "取消",
    "limit_hint": (
        "当前用量 {mb} MB。设了上限后，超量时被杀的是这个容器自己，"
        "而不会让内核挑整台 VM 最占内存的进程下手。"
    ),

    # ── 消息 ──
    "msg_read_failed": "读取失败：{error}",
    "msg_stop_protected": "{name} 是平台容器，停掉会让这个页面无法使用。",
    "msg_restart_protected": "{name} 无法从自己的页面重启（这个连接是它提供的）。",
    "msg_stop_ok": "{name} 已停止。",
    "msg_stop_http": "停止 {name} 失败（HTTP {code}）。",
    "msg_stop_err": "停止 {name} 失败：{error}",
    "msg_restart_ok": "{name} 已重启。",
    "msg_restart_http": "重启 {name} 失败（HTTP {code}）。",
    "msg_restart_err": "重启 {name} 失败：{error}",
    "msg_no_memtotal": "读不到 VM 总内存，无法解除上限。",
    "msg_not_number": "请输入 MB 数字，或留空代表解除上限。",
    "msg_min_limit": "上限至少 {min} MB。",
    "msg_below_usage": (
        "{name} 当前就用了 {current} MB，上限设 {wanted} MB 会立刻被 OOM 杀掉。"
        "请设在 {suggested} MB 以上。"
    ),
    "msg_released": (
        "{name} 上限放宽到 VM 总量 {mb} MB（等同解除；Docker 无法在不重建容器的情况下"
        "真正移除上限，要彻底移除请重新安装这个 app）。"
    ),
    "msg_limit_set": "{name} 内存上限设为 {mb} MB（超过就只杀它自己）。",
    "msg_limit_err": "设置 {name} 上限失败：{error}",
    "msg_limit_http": "设置 {name} 上限失败（HTTP {code}）：{detail}",
}
