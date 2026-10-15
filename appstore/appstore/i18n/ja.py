"""日本語。"""

STRINGS: dict[str, str] = {
    # ── ページ全体 ──
    "page_title": "コンテナのメモリ",
    "subtitle": (
        "{seconds} 秒ごとに取得します。メモリは working set（回収できない分）で、"
        "docker stats と同じ値です。"
    ),
    "auto_on": "自動更新中",
    "auto_off": "一時停止",
    "refresh": "更新",
    "back_to_store": "App Store",
    "loading_rows": "コンテナを読み込み中…",
    "language": "言語",

    # ── Docker VM ──
    "vm_title": "Docker VM のメモリ",
    "vm_containers": "コンテナ {count} 個",
    "vm_used": "使用中",
    "vm_cache": "キャッシュ（回収可）",
    "vm_avail": "利用可能",
    "vm_swap": "スワップ",
    "vm_total": "合計",
    "note_ok": "メモリに余裕があります。",
    "note_tight": (
        "利用可能なメモリは {avail} MB だけです。メモリを多く使う app をもう 1 つ開くと "
        "OOM の恐れがあります。"
    ),
    "note_critical": (
        "残り {avail} MB しかありません。次の通話や Whisper の読み込み（約 1.7 GB）で "
        "VM 全体の OOM が起きる可能性が高く、その時点で最も大きいプロセスが"
        "（原因とは限らないのに）強制終了されます。"
    ),
    "socket_error": "Docker socket にアクセスできません",

    # ── コンテナごと ──
    "st_running": "実行中",
    "st_half_dead": "OOM 半死状態",
    "st_restarting": "再起動中",
    "st_starting": "起動中…",
    "st_stopped": "停止中",
    "badge_platform": "基盤",
    "restarts": "再起動 {count} 回",
    "cpu": "CPU",
    "no_limit": "上限なし",
    "act_limit": "上限",
    "act_stop": "停止",

    # ── Dev / Non-Dev メニュー ──
    "menu_title": "操作",
    "menu_open": "App のリンクを開く",
    "menu_restart": "再起動",
    "menu_restart_hint": "コンテナを停止して起動し直します",
    "menu_to_dev": "Dev に切り替え",
    "menu_to_dev_hint": "ホットリロードあり。Vite 開発サーバーでメモリ多め",
    "menu_to_prod": "Non-Dev に切り替え",
    "menu_to_prod_hint": "ビルド済みフロントエンド。ホットリロードなし、省メモリ",
    "mode_dev": "Dev",
    "mode_prod": "Non-Dev",
    "switch_confirm": "{name} を {mode} に切り替えますか？同じ設定でコンテナを作り直し、app を再インストールします（1〜2 分ほど）。ボリュームとマウントしたフォルダのデータは残ります。",
    "switch_go": "切り替える",
    "switch_cancel": "キャンセル",
    "switching": "コンテナを作り直しています…",
    "msg_switch_working": "{name} を {mode} に切り替えています…",
    "msg_switch_started": "{name} は {mode} で動作します。再インストール中で、1〜2 分ほどで戻ります。",
    "msg_switch_failed": "{name} の切り替えに失敗したため、元のコンテナに戻しました: {error}",
    "msg_switch_busy": "別の切り替えがまだ実行中です。",

    # ── メモリ上限 ──
    "limit_placeholder": "MB（空欄 = VM 合計まで緩める）",
    "limit_apply": "適用",
    "limit_cancel": "キャンセル",
    "limit_hint": (
        "現在の使用量は {mb} MB です。上限を設定すると、使いすぎたときに終了されるのは"
        "このコンテナ自身になり、カーネルが VM 内で最大のプロセスを選ぶことはありません。"
    ),

    # ── メッセージ ──
    "msg_read_failed": "読み込みに失敗しました: {error}",
    "msg_stop_protected": "{name} は基盤コンテナです。停止するとこのページが使えなくなります。",
    "msg_restart_protected": "{name} は自分のページから再起動できません（この接続を提供しています）。",
    "msg_stop_ok": "{name} を停止しました。",
    "msg_stop_http": "{name} の停止に失敗しました（HTTP {code}）。",
    "msg_stop_err": "{name} の停止に失敗しました: {error}",
    "msg_restart_ok": "{name} を再起動しました。",
    "msg_restart_http": "{name} の再起動に失敗しました（HTTP {code}）。",
    "msg_restart_err": "{name} の再起動に失敗しました: {error}",
    "msg_no_memtotal": "VM の合計メモリが読めないため、上限を解除できません。",
    "msg_not_number": "MB の数値を入力してください。空欄にすると上限を解除します。",
    "msg_min_limit": "上限は {min} MB 以上にしてください。",
    "msg_below_usage": (
        "{name} は現在 {current} MB 使っています。上限を {wanted} MB にすると直ちに "
        "OOM で終了されます。{suggested} MB 以上にしてください。"
    ),
    "msg_released": (
        "{name} の上限を VM 合計の {mb} MB まで緩めました（実質的に上限なしです。Docker は"
        "コンテナを作り直さずに上限を完全に削除できないため、完全に外すには app を"
        "再インストールしてください）。"
    ),
    "msg_limit_set": "{name} のメモリ上限を {mb} MB にしました。超えたときに終了されるのはこのコンテナだけです。",
    "msg_limit_err": "{name} の上限設定に失敗しました: {error}",
    "msg_limit_http": "{name} の上限設定に失敗しました（HTTP {code}）: {detail}",
}
