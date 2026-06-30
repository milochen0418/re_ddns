# RUN FROM ZERO — 從零到整套跑起來

本文件記錄「**從零 docker build 到 `https://home.reflex-ddns.com` 與三個 testapp 全部可用**」的完整、實測可行流程。

> 目標結果：在本機瀏覽器（綠色鎖頭、無憑證警告）開啟
> - `https://home.reflex-ddns.com` — Re-DDNS 控制台
> - `https://testapp.reflex-ddns.com` — testapp
> - `https://testapp2.reflex-ddns.com` — testapp2（含容器內瀏覽器，另有 `http://localhost:6080/vnc.html`）
> - `https://testapp3.reflex-ddns.com` — testapp3（前後端整合測試）

---

## 0. 架構速覽（為什麼需要這些步驟）

整套系統的核心是 **`re-ddns` 這一個容器**，同時跑三個服務：

```
┌─────────────── re-ddns 容器 ───────────────┐
│  BIND9   :53        → DNS（解析 *.reflex-ddns.com）│
│  nginx   :80/:443   → HTTPS 反向代理 + Local CA     │
│  Reflex  :3000/8000 → 控制台 UI（home 頁面本體）    │
└────────────────────────────────────────────┘
        ▲ testapp / testapp2 / testapp3 啟動時
        │ 自動呼叫 re-ddns API 註冊（DNS + 憑證 + nginx）
```

關鍵觀念：

1. **所有網域解析到同一個 IP**（`EXTERNAL_IP`，自動偵測為本機 LAN IP，偵測不到才退回 `127.0.0.1`），因為 HTTPS 一律在 `re-ddns` 的 nginx 終結。`home` / `testapp` / `testapp2` / `testapp3` 全部指到那裡。
2. 三個 testapp **不需手動設定**，啟動時會自動向 re-ddns 註冊自己（寫入 `registry.json` + 簽憑證 + 生成 nginx 設定 + 建 DNS A 記錄）。
3. 本機要看到頁面，需做三件「主機端」設定：**釋放 port 53 → 把 DNS 指向本機 BIND9 → 安裝 CA 憑證**。

> ⚠️ 用對 compose 檔：`docker-compose.yml` 只有單一容器、**沒有 nginx 也沒有 testapp**（只能 `http://localhost:3000`）。要「home + 3 testapp 走 HTTPS」必須用 **`docker-compose.test.yml`**，而 `docker_restart.sh` 就是用它編排的。

---

## 1. 前置需求

- 安裝並啟動 **Docker Desktop for Mac**。
- 終端機切到專案根目錄：

```bash
cd /Users/milochen/gits/re_ddns
```

確認 Docker daemon 已就緒：

```bash
docker info >/dev/null 2>&1 && echo "Docker OK" || open -a Docker
```

若 daemon 沒在跑，`open -a Docker` 會啟動 Docker Desktop，等約 20–30 秒再重試。

---

## 2. 釋放 macOS 的 port 53

BIND9 需要佔用 53 埠。先檢查：

```bash
sudo lsof -nP -i :53
```

- **沒有任何輸出** → 53 是空的，直接跳到步驟 3。
- 被 `mDNSResponder` 佔用 → 關閉它：

```bash
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist
```

> 還原方式：把 `unload` 換成 `load`。在新版 macOS 上，即使該指令報錯，只要 `lsof` 顯示 53 是空的就沒問題。

---

## 3. 一鍵 build + 啟動整套堆疊（含 3 個 testapp）

```bash
./docker_restart.sh
```

這支腳本會自動完成：

1. 用 `detect_external_ip.sh` 偵測本機 LAN IP，設成 `EXTERNAL_IP`（DNS A 記錄指向這裡）。
   - 只有一張網路介面 → 自動採用，不會詢問。
   - 有多個 IP → 會互動詢問請你選一個。
2. `docker compose -f docker-compose.test.yml down -v` 清掉舊容器與 volume（避免殘留 registry/nginx 設定）。
3. `up -d --build re-ddns`，等到 re-ddns API 回 200。
4. `up -d --build test-app test-app2 test-app3`，等到每個 app 就緒。

> 第一次會編譯 Reflex，較慢屬正常。

### ⚠️ 重要：腳本結尾的 health check「失敗」是誤報

腳本最後可能印出：

```
[restart] testapp did not become ready after 300s (internal=200, HTTPS=000000)
[restart]  3 app(s) failed health check!
```

這是 **誤報**，不代表後端有問題。原因：腳本的外部檢查用「網域名稱」去 `curl https://testapp.reflex-ddns.com`，但此時**主機 DNS 還沒設定（步驟 4 才做）**，所以本機無法解析網域 → `HTTPS=000`。注意 `internal=200` 代表容器內部其實正常。

用以下指令繞過 DNS、直接驗證 nginx 後端，確認其實一切正常：

```bash
for d in home testapp testapp2 testapp3; do
  code=$(curl -sk -o /dev/null -w "%{http_code}" \
    --resolve ${d}.reflex-ddns.com:443:127.0.0.1 \
    https://${d}.reflex-ddns.com/)
  echo "${d}.reflex-ddns.com -> HTTPS ${code}"
done
```

四個都應該回 `HTTPS 200`。再看註冊紀錄：

```bash
docker exec re-ddns cat /app/data/registry.json
```

應看到 testapp / testapp2 / testapp3 三筆，`ip_address` 為你的 `EXTERNAL_IP`。

確認 BIND9 解析正確：

```bash
for d in home testapp testapp2 testapp3; do
  echo -n "${d}.reflex-ddns.com -> "; dig @127.0.0.1 ${d}.reflex-ddns.com +short
done
```

