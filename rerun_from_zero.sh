#!/usr/bin/env bash
#
# ── rerun_from_zero.sh ─────────────────────────────────────────────────────
#
# 一支「聰明的」互動引導腳本：不論你目前環境為何（從沒跑過、跑到一半壞掉、
# 缺套件、port 被佔用、DNS / CA 沒設好…），照著它一路走，就能把整套
#   home / testapp / testapp2 / testapp3 / aapps (App Store)
# 透過 HTTPS 順利跑起來。
#
# 它會在每個有風險或需要決定的步驟，用 y/N 問你；需要密碼的地方（sudo、
# 鑰匙圈）會直接在終端機跟你要，本腳本不會代你輸入或儲存任何密碼。
#
# 對應文件：RUN_FROM_ZERO.md（本腳本即為其自動化版本）。
#
# 用法：
#   ./rerun_from_zero.sh            # 完整互動引導
#   ./rerun_from_zero.sh --yes      # 全部採用建議預設（非互動，慎用）
#   ./rerun_from_zero.sh --iface Ethernet   # 有線網路
#   ./rerun_from_zero.sh --help
#
# 注意：故意不使用 `set -e`，因為遇到問題時我們要「引導」而非直接中止。
# ───────────────────────────────────────────────────────────────────────────

set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── 顏色 ──
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'
CYAN='\033[0;36m'; BOLD='\033[1m'; DIM='\033[2m'; NC='\033[0m'

step()  { echo -e "\n${BOLD}${CYAN}━━ $* ━━${NC}"; }
log()   { echo -e "${CYAN}›${NC} $*"; }
ok()    { echo -e "${GREEN}✓${NC} $*"; }
warn()  { echo -e "${YELLOW}!${NC} $*"; }
err()   { echo -e "${RED}✗${NC} $*" >&2; }
hint()  { echo -e "  ${DIM}$*${NC}"; }

# ── 參數 ──
ASSUME_YES=false
IFACE="Wi-Fi"
COMPOSE_FILE="docker-compose.test.yml"
DOMAINS=(home testapp testapp2 testapp3 aapps)

usage() {
    cat <<'EOF'
Usage: ./rerun_from_zero.sh [OPTIONS]

從零（或任何半殘狀態）一路引導把整套 re-ddns 環境跑起來。

Options:
  --yes, -y           全部採用建議預設，不再逐項詢問（非互動，慎用）。
  --iface <name>      設定 DNS 時使用的網路介面（預設 Wi-Fi；有線用 Ethernet）。
  --help, -h          顯示說明後離開。

流程：
  1. 環境檢查（macOS / docker / curl / dig…，缺的會引導安裝）
  2. 確認 Docker Desktop 已啟動
  3. 釋放 port 53（必要時關閉 mDNSResponder）
  4. build + 啟動整套 Docker 堆疊（可選擇是否清除舊資料）
  5. 繞過 DNS 驗證後端（health-check 誤報的正解）
  6. 把 Mac DNS 指向本機 BIND9（./macos_set_dns.sh --join）
  7. 安裝 Local CA 憑證（讓 HTTPS 受信任）
  8. 最終驗收 + 總結
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --yes|-y) ASSUME_YES=true; shift ;;
        --iface)  IFACE="${2:-Wi-Fi}"; shift 2 ;;
        --help|-h) usage; exit 0 ;;
        *) err "未知參數：$1"; echo; usage; exit 1 ;;
    esac
done

# ── 互動 y/N 詢問 ───────────────────────────────────────────────────────────
# confirm "問題" [default]   default 為 Y 或 N（預設 Y）
confirm() {
    local q="$1"; local def="${2:-Y}"; local ans prompt
    if [[ "$def" == "Y" ]]; then prompt="[Y/n]"; else prompt="[y/N]"; fi
    if $ASSUME_YES; then
        echo -e "${YELLOW}?${NC} $q $prompt ${DIM}→ --yes 自動選 ${def}${NC}"
        [[ "$def" == "Y" ]]
        return
    fi
    if [[ ! -t 0 ]]; then
        # 沒有終端機可互動 → 採用預設
        [[ "$def" == "Y" ]]
        return
    fi
    while true; do
        read -r -p "$(echo -e "${YELLOW}?${NC} $q $prompt ")" ans || ans=""
        ans="${ans:-$def}"
        case "$ans" in
            [Yy]*) return 0 ;;
            [Nn]*) return 1 ;;
            *) echo "  請輸入 y 或 n" ;;
        esac
    done
}

