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

    # ── 共通 ──
    "cancel": "キャンセル",
    "list_sep": "、",

    # ══ App Store ページ ══
    "store_subtitle": "re-ddns の後ろで動く Reflex アプリを探して、インストールし、管理します。",
    "store_memory": "メモリ",
    "store_empty": "カタログにアプリがまだありません。",
    "store_empty_hint": "data/appstore_catalog.json に項目を追加してください。",

    # ── アプリのカード ──
    "st_not_installed": "未インストール",
    "st_unknown": "不明",
    "store_open": "開く",
    "store_start": "起動",
    "store_stop": "停止",
    "store_install": "インストール",
    "store_uninstall": "アンインストール",
    "store_dev": "Dev",
    "store_installing": "インストール中",
    "store_uninstalling": "アンインストール中",
    "store_view_progress": "進捗を見る",
    "store_install_failed": "インストール失敗",
    "store_uninstall_failed": "アンインストール失敗",

    # ── メッセージ ──
    "store_started": "{name} を起動しました。",
    "store_stopped": "{name} を停止しました。",
    "store_no_socket_start": "Docker socket にアクセスできないため、コンテナを起動できません。",
    "store_no_socket_stop": "Docker socket にアクセスできないため、コンテナを停止できません。",
    "store_not_installed_yet": "{name} はまだインストールされていません。先に「インストール」を押してください。",
    "store_start_failed": "起動に失敗しました（HTTP {code}）。",
    "store_stop_failed": "停止に失敗しました（HTTP {code}）。",
    "store_installed": "{name} のインストールが完了しました！",
    "store_uninstalled": "{name} を削除しました。コンテナ、DNS レコード、nginx 設定、TLS 証明書はすべて消えています。",

    # ── 設定フォーム ──
    "env_title": "{name} の設定",
    "env_intro": (
        "このアプリを動かすにはいくつかの設定が必要です。値はインストール時に"
        "コンテナの環境変数として渡され、.env にも書き込まれます。"
    ),
    "env_missing": "必須項目を入力してください: {fields}",

    # ── Dev フォーム ──
    "dev_title": "Dev モード — {name}",
    "dev_intro": (
        "ローカルのプロジェクトの絶対パスを入力してください。コンテナはこのフォルダを "
        "bind mount し、git clone をせずに、正しい Linux 環境でアプリを実行します。"
        "コードを変更すると Reflex が自動でホットリロードします。"
    ),
    "dev_path_label": "ローカルのプロジェクトのパス",
    "dev_path_placeholder": "/ か ~/ を入力して Tab",
    "dev_path_hint": "Docker ホスト上の絶対パス（pyproject.toml があるフォルダ）",
    "dev_path_keys": " · Tab で補完 · ↑↓ で選択 · Esc で閉じる",
    "dev_path_no_browse": " · ホストのフォルダが見えないため補完できません",
    "dev_more": "…ほかに {count} 個あります。もう少し入力して絞り込んでください",
    "dev_install": "Dev インストール",
    "dev_err_empty": "ローカルのプロジェクトのパスを入力してください",
    "dev_err_missing": "フォルダが見つかりません: {path}",
    "dev_st_relative": "絶対パスを入力してください（/ か ~/ で始まる）",
    "dev_st_outside": "ここでは補完できません（{root} の下だけが見えます）。入力したパスをそのまま使います",
    "dev_st_not_found": "このフォルダは見つかりません",
    "dev_st_reflex": "✓ Reflex プロジェクト: rxconfig.py があります",
    "dev_st_reflex_sub": "✓ Reflex プロジェクト（サブフォルダ {sub}）: rxconfig.py があります",
    "dev_st_python": "✓ pyproject.toml があります",
    "dev_st_python_sub": "✓ pyproject.toml があります（サブフォルダ {sub}）",
    "dev_st_none": "このフォルダには pyproject.toml がありません。さらに下を選んでください",
    "dev_st_none_sub": "このフォルダ（サブフォルダ {sub}）には pyproject.toml がありません。さらに下を選んでください",

    # ── アンインストールの確認 ──
    "un_title": "{name} のアンインストール",
    "un_body": (
        "コンテナ {container} を停止して削除し、DNS レコード、nginx 設定、TLS 証明書も"
        "削除します。削除後はメモリを使いません。いつでも再インストールできます。"
    ),
    "un_running": "このアプリは実行中です。停止してから削除します。",
    "un_remove_data": "データのボリュームも削除する",
    "un_keep_hint": (
        "チェックしなければ残り、再インストール時にそのデータを使います。"
        "Dev モードでマウントしたローカルのフォルダには一切触れません。"
    ),
    "un_confirm": "アンインストール",

    # ── 進捗ウィンドウ ──
    "job_title_install": "{name} のインストール",
    "job_title_uninstall": "{name} のアンインストール",
    "job_busy_install": "インストール中…（ウィンドウを閉じても、インストールはバックグラウンドで続きます）",
    "job_busy_uninstall": "アンインストール中…（ウィンドウを閉じても、削除はバックグラウンドで続きます）",
    "job_done": "完了",
    "job_sending_install": "インストールのリクエストを送信しています…",
    "job_sending_dev_install": "Dev モードのインストールのリクエストを送信しています…",
    "job_sending_uninstall": "アンインストールのリクエストを送信しています…",
    "job_install_refused": "インストールを開始できませんでした（HTTP {code}）: {detail}",
    "job_dev_install_refused": "Dev モードのインストールを開始できませんでした（HTTP {code}）: {detail}",
    "job_uninstall_refused": "アンインストールを開始できませんでした（HTTP {code}）: {detail}",
    "job_unreachable": "re-ddns に接続できません: {error}",
    "job_queued": "待機中…",
    "job_queued_dev": "待機中（Dev モード）…",
    "job_building_image": "初回インストール: ランチャーのイメージをビルドしています（数分かかります）…",
    "job_image_context_missing": "ランチャーのビルド用ファイルが見つかりません: {path}",
    "job_image_build_http": "イメージのビルドに失敗しました（HTTP {code}）",
    "job_image_build_failed": "イメージのビルドに失敗しました: {error}",
    "job_image_build_exception": "イメージのビルド中に例外が発生しました: {error}",
    "job_image_missing": "ビルド後もイメージが見つかりません。",
    "job_creating": "{name} のコンテナを作成しています…",
    "job_creating_dev": "{name} の Dev コンテナを作成しています…",
    "job_create_failed": "コンテナの作成に失敗しました（HTTP {code}）",
    "job_start_failed": "コンテナの起動に失敗しました（HTTP {code}）: {error}",
    "job_installing": "{name} をインストールしています…",
    "job_installing_dev": "{name} を Dev モードでインストールしています…",
    "job_phase": "{name}: {phase}",
    "job_installed": "{name} のインストールが完了し、起動しました！",
    "job_container_exited": "{name} のコンテナが終了しました（exit code {code}）。",
    "job_install_start_failed": "インストールを開始できませんでした: {error}",
    "job_dev_install_start_failed": "Dev モードのインストールを開始できませんでした: {error}",
    "job_stop_waiting": "{name}: コンテナの終了を待っています…（{seconds} 秒）",
    "job_uninstalled": "{name} を削除しました。",
    "job_uninstall_failed": "{name} の削除に失敗しました: {error}",
    "phase_queued": "待機中",
    "phase_preparing_image": "ランチャーのイメージを準備",
    "phase_building_image": "ランチャーのイメージをビルド",
    "phase_creating": "コンテナを作成",
    "phase_starting_container": "コンテナを起動",
    "phase_dev_mount": "ローカルにマウントしたソースを使用",
    "phase_apt_packages": "システムパッケージをインストール",
    "phase_cloning": "コードをダウンロード",
    "phase_cloning_deps": "依存リポジトリをダウンロード",
    "phase_installing_deps": "依存パッケージをインストール",
    "phase_initializing": "Reflex を初期化",
    "phase_registering": "DNS / nginx に登録",
    "phase_starting_app": "アプリを起動",
    "phase_running": "完了。アプリは実行中です",
    "phase_stopping": "コンテナを停止",
    "phase_removing_container": "コンテナを削除",
    "phase_unregistering": "登録と DNS レコードを削除",
    "phase_nginx": "nginx 設定を更新",
    "phase_cert": "TLS 証明書を削除",
    "phase_data": "データのボリュームを削除",
    "phase_done": "完了。削除しました",
}