---

## 4. 把 Mac 的 DNS 指向本機 BIND9

```bash
./macos_set_dns.sh --join
```

執行時會要求輸入 **sudo（Mac 登入）密碼**，請直接在終端機輸入。它會：

- 把 `127.0.0.1` 加到 Wi-Fi 的 DNS 清單最前面（保留原本 DHCP DNS 作後備）；
- 建立 `/etc/resolver/reflex-ddns.com` → 讓所有 `*.reflex-ddns.com` 查詢走本機 BIND9；
- 在 `/etc/hosts` 加上受管理項目；
- 清除 macOS DNS 快取。

> 有線網路請加 `--iface Ethernet`。隨時可 `./macos_set_dns.sh --list` 檢查、`--leave` 還原。

驗證主機端已可解析、且 HTTPS 可達：

```bash
for d in home testapp testapp2 testapp3; do
  echo -n "${d} -> "; dig ${d}.reflex-ddns.com +short
done

for d in home testapp testapp2 testapp3; do
  code=$(curl -sk -o /dev/null -w "%{http_code}" https://${d}.reflex-ddns.com/)
  echo "${d} -> ${code}"
done
```

兩段都應顯示你的 `EXTERNAL_IP` 與 `200`。

---

## 5. 安裝 Local CA 憑證（讓 HTTPS 被信任）

DNS 通了之後（HTTP port 80 已可連），一行指令下載並安裝 CA：

```bash
curl -fL http://home.reflex-ddns.com/api/ca/install-script/macos | bash
```

或開 `http://home.reflex-ddns.com`，在 UI 的 CA 引導頁點「Download CA Certificate」，手動安裝到「**系統**」鑰匙圈並設為「**永遠信任**」。

安裝後 **完全關閉再重開瀏覽器**，讓它重新讀取信任憑證。

驗證 CA 已受信任（不加 `-k` 也能通過憑證驗證）：

```bash
curl -s -o /dev/null -w "https verify -> %{http_code}\n" https://home.reflex-ddns.com/
```

回 `200` 即代表 CA 已信任。

---

## 6. 最終驗收

瀏覽器開啟（皆為綠色鎖頭、無警告）：

| 網址 | 內容 |
|------|------|
| `https://home.reflex-ddns.com` | Re-DDNS 控制台 |
| `https://testapp.reflex-ddns.com` | testapp Hello World |
| `https://testapp2.reflex-ddns.com` | testapp2（含容器內瀏覽器） |
| `https://testapp3.reflex-ddns.com` | testapp3（前後端整合測試） |
| `http://localhost:6080/vnc.html` | noVNC（看 testapp2 容器桌面） |

---

## 7. 日常使用

| 動作 | 指令 |
|------|------|
| 重啟整套（保留資料） | `./docker_restart.sh --keep-volumes` |
| 完全乾淨重來 | `./docker_restart.sh` |
| 改 `re_ddns/` 的 Python | 自動 reload，不用 rebuild（原始碼是 volume 掛載） |
| 改 `Dockerfile` / `pyproject.toml` / `docker/` | 需重跑 `./docker_restart.sh`（含 `--build`） |
| 看日誌 | `docker compose -f docker-compose.test.yml logs -f re-ddns` |
| 還原 Mac DNS | `./macos_set_dns.sh --leave` |

> DNS 與 CA 設定只需做一次。重開機後若 53 又被佔用，重做步驟 2 即可。

---

## 8. 疑難排解

| 症狀 | 原因 / 解法 |
|------|------|
| `docker_restart.sh` 結尾報「app(s) failed health check」 | **誤報**（見 §3）。用 `--resolve` 驗證後端；設好步驟 4 的 DNS 後瀏覽器即正常。 |
| `http://localhost:3000` 可以，但 `https://home...` 不行 | 你跑成 `docker-compose.yml`（無 nginx）。改用 `./docker_restart.sh`。 |
| 瀏覽器「無法解析主機」 | 沒做步驟 4。執行 `./macos_set_dns.sh --join`，再 `dig home.reflex-ddns.com +short` 確認。 |
| 「您的連線不是私人連線」 | 沒裝 CA（步驟 5），或裝完沒重啟瀏覽器。 |
| testapp 開不了、home 正常 | 看 `docker logs test-app` 找 `[register]` 是否成功；常見是 re-ddns 還沒 ready 它就註冊，重跑 `./docker_restart.sh` 會依序等待。 |
| 容器起不來 / port 53 衝突 | 回步驟 2 釋放 53；`docker logs re-ddns` 看 BIND9 設定檢查是否失敗。 |
| `docker info` 連不上 | Docker Desktop 沒啟動：`open -a Docker`，等就緒再重試。 |

---

## 附錄：實測環境快照

本文件依下列實測結果撰寫（單一網路介面，自動偵測 `EXTERNAL_IP`）：

- `EXTERNAL_IP` 自動偵測為本機 LAN IP（單一介面，無互動詢問）。
- BIND9（容器內 53）對四個網域皆解析到 `EXTERNAL_IP`。
- nginx 對 `home` / `testapp` / `testapp2` / `testapp3` 皆回 HTTPS `200`。
- `registry.json` 含 testapp / testapp2 / testapp3 三筆，IP 為 `EXTERNAL_IP`。
- `./macos_set_dns.sh --join` 後，主機 `dig` 可解析、`curl https://...` 回 `200`。
- `GET /api/ca/install-script/macos` 與 `GET /api/ca.pem` 皆回 `200`；CA 安裝後 `https` 不加 `-k` 即通過驗證。