pause_enter() {
    $ASSUME_YES && return 0
    [[ -t 0 ]] || return 0
    read -r -p "$(echo -e "  ${DIM}做完後按 Enter 繼續…${NC}")" _ || true
}

# ── 後端驗證（繞過主機 DNS，直接打 nginx）─────────────────────────────────
verify_backend() {
    local all_ok=true code
    for d in "${DOMAINS[@]}"; do
        code=$(curl -sk -o /dev/null -w "%{http_code}" --max-time 8 \
            --resolve "${d}.reflex-ddns.com:443:127.0.0.1" \
            "https://${d}.reflex-ddns.com/" 2>/dev/null || echo "000")
        if [[ "$code" == "200" ]]; then
            ok "${d}.reflex-ddns.com → HTTPS ${code}"
        else
            warn "${d}.reflex-ddns.com → HTTPS ${code}"
            all_ok=false
        fi
    done
    $all_ok
}

# ── 主機端 DNS 驗證 ─────────────────────────────────────────────────────────
verify_host_dns() {
    local all_ok=true ip
    for d in "${DOMAINS[@]}"; do
        ip=$(dig "${d}.reflex-ddns.com" +short 2>/dev/null | tail -1)
        if [[ -n "$ip" ]]; then
            ok "${d}.reflex-ddns.com → ${ip}"
        else
            warn "${d}.reflex-ddns.com → (無法解析)"
            all_ok=false
        fi
    done
    $all_ok
}

echo -e "${BOLD}Re-DDNS — Run From Zero 引導腳本${NC}"
hint "專案目錄：$SCRIPT_DIR"
$ASSUME_YES && warn "--yes 模式：所有問題自動採用建議預設。"

# ════════════════════════════════════════════════════════════════════════════
step "步驟 1/8 · 環境檢查"
# ════════════════════════════════════════════════════════════════════════════

OS="$(uname)"
if [[ "$OS" != "Darwin" ]]; then
    warn "偵測到非 macOS（${OS}）。本腳本的 DNS / CA 步驟針對 macOS 設計。"
    confirm "仍要繼續嗎？" N || { err "已中止。"; exit 1; }
fi

HAS_BREW=false
command -v brew >/dev/null 2>&1 && HAS_BREW=true

# Docker：必要
if ! command -v docker >/dev/null 2>&1; then
    err "找不到 docker 指令——需要安裝 Docker Desktop for Mac。"
    if $HAS_BREW && confirm "用 Homebrew 安裝 Docker Desktop（brew install --cask docker）？" Y; then
        brew install --cask docker || err "brew 安裝失敗，請手動安裝。"
    else
        hint "請至 https://www.docker.com/products/docker-desktop/ 下載安裝後重跑本腳本。"
    fi
    command -v docker >/dev/null 2>&1 || { err "docker 仍不存在，先安裝再重跑。"; exit 1; }
fi
ok "docker：$(command -v docker)"

# 其他工具：缺了會影響部分步驟，盡量引導補齊
declare -a MISSING=()
for t in curl dig lsof; do
    command -v "$t" >/dev/null 2>&1 || MISSING+=("$t")
done
if [[ "$OS" == "Darwin" ]]; then
    command -v networksetup >/dev/null 2>&1 || MISSING+=("networksetup")
