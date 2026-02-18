[TOC]

# 初始建立
All files created. Here's a summary of the complete Docker setup:

---

### Docker 相關檔案一覽

| File | Purpose |
| --- | --- |
| [ Dockerfile](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | Python 3.11 + BIND9 + Node.js，安裝 Poetry 依賴後啟動兩個服務 |
| [ docker-compose.yml](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | 埠映射 (53, 3000, 8000)，Volume 掛載源碼實現 live-reload |
| [ named.conf](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | BIND9 主設定：authoritative-only, logging |
| [ named.conf.local](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | TSIG key 定義 + zone 宣告 (允許動態更新) |
| [ rndc.conf](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | rndc 管理工具設定 |
| [ db.example.com](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | 範例 zone 檔，含  `home`  A record |
| [ entrypoint.sh](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | 啟動 BIND9 → 啟動 Reflex dev server → 優雅關閉 |
| [ generate\_tsig\_key.sh](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | 一鍵產生 TSIG secret 並自動寫入設定檔 |
| [ .dockerignore](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html) | 排除不需要的檔案，加速 build |

### 運作方式

1.  **單一容器**同時跑 BIND9 (DNS) 和 Reflex App (Web UI)
2.  **Volume 掛載**  [ re\_ddns](vscode-file://vscode-app/Applications/Visual%20Studio%20Code.app/Contents/Resources/app/out/vs/code/electron-browser/workbench/workbench.html)  原始碼 → 你在 Mac 上改 Python 程式碼，容器內的 Reflex dev server 自動偵測並重新載入，**不需要重新 build image**
3.  **Port 53**  從容器拉出到 Mac → Mac 變成一台 DDNS 伺服器
4.  **Port 3000**  → 打開瀏覽器  `http://localhost:3000`  操作 Reflex App 控制 BIND9
5.  Reflex App 透過 RFC 2136 (dnspython) 向容器內的  `127.0.0.1:53`  發送動態 DNS 更新

## 快速使用

### 快速使用1
```bash
# 1. 產生 TSIG key（只需一次）
./docker/generate_tsig_key.sh

# 2. 如果 macOS 的 port 53 被佔用
sudo lsof -i :53  # 檢查
sudo launchctl unload -w /System/Library/LaunchDaemons/com.apple.mDNSResponder.plist

# 3. Build & 啟動
docker compose up --build

# 4. 瀏覽器開啟 http://localhost:3000
# 5. 在設定表單填入 Server IP=127.0.0.1, Key Name=ddns-key, Key Secret=<產生的 secret>

# 驗證 DNS
dig @127.0.0.1 home.example.com A
```

### 快速使用2
Port 53 is already free (the  `lsof`  returned nothing), so there's no conflict. The  `launchctl unload`  error is expected — on modern macOS (Ventura+),  `mDNSResponder`  is managed differently and may already not be listening on port 53, which is exactly what the empty  `lsof`  result confirms.

You're good to proceed:
```bash 
# 1. Generate the TSIG key (one-time)
./docker/generate_tsig_key.sh

# 2. Build & start
docker compose up --build
```

No need to worry about the  `launchctl`  error — port 53 is available.



# 初始啟動測試
## 測試方法

初始啟動，進入專案資料夾 re_ddns 可以作以下測試


```bash=1 
dig @127.0.0.1 home.example.com A
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 home.example.com A
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 24711
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;home.example.com.              IN      A

;; ANSWER SECTION:
home.example.com.       300     IN      A       127.0.0.1

;; Query time: 5 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:49:54 CST 2026
;; MSG SIZE  rcvd: 61
```

```bash=2
dig @127.0.0.1 home.example.com A +short
```
```
127.0.0.1
```

```bash=3
dig @127.0.0.1 example.com SOA
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com SOA
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 38322
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      SOA

;; ANSWER SECTION:
example.com.            300     IN      SOA     ns1.example.com. admin.example.com. 2025010101 3600 900 604800 300

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:50:13 CST 2026
;; MSG SIZE  rcvd: 86
```



```bash=4
dig @127.0.0.1 example.com NS
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com NS
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 34433
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 2
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      NS

;; ANSWER SECTION:
example.com.            300     IN      NS      ns1.example.com.

;; ADDITIONAL SECTION:
ns1.example.com.        300     IN      A       127.0.0.1

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:50:20 CST 2026
;; MSG SIZE  rcvd: 74
```

```bash=5
dig @127.0.0.1 home.example.com A +noall +answer +authority
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 home.example.com A +noall +answer +authority
; (1 server found)
;; global options: +cmd
home.example.com.       300     IN      A       127.0.0.1
```

```bash=6
dig @127.0.0.1 example.com ANY
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 example.com ANY
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 7064
;; flags: qr aa rd; QUERY: 1, ANSWER: 2, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;example.com.                   IN      ANY

;; ANSWER SECTION:
example.com.            300     IN      SOA     ns1.example.com. admin.example.com. 2025010101 3600 900 604800 300
example.com.            300     IN      NS      ns1.example.com.

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:51:12 CST 2026
;; MSG SIZE  rcvd: 100
```

```bash=7
dig @127.0.0.1 version.bind TXT CHAOS
```
```
; <<>> DiG 9.10.6 <<>> @127.0.0.1 version.bind TXT CHAOS
; (1 server found)
;; global options: +cmd
;; Got answer:
;; ->>HEADER<<- opcode: QUERY, status: NOERROR, id: 26953
;; flags: qr aa rd; QUERY: 1, ANSWER: 1, AUTHORITY: 0, ADDITIONAL: 1
;; WARNING: recursion requested but not available

;; OPT PSEUDOSECTION:
; EDNS: version: 0, flags:; udp: 1232
;; QUESTION SECTION:
;version.bind.                  CH      TXT

;; ANSWER SECTION:
version.bind.           0       CH      TXT     "not disclosed"

;; Query time: 1 msec
;; SERVER: 127.0.0.1#53(127.0.0.1)
;; WHEN: Thu Feb 19 06:51:19 CST 2026
;; MSG SIZE  rcvd: 67
```




## 測試結果分析


全部正常，所有測試都通過了：

| 項次 | 測試  | 結果  | 說明  |
| --- | --- | --- | --- |
| 01 | `home.example.com A` | `127.0.0.1` | 動態記錄存在，TTL 300 正確 |
| 02 | `example.com SOA` | `ns1.example.com. admin.example.com.` | Zone 權威資訊正確 |
| 03 | `example.com NS` | `ns1.example.com.`  \+ glue record | NS 及其 A 記錄都正確回傳 |
| 04 | `example.com ANY` | SOA + NS 共 2 筆 | Zone 完整 |
| 05 | `version.bind TXT CHAOS` | `"not disclosed"` | 版本隱藏生效，安全性 OK |
| 06 | `flags: qr aa rd` | `aa`  (authoritative answer) | BIND9 作為權威伺服器正確運作 |
| 07 | `recursion requested but not available` | 預期行為 | 我們設定了  `recursion no`，正確 |



# 動態操作指引-測試方法

動態 DNS 更新 — 完整操作指引
------------------

### Step 1：開啟 Reflex UI

瀏覽器打開  **[http://localhost:3000](http://localhost:3000)**

### Step 2：填寫設定表單

在 Configuration 頁面，填入以下值：

| 欄位  | 填入值 | 說明  |
| --- | --- | --- |
| **Primary Nameserver** | `127.0.0.1` | BIND9 在容器內，Reflex 也在同一容器，所以是 localhost |
| **DNS Zone** | `example.com` | 對應 BIND9 設定的 zone 名稱 |
| **Record Hostname** | `home` | 要動態更新的子域名（即  `home.example.com`） |
| **Record Type** | `A (IPv4)` | 下拉選 A |
| **TTL (Seconds)** | `300` | 預設即可 |
| **TSIG Key Name** | `ddns-key` | 對應 BIND9 設定的 key 名稱 |
| **TSIG Key Secret** | `yfy0mnBZvA1pXv/hqJxNefx6R6RwZG7jXLYT6YcAM2g=` | generate\_tsig\_key.sh 產生的密鑰 |

填完後點  **Save**  按鈕。

### Step 3：偵測 IP 並觸發 DNS 更新

1.  在 Dashboard 頁面，點  **Check Now**  — 這會去  `api64.ipify.org`  偵測你的外部 IP
2.  偵測成功後，點  **Update DNS**  — 這會透過 RFC 2136 發送動態更新到 BIND9

### Step 4：用 dig 驗證更新結果
```bash 
# 查詢更新後的記錄（應該會從 127.0.0.1 變成你的外部 IP）
dig @127.0.0.1 home.example.com A +short

# 完整輸出版本
dig @127.0.0.1 home.example.com A

# 查看 SOA serial 是否遞增（每次動態更新 BIND9 會自動遞增）
dig @127.0.0.1 example.com SOA +short
```

### 預期結果

**更新前：**

```bash
$ dig @127.0.0.1 home.example.com A +short
127.0.0.1
```

**更新後：**

```bash 
$ dig @127.0.0.1 home.example.com A +short
<你的外部 IP, 例如 203.0.113.42>
```
### 除錯指令

如果更新失敗，可以檢查：

```bash 
# 查看 BIND9 的動態更新 log
docker exec re-ddns cat /var/log/bind/update.log

# 查看 BIND9 主 log
docker exec re-ddns cat /var/log/bind/named.log

# 查看整體容器 log
docker compose logs --tail=30

# 手動用 nsupdate 測試（在容器內）
docker exec -it re-ddns bash -c '
nsupdate -y hmac-sha256:ddns-key:yfy0mnBZvA1pXv/hqJxNefx6R6RwZG7jXLYT6YcAM2g= <<EOF
server 127.0.0.1
zone example.com
update delete test.example.com A
update add test.example.com 300 A 1.2.3.4
send
EOF
'

# 驗證手動更新
dig @127.0.0.1 test.example.com A +short
# 預期輸出: 1.2.3.4

```