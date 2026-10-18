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

    # ── 共用 ──
    "cancel": "取消",
    "list_sep": "、",

    # ══ App Store 页面 ══
    "store_subtitle": "浏览、安装和管理部署在 re-ddns 后面的 Reflex 应用。",
    "store_memory": "内存",
    "store_empty": "目录里还没有任何应用。",
    "store_empty_hint": "请在 data/appstore_catalog.json 中添加条目。",

    # ── 应用卡片 ──
    "st_not_installed": "未安装",
    "st_unknown": "未知",
    "store_open": "打开",
    "store_start": "启动",
    "store_stop": "停止",
    "store_install": "安装",
    "store_uninstall": "卸载",
    "store_dev": "Dev",
    "store_installing": "安装中",
    "store_uninstalling": "卸载中",
    "store_view_progress": "查看进度",
    "store_install_failed": "安装失败",
    "store_uninstall_failed": "卸载失败",

    # ── 消息 ──
    "store_started": "已启动 {name}。",
    "store_stopped": "已停止 {name}。",
    "store_no_socket_start": "无法访问 Docker socket，不能启动容器。",
    "store_no_socket_stop": "无法访问 Docker socket，不能停止容器。",
    "store_not_installed_yet": "{name} 尚未安装，请先点「安装」。",
    "store_start_failed": "启动失败（HTTP {code}）。",
    "store_stop_failed": "停止失败（HTTP {code}）。",
    "store_installed": "{name} 安装完成！",
    "store_uninstalled": "{name} 已卸载：容器、DNS 记录、nginx 配置和 TLS 证书都已清除。",

    # ── 设置表单 ──
    "env_title": "设置 {name}",
    "env_intro": "这个应用需要一些设置才能运行。这些值会在安装时注入容器的环境变量，并写入 .env。",
    "env_missing": "请填写必填字段：{fields}",

    # ── Dev 表单 ──
    "dev_title": "Dev 模式 — {name}",
    "dev_intro": (
        "输入本地项目的绝对路径。容器会 bind mount 这个目录，跳过 git clone，"
        "直接在正确的 Linux 环境中运行你的 app。改代码后 Reflex 会自动热重载。"
    ),
    "dev_path_label": "本地项目路径",
    "dev_path_placeholder": "输入 / 或 ~/ 再按 Tab",
    "dev_path_hint": "Docker 主机上的绝对路径（包含 pyproject.toml 的目录）",
    "dev_path_keys": " · Tab 补全 · ↑↓ 选择 · Esc 收起",
    "dev_path_no_browse": " · 看不到主机文件夹，无法自动补全",
    "dev_more": "…还有 {count} 个，多输入几个字缩小范围",
    "dev_install": "Dev 安装",
    "dev_err_empty": "请输入本地项目路径",
    "dev_err_missing": "找不到文件夹：{path}",
    "dev_st_relative": "请输入绝对路径（以 / 或 ~/ 开头）",
    "dev_st_outside": "这里无法自动补全（只能看到 {root} 下面）；会直接使用此路径",
    "dev_st_not_found": "找不到这个文件夹",
    "dev_st_reflex": "✓ Reflex 项目：找到 rxconfig.py",
    "dev_st_reflex_sub": "✓ Reflex 项目（子目录 {sub}）：找到 rxconfig.py",
    "dev_st_python": "✓ 找到 pyproject.toml",
    "dev_st_python_sub": "✓ 找到 pyproject.toml（子目录 {sub}）",
    "dev_st_none": "这个文件夹没有 pyproject.toml，继续往下选",
    "dev_st_none_sub": "这个文件夹（子目录 {sub}）没有 pyproject.toml，继续往下选",

    # ── 卸载确认 ──
    "un_title": "卸载 {name}",
    "un_body": (
        "会停止并删除容器 {container}，再移除它的 DNS 记录、nginx 配置和 TLS 证书。"
        "卸载后它不再占用内存；之后随时可以重新安装。"
    ),
    "un_running": "这个应用正在运行，会先停止再卸载。",
    "un_remove_data": "同时删除数据 volume",
    "un_keep_hint": "不勾选就保留，重新安装会沿用这些数据。Dev 模式挂载的本地文件夹一律不会动。",
    "un_confirm": "卸载",

    # ── 进度窗口 ──
    "job_title_install": "安装 {name}",
    "job_title_uninstall": "卸载 {name}",
    "job_busy_install": "安装进行中…（可关闭窗口，安装会在后台继续）",
    "job_busy_uninstall": "卸载进行中…（可关闭窗口，卸载会在后台继续）",
    "job_done": "完成",
    "job_sending_install": "正在发送安装请求…",
    "job_sending_dev_install": "正在发送开发模式安装请求…",
    "job_sending_uninstall": "正在发送卸载请求…",
    "job_install_refused": "无法开始安装（HTTP {code}）：{detail}",
    "job_dev_install_refused": "无法开始开发模式安装（HTTP {code}）：{detail}",
    "job_uninstall_refused": "无法开始卸载（HTTP {code}）：{detail}",
    "job_unreachable": "无法连接 re-ddns：{error}",
    "job_queued": "排队中…",
    "job_queued_dev": "排队中（开发模式）…",
    "job_building_image": "首次安装：正在构建启动器镜像（约需几分钟）…",
    "job_image_context_missing": "找不到启动器的构建文件：{path}",
    "job_image_build_http": "镜像构建失败（HTTP {code}）",
    "job_image_build_failed": "镜像构建失败：{error}",
    "job_image_build_exception": "镜像构建出现异常：{error}",
    "job_image_missing": "镜像构建完成后仍然找不到。",
    "job_creating": "创建 {name} 容器…",
    "job_creating_dev": "创建 {name} 开发容器…",
    "job_create_failed": "创建容器失败（HTTP {code}）",
    "job_start_failed": "启动容器失败（HTTP {code}）：{error}",
    "job_installing": "{name} 安装中…",
    "job_installing_dev": "{name} 开发模式安装中…",
    "job_phase": "{name}：{phase}",
    "job_installed": "{name} 安装完成，已启动！",
    "job_container_exited": "{name} 容器已退出（exit code {code}）。",
    "job_install_start_failed": "安装启动失败：{error}",
    "job_dev_install_start_failed": "开发模式安装启动失败：{error}",
    "job_stop_waiting": "{name}：等待容器退出…（{seconds} 秒）",
    "job_uninstalled": "{name} 已卸载。",
    "job_uninstall_failed": "{name} 卸载失败：{error}",
    "phase_queued": "排队中",
    "phase_preparing_image": "准备启动器镜像",
    "phase_building_image": "构建启动器镜像",
    "phase_creating": "创建容器",
    "phase_starting_container": "启动容器",
    "phase_dev_mount": "使用本地挂载的源代码",
    "phase_apt_packages": "安装系统软件包",
    "phase_cloning": "下载代码",
    "phase_cloning_deps": "下载依赖仓库",
    "phase_installing_deps": "安装依赖",
    "phase_initializing": "初始化 Reflex",
    "phase_registering": "注册 DNS / nginx",
    "phase_starting_app": "启动应用",
    "phase_running": "完成，应用运行中",
    "phase_stopping": "停止容器",
    "phase_removing_container": "删除容器",
    "phase_unregistering": "移除注册和 DNS 记录",
    "phase_nginx": "更新 nginx 配置",
    "phase_cert": "移除 TLS 证书",
    "phase_data": "删除数据 volume",
    "phase_done": "完成，已卸载",
}