fi
if [[ ${#MISSING[@]} -gt 0 ]]; then
    warn "以下工具缺少：${MISSING[*]}"
    # dig 由 bind 提供；其餘多為系統內建
    if printf '%s\n' "${MISSING[@]}" | grep -qx "dig" && $HAS_BREW; then
        confirm "用 Homebrew 安裝 dig（brew install bind）？" Y && brew install bind || true
    fi
    hint "networksetup / lsof / curl 通常為 macOS 內建；若缺請檢查系統。"
else
    ok "curl / dig / lsof / networksetup 皆可用"
fi

# 必要檔案
for f in docker_restart.sh macos_set_dns.sh detect_external_ip.sh "$COMPOSE_FILE"; do
    if [[ ! -e "$f" ]]; then
        err "缺少必要檔案：${f}（請確認在正確的專案根目錄）。"
        exit 1
    fi
done
chmod +x docker_restart.sh macos_set_dns.sh 2>/dev/null || true
ok "專案腳本與 compose 檔齊備"

# ════════════════════════════════════════════════════════════════════════════
step "步驟 2/8 · 確認 Docker Desktop 已啟動"
# ════════════════════════════════════════════════════════════════════════════

if docker info >/dev/null 2>&1; then
    ok "Docker daemon 已就緒"
else
    warn "Docker daemon 沒在跑。"
    if [[ "$OS" == "Darwin" ]] && confirm "啟動 Docker Desktop（open -a Docker）並等待就緒？" Y; then
        open -a Docker 2>/dev/null || true
        log "等待 Docker daemon 啟動中（最多 90 秒）…"
        for i in $(seq 1 90); do
            if docker info >/dev/null 2>&1; then break; fi
            sleep 1
            (( i % 10 == 0 )) && hint "仍在等待… (${i}s)"
        done
    fi
    if docker info >/dev/null 2>&1; then
        ok "Docker daemon 已就緒"
    else
        err "Docker daemon 仍無法連線。請手動啟動 Docker Desktop 後重跑本腳本。"
        exit 1
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 3/8 · 釋放 port 53（BIND9 需要）"
# ════════════════════════════════════════════════════════════════════════════

PORT53_USERS=""
if command -v lsof >/dev/null 2>&1; then
    PORT53_USERS=$(sudo -n lsof -nP -i :53 2>/dev/null || lsof -nP -i :53 2>/dev/null || true)
fi

if [[ -z "$PORT53_USERS" ]]; then
    ok "port 53 目前沒有被佔用（或需 sudo 才看得到；稍後啟動若衝突會再提示）。"
else
    warn "port 53 正被以下程序佔用："
    echo "$PORT53_USERS" | sed 's/^/    /'
    if echo "$PORT53_USERS" | grep -qi "mDNSResponder"; then
        hint "這是 macOS 的 mDNSResponder。關閉它才能讓 BIND9 佔用 53。"
        if confirm "關閉 mDNSResponder 以釋放 port 53？（需 sudo 密碼）" Y; then
            log "執行：sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist"
            sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist 2>/dev/null \
                && ok "已嘗試關閉 mDNSResponder" \
                || warn "指令回報錯誤——新版 macOS 常如此，只要 53 已空即可（稍後驗證）。"
            hint "還原方式：把上面指令的 unload 換成 load。"
        else
            warn "未釋放 53，BIND9 可能無法啟動。"
        fi
    elif echo "$PORT53_USERS" | grep -qiE "com\.docke|docker|bind|named"; then
        ok "佔用者是 Docker / 既有的 re-ddns 堆疊——這是正常的。"
        hint "步驟 4 會先 docker compose down 再重新綁定 53，無需手動處理。"
    else
        hint "非 mDNSResponder。請自行停止上述程序，或讓本腳本繼續嘗試啟動。"
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 4/8 · build + 啟動整套 Docker 堆疊"
# ════════════════════════════════════════════════════════════════════════════

hint "使用 ${COMPOSE_FILE}（含 nginx + 三個 testapp + App Store），由 docker_restart.sh 編排。"
echo
warn "「完全清除」會移除所有 Docker volume（registry / 憑證 / nginx 設定 / DB），"
warn "得到最乾淨的環境，但會清掉先前註冊的 app 狀態（最穩定、建議用於修壞掉的環境）。"
hint "「保留資料」只重啟容器、保留 volume（較快，但殘留設定可能造成問題）。"
echo

RESTART_FLAG=""
if confirm "要完全清除 Docker 資料再重建嗎？（推薦：Y＝乾淨重來）" Y; then
    log "將執行：./docker_restart.sh（完全清除 volume）"
else
    RESTART_FLAG="--keep-volumes"
    log "將執行：./docker_restart.sh --keep-volumes（保留 volume）"
fi

log "啟動中…（第一次會編譯 Reflex，較慢屬正常）"
echo -e "${DIM}────────────────────────────────────────────────────────────${NC}"
# docker_restart.sh 結尾的 health-check 在主機 DNS 尚未設定時會「誤報」，
# 因此忽略其退出碼，改由本腳本用 --resolve 直接驗證後端。
./docker_restart.sh $RESTART_FLAG
RESTART_RC=$?
echo -e "${DIM}──────────────────────────────────────────────────────────────${NC}"
if [[ $RESTART_RC -ne 0 ]]; then
    warn "docker_restart.sh 回傳非 0（很可能是結尾 health-check 的『誤報』——"
    warn "它用網域名稱檢查，但此刻主機 DNS 還沒設定。下一步會用 --resolve 直接驗證後端。"
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 5/8 · 繞過 DNS，直接驗證 nginx 後端"
# ════════════════════════════════════════════════════════════════════════════

hint "用 curl --resolve 直接打 127.0.0.1，避開尚未設定的主機 DNS。"
echo
BACKEND_OK=false
for attempt in 1 2 3; do
    if verify_backend; then BACKEND_OK=true; break; fi
    if [[ $attempt -lt 3 ]]; then
        warn "尚未全部就緒，10 秒後重試（可能仍在編譯）… ($attempt/3)"
        sleep 10
    fi
done

if $BACKEND_OK; then
    ok "後端全部回 HTTPS 200——核心服務正常！"
else
    err "部分服務後端尚未回 200。可檢查日誌："
    hint "docker compose -f ${COMPOSE_FILE} logs --tail=80 re-ddns"
    hint "docker logs test-app   /   docker logs app-store"
    if ! confirm "仍要繼續設定 DNS / CA 嗎？" N; then
        err "已停在驗證階段。排除後端問題後可重跑本腳本。"
        exit 1
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 6/8 · 把 Mac 的 DNS 指向本機 BIND9"
# ════════════════════════════════════════════════════════════════════════════

if [[ "$OS" != "Darwin" ]]; then
    warn "非 macOS，略過 DNS 設定。請自行讓 *.reflex-ddns.com 解析到本機 BIND9。"
else
    DNS_ALREADY=false
    if verify_host_dns >/dev/null 2>&1; then DNS_ALREADY=true; fi

    if $DNS_ALREADY; then
        ok "主機已能解析 *.reflex-ddns.com（先前設定過）。"
        confirm "要重新執行 ./macos_set_dns.sh --join 嗎？" N && DO_JOIN=true || DO_JOIN=false
    else
        hint "將執行：./macos_set_dns.sh --join --iface \"$IFACE\""
        hint "它會要求 sudo（Mac 登入）密碼——請直接在終端機輸入。"
        hint "有線網路請用 --iface Ethernet（目前：${IFACE}）。"
        confirm "現在把 DNS 指向本機 BIND9？" Y && DO_JOIN=true || DO_JOIN=false
    fi

    if ${DO_JOIN:-false}; then
        echo -e "${DIM}──────────────────────────────────────────────────────────────${NC}"
        ./macos_set_dns.sh --join --iface "$IFACE"
        JOIN_RC=$?
        echo -e "${DIM}──────────────────────────────────────────────────────────────${NC}"
        [[ $JOIN_RC -eq 0 ]] && ok "DNS 設定完成" || warn "macos_set_dns.sh 回傳非 0，請看上方訊息。"
        log "驗證主機端解析："
        verify_host_dns || warn "仍有網域無法解析；可 ./macos_set_dns.sh --list 檢查，或確認 --iface 正確。"
    elif $DNS_ALREADY; then
        ok "保持現有 DNS 設定（已可解析 *.reflex-ddns.com）。"
    else
        warn "略過 DNS 設定——瀏覽器將無法用網域開啟（會顯示無法解析主機）。"
    fi
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 7/8 · 安裝 Local CA 憑證（讓 HTTPS 受信任）"
# ════════════════════════════════════════════════════════════════════════════

# 先看是否已受信任（不加 -k 也能通過）
CA_TRUSTED=false
if curl -s -o /dev/null --max-time 6 https://home.reflex-ddns.com/ 2>/dev/null; then
    CA_TRUSTED=true
fi

if $CA_TRUSTED; then
    ok "Local CA 似乎已受信任（https://home.reflex-ddns.com 無憑證錯誤）。"
    confirm "要重新安裝 CA 嗎？" N && DO_CA=true || DO_CA=false
else
    # 確認 HTTP 端可達（DNS 通了才行）
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 http://home.reflex-ddns.com/api/ca.pem 2>/dev/null || echo "000")
    if [[ "$HTTP_CODE" == "000" ]]; then
        warn "目前連 http://home.reflex-ddns.com 都不通——多半是上一步 DNS 還沒設好。"
        hint "可改用繞過 DNS 的方式安裝（用 --resolve 取得 CA），或先把 DNS 設好。"
        confirm "用繞過 DNS 的方式安裝 CA？" Y && DO_CA=resolve || DO_CA=false
    else
        hint "將執行：curl -fL http://home.reflex-ddns.com/api/ca/install-script/macos | bash"
        hint "安裝過程可能要求 sudo / 鑰匙圈密碼——請直接在終端機輸入。"
        confirm "現在安裝 Local CA 憑證？" Y && DO_CA=true || DO_CA=false
    fi
fi

case "${DO_CA:-false}" in
    true)
        echo -e "${DIM}──────────────────────────────────────────────────────────────${NC}"
        curl -fL http://home.reflex-ddns.com/api/ca/install-script/macos | bash
        CA_RC=$?
        echo -e "${DIM}──────────────────────────────────────────────────────────────${NC}"
        [[ $CA_RC -eq 0 ]] && ok "CA 安裝指令執行完成" || warn "CA 安裝指令回傳非 0，請看上方訊息。"
        ;;
    resolve)
        # 繞過 DNS：先抓 CA，再用 macOS security 加入系統信任
        TMP_CA="$(mktemp -t reflex-ca)"
        if curl -sk --resolve home.reflex-ddns.com:443:127.0.0.1 \
                -o "$TMP_CA" https://home.reflex-ddns.com/api/ca.pem 2>/dev/null \
           || curl -s --resolve home.reflex-ddns.com:80:127.0.0.1 \
                -o "$TMP_CA" http://home.reflex-ddns.com/api/ca.pem 2>/dev/null; then
            if [[ -s "$TMP_CA" ]]; then
                log "已取得 CA 憑證：$TMP_CA"
                log "加入系統鑰匙圈並設為信任（需 sudo / 鑰匙圈密碼）："
                sudo security add-trusted-cert -d -r trustRoot \
                    -k /Library/Keychains/System.keychain "$TMP_CA" \
                    && ok "CA 已加入系統信任" \
                    || warn "加入信任失敗，請手動把 $TMP_CA 匯入『系統』鑰匙圈並設為永遠信任。"
            else
                warn "下載到的 CA 檔為空，請改用 UI 手動安裝。"
            fi
        else
            warn "無法取得 CA 憑證，請確認 re-ddns 容器運作正常。"
        fi
        ;;
    *)
        if $CA_TRUSTED; then
            ok "保持現有 CA 設定（已受信任）。"
        else
            warn "略過 CA 安裝——瀏覽器會顯示『您的連線不是私人連線』。"
        fi
        ;;
esac

if [[ "${DO_CA:-false}" != "false" ]]; then
    warn "請『完全關閉再重開瀏覽器』，讓它重新讀取信任憑證。"
fi

# ════════════════════════════════════════════════════════════════════════════
step "步驟 8/8 · 最終驗收"
# ════════════════════════════════════════════════════════════════════════════

log "後端（繞過 DNS）："
verify_backend || true

if [[ "$OS" == "Darwin" ]]; then
    echo
    log "主機端 DNS 解析："
    verify_host_dns || true

    echo
    log "CA 信任驗證（不加 -k）："
    code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 6 https://home.reflex-ddns.com/ 2>/dev/null || echo "000")
    if [[ "$code" == "200" ]]; then
        ok "https://home.reflex-ddns.com → ${code}（CA 已受信任）"
    else
        warn "https://home.reflex-ddns.com → ${code}（若非 200：CA 未信任或需重開瀏覽器/設定 DNS）"
    fi
fi

cat <<EOF

$(echo -e "${BOLD}${GREEN}完成！可在瀏覽器開啟（綠色鎖頭、無警告）：${NC}")

  https://home.reflex-ddns.com       Re-DDNS 控制台
  https://testapp.reflex-ddns.com    testapp
  https://testapp2.reflex-ddns.com   testapp2（另有 http://localhost:6080/vnc.html）
  https://testapp3.reflex-ddns.com   testapp3
  https://aapps.reflex-ddns.com      App Store（瀏覽 / 安裝 / 啟停管理各 app）

$(echo -e "${DIM}日常：")
  重啟（保留資料）  ./docker_restart.sh --keep-volumes
  乾淨重來          ./docker_restart.sh
  看日誌            docker compose -f ${COMPOSE_FILE} logs -f re-ddns
  還原 Mac DNS      ./macos_set_dns.sh --leave
$(echo -e "${NC}")
EOF

ok "rerun_from_zero.sh 全部完成。"
