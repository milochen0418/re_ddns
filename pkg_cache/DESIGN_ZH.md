# pkg-cache 設計說明

English version: [DESIGN.md](DESIGN.md) · 怎麼啟動、怎麼確認它有在運作：[README.md](README.md)

## 一分鐘看懂

```
 app installs                         cache                                  internet
┌──────────────────────────┐         ┌────────────────────────────┐         ┌────────────────────────┐
│ smart-app-* containers   │  HTTP   │ pkg-cache  :3142           │  HTTPS  │ pypi.org               │
│                          │────────►│ same file before? → disk   │────────►│ registry.npmjs.org     │
│ apt, Poetry, pip, uv,    │         │ new file → download once   │  only   │ deb.debian.org         │
│ bun, Node.js, Playwright │         │ index → re-check (5 min)   │  when   │ nodejs.org, github.com │
└──────────────────────────┘         └──────────────┬─────────────┘  needed └────────────────────────┘
                                                    │ /data
                                     ┌──────────────▼─────────────┐
                                     │ pkg_cache/data/ on the Mac │
                                     │ (git-ignored)              │
                                     └────────────────────────────┘
```

圖說：app 安裝時的下載全部先經過 pkg-cache。下載過的檔案直接從 Mac 上的
`pkg_cache/data/` 給；只有沒下載過的檔案、或要確認索引有沒有更新時，才連到網路。

- **是什麼：** 一個 container `pkg-cache`，app 安裝時的下載都經過它。
- **規則：** 網址裡指名了確切版本的檔案（wheel、npm 的 `.tgz`、`.deb`、Node.js
  安裝檔）只下載一次，之後都從硬碟提供。不同版本的網址不同，所以一定重新下載。
- **索引保持最新：** 「有哪些版本」的清單（PyPI 頁面、npm 套件文件、apt 的
  `InRelease`）超過 5 分鐘就向上游重新確認，所以安裝選到的版本跟沒有快取時一樣。
- **檔案放在哪：** Mac 上的 `pkg_cache/data/`，已列入 `.gitignore`，不會被 commit。
- **可有可無：** 快取沒在跑時，app 照舊直接從網路下載。
- **效果：** 在全新的 container 重新安裝 ReflexGrid，從 333 秒、下載 168 MB，變成 83 秒、
  不必下載任何套件。

## 1. 為什麼需要

App Store 每次安裝都會開一個全新的 smart-launcher container，它的 entrypoint 會把所有相依
套件重新下載一遍：

| 下載內容 | 工具 | 大小（實測） |
|----------|------|--------------|
| apt 索引與套件（`ffmpeg`、Noto 字型…） | apt-get | 每次 `apt-get update` 約 9 MB 索引，另加套件本身 |
| Python wheel | Poetry、pip、uv | ReflexGrid 73 MB；執行中各 app 的 Poetry 快取各 125–180 MB |
| 前端套件 | bun（由 Reflex 執行） | ReflexGrid 的 tarball 38 MB；每個執行中的 app 解開後 180–375 MB |
| Node.js 22（Reflex 0.10 的 app） | launcher | 57 MB |
| Chromium（用 Playwright 的 app） | Playwright | 111 MB |

同樣的檔案會在不同 app 之間重複出現（每個 Reflex app 都要 Reflex、FastAPI、React、Vite、
Radix…），重新安裝時也會再出現一次（`docker_restart.sh` 會移除所有 smart-app container）。
用手機熱點（0.3–1 MB/s）時，每次安裝都要多花好幾分鐘。

**目標**

1. 每個確切的檔案只下載一次，之後從本機硬碟提供。
2. 絕不給出跟要求不同的版本。
3. 版本解析的結果跟沒有快取時完全一樣。
4. 以前下載過的東西，斷網時也能用。
5. app 不需要任何修改；快取是可選的，沒有它時照舊直接下載。
6. 輕量：Docker VM 的記憶體很緊，之前曾經耗盡過。

**不做的事：** 通用的網路 proxy；快取 app 執行時才下載的東西；私有套件或上傳發佈；自動清除
舊檔。

## 2. 組成

| 元件 | 位置 | 角色 |
|------|------|------|
| 快取伺服器 | [server.py](server.py)（單一檔案，aiohttp）、[Dockerfile](Dockerfile) | 把網址前綴對應到上游；保存檔案；重新確認索引 |
| 儲存空間 | host 上的 `pkg_cache/data/` = container 裡的 `/data` | 保存的檔案、索引、統計數字 |
| 用戶端設定 | [smart_launcher/entrypoint.sh](../smart_launcher/entrypoint.sh) 第 0.5 段 | 啟動時找到快取，把每個工具指向它 |
| 服務 | [docker-compose.test.yml](../docker-compose.test.yml) 的 `pkg-cache`；[docker_restart.sh](../docker_restart.sh) 步驟 2.6 | 在 `ddns-net` 與 `127.0.0.1:3142` 上執行 |

## 3. 核心規則：檔案與索引

套件管理工具的做法都是兩步：先讀**索引**選出版本，再下載那個版本的**檔案**。快取對兩者的
處理方式不同：

| | 檔案 | 索引 |
|-|------|------|
| 例子 | `six-1.17.0-py2.py3-none-any.whl`、`react-19.0.0.tgz`、`pool/…/jq_1.6-2.1+deb12u2_arm64.deb`、`dist/v22.23.3/node-v22.23.3-linux-arm64.tar.gz` | `/simple/six/`、npm 上 `react` 的套件文件、apt 的 `InRelease`、`latest-v22.x/SHASUMS256.txt` |
| 內容會變嗎？ | 不會：網址指名了一個版本 | 會：每次有新東西發佈就變 |
| 保存 | 永久保存，路徑跟上游相同 | 保存，連同 ETag、Last-Modified 與抓取時間 |
| 從硬碟提供 | 只要有，一律從硬碟 | 比 TTL 新的時候（300 秒；apt 每次都重新確認） |
| 否則 | 下載一次，邊下載邊傳給用戶端，然後保存 | 向上游發條件式請求：`304` → 沿用，`200` → 換成新的 |
| 上游連不到 | 用不到上游 | 送出最後一份副本（`STALE`） |

**為什麼保證「只給同一個版本」：** 快取的 key 就是檔案的網址，而版本是網址的一部分。只存了
`react-19.0.0.tgz` 時要 `react-19.1.0.tgz`，就是沒命中（miss），所以快取不可能給出別的版本。
要哪個版本則由用戶端（Poetry、uv、bun、apt）依據最多 5 分鐘前的索引決定——這比 PyPI 自己還
嚴格，PyPI 的索引頁標示的是 `Cache-Control: max-age=600`。

**檔案怎麼也經過快取：改寫網址。** 索引裡指向檔案的是完整網址
（`https://files.pythonhosted.org/packages/…`、`https://registry.npmjs.org/react/-/react-19.0.0.tgz`）。
快取送出 PyPI 或 npm 的索引時，會把這些前綴換成自己的位址，位址取自請求的 `Host` 標頭：
Docker 裡是 `http://pkg-cache:3142/pypi/files/…`，Mac 上是 `http://localhost:3142/…`。存下來的
副本保持上游的原始內容，改寫在每次回應時才做，所以一份副本可以服務所有用戶端。apt、
Node.js、Playwright 不需要改寫：它們用拿到的基底網址自己組出檔案網址。

## 4. 請求流程

**檔案**

```
GET /npm/react/-/react-19.0.0.tgz
 │
 ├─ data/files/npm/react/-/react-19.0.0.tgz 已存在？ ──是──► 從硬碟送出（HIT；支援 Range 與 HEAD）
 │
 ├─ 是 HEAD 請求？ ──是──► 轉送上游的標頭，什麼都不保存（PASS）
 │
 ├─ 這個檔案正在下載中？ ──是──► 加入那次下載，資料一到就傳出去（MISS）
 │
 └─ 在背景開始一次下載（MISS）
      上游 ──► data/tmp/<亂數> ──► 長度與雜湊值都正確？ ──► 移到 data/files/…
                 │（用戶端一邊讀這個檔案，一邊等它變大）
                 └─ 中斷或不正確：刪掉它，切斷用戶端的連線（用戶端會重試）
```

**索引**

```
GET /pypi/simple/six/              （Accept 標頭決定拿 JSON 還是 HTML 的副本）
 │
 ├─ 副本比 TTL 新？ ──是──► 改寫檔案網址後送出（HIT）
 │
 └─ 帶 If-None-Match / If-Modified-Since 問上游（同一個索引同時只問一次）
      ├─ 304 Not Modified ──► 標記為最新，送出副本（REVALIDATED）
      ├─ 200 ───────────────► 換成新的副本後送出（MISS）
      ├─ 404 之類 ──────────► 照轉上游的回答（例如沒有這個套件）
      └─ 逾時、5xx、斷網 ───► 送出最後一份副本（STALE；完全沒有副本時回 502）
```

括號裡是回應標頭 `X-Cache` 的值，用來看每個請求是怎麼被處理的。

## 5. 路由

| 路由（`http://pkg-cache:3142…`） | 上游 | 當成檔案保存 | 當成索引 | 使用者 |
|----------------------------------|------|--------------|----------|--------|
| `/pypi/files/…` | files.pythonhosted.org | 全部（wheel、sdist、`.metadata`） | — | Poetry、pip、uv |
| `/pypi/simple/<project>/`、`/pypi/pypi/<project>/json` | pypi.org | — | 全部；JSON 與 HTML 副本分開存 | Poetry、pip、uv |
| `/npm/<pkg>/-/<file>.tgz` | registry.npmjs.org | tarball | — | bun、npm |
| `/npm/<pkg>` | registry.npmjs.org | — | 套件文件；精簡版與完整版分開存 | bun、npm |
| `/apt/<host>/…` | `https://<host>/…`，只限白名單上的主機 | `pool/`、`by-hash/` | `dists/` 裡其餘的檔案 | apt-get、`playwright install-deps` |
| `/nodejs/…` | nodejs.org | `dist/v<x.y.z>/<file>` | `latest-*`、`index.json`、目錄列表 | launcher 下載 Node.js |
| `/github/<owner>/<repo>/releases/download/<tag>/<file>` | github.com（會跟隨轉址） | release 附件 | —（拒絕 `releases/latest`） | Reflex 的 bun 安裝程式、uv 下載的 Python |
| `/playwright/builds/…` | Playwright 的 CDN | 瀏覽器安裝檔 | — | `playwright install` |

其他請求——別的路徑、帶查詢字串的網址、GET 與 HEAD 以外的方法——一律回 `404` 或 `405`。
這個快取不是通用的 proxy。

## 6. 儲存結構

```
pkg_cache/data/                         （host）=  /data（container）
├─ files/<route>/<上游路徑>             保存的檔案，寫入後就不再變動，例如：
│    pypi/packages/b7/ce/149a…5e/six-1.17.0-py2.py3-none-any.whl
│    npm/react/-/react-19.0.0.tgz
│    apt/deb.debian.org/debian/pool/main/j/jq/jq_1.6-2.1+deb12u2_arm64.deb
│    nodejs/dist/v22.23.3/node-v22.23.3-linux-arm64.tar.gz
├─ meta/<route>/<路徑>/#<variant>       抓回來的索引，例如 meta/npm/react/#abbreviated
│                      #<variant>.json  它的網址、Content-Type、ETag、Last-Modified、抓取時間
├─ tmp/                                 下載中的檔案（啟動時清空）
└─ stats.json                           狀態頁上的統計數字
```

- 所有東西都先寫到 `tmp/`，再用原子性的 rename 移到正式位置，所以絕不會送出寫到一半的檔案。
- 路徑跟上游網址一致，可以直接瀏覽、手動清理。刪掉任何東西都安全：下次需要時會再下載。
- 這個資料夾在 macOS 上，檔案系統不分大小寫，但 npm 還有一些只差在大小寫的舊套件名稱
  （`JSONStream` 和 `jsonstream`）。所以 npm 的路徑會把大寫字母存成 `!` 加小寫
  （`!j!s!o!n!stream`），做法跟 Go 的 module cache 相同。
- 索引檔名是 `#<variant>`。快取不接受網址路徑裡有 `#`，所以這些檔名不會跟套件路徑衝突。

## 7. 並行與完整性

- **每個檔案只下載一次。** 檔案正在下載時，同一個檔案的其他請求會加入那次下載，從持續變大的
  暫存檔讀取。實測：3 個用戶端同時要同一個沒快取過的 2.1 MB wheel，只從上游下載一次，3 個
  用戶端都拿到完全相同且正確的檔案。
- **下載不會因用戶端離開而中斷。** 每次下載都是獨立的工作，就算發起下載的用戶端斷線，也會
  下載完並保存。
- **每個索引同時只確認一次。** 每個索引有自己的鎖，一大批請求湧入時不會對同一個索引同時發出
  多次確認。
- **保存前的檢查。** 位元組數必須等於 `Content-Length`。PyPI 的路徑
  （`packages/ab/cd/<60 個十六進位字元>/…`）就是檔案的 BLAKE2b-256，apt 的
  `by-hash/SHA256/<hex>` 路徑就是檔案的 SHA-256，兩者都會驗證。任何一項失敗就不保存，並切斷
  用戶端的連線，讓用戶端看到下載不完整而重試。
- **用戶端照樣會驗證。** pip、Poetry、uv 會核對索引或 lock 檔裡的 sha256；bun 會核對 npm 的
  `integrity`；apt 會核對簽章過的 `InRelease` 裡的雜湊值；launcher 會用 `SHASUMS256.txt` 核對
  Node.js。

## 8. App 怎麼使用快取

`smart_launcher/entrypoint.sh` 的第 0.5 段在每次 container 啟動時執行：

1. `PKG_CACHE_URL` 預設為 `http://pkg-cache:3142`；設成空字串就關閉快取。
2. 還原上一次啟動時改寫過的 apt 來源（原檔備份在 `/var/lib/smart-launcher/apt-sources-orig`）。
3. 試著連 `$PKG_CACHE_URL/_health`，最多 5 次、每次間隔 1 秒，因為 Docker 重啟後所有
   container 會同時啟動。
4. 快取有回應時，記錄 `Package cache: …`，然後設定每個工具：

| 工具 | 怎麼指向快取 |
|------|--------------|
| apt | 來源設定裡的 `deb.debian.org`、`security.debian.org`、`deb.nodesource.com` 網址改成 `$PKG_CACHE_URL/apt/<host>/`；原檔留給步驟 2 還原 |
| Poetry 1.8 | Poetry 只從 `pyproject.toml` 讀索引來源，不理會 `PIP_INDEX_URL`。所以在 `poetry lock` 之前，把 `[[tool.poetry.source]] name = "pkg-cache"`、`priority = "primary"` 加到 container 裡那份 `pyproject.toml` 的最後。設了 primary 來源就會取代預設的 PyPI：Poetry 不再連 pypi.org，lock 檔裡記錄的是 `reference = "pkg-cache"`（已驗證）。app 自己設了 primary 來源時就不加。 |
| pip | `PIP_INDEX_URL`，以及 `PIP_TRUSTED_HOST`（因為快取用的是一般 HTTP） |
| uv | `UV_DEFAULT_INDEX`、`UV_PYTHON_INSTALL_MIRROR`。如果 `uv.lock` 是對著 pypi.org 產生的，`uv sync` 會把 lock 改指向快取，並保留原本鎖定的版本（已驗證）。 |
| bun / npm | `NPM_CONFIG_REGISTRY`（Reflex 會把它寫進 `.web/bunfig.toml`），以及 `BUN_CONFIG_REGISTRY` |
| Node.js | `_fetch_node` 先讀 `latest-v22.x/SHASUMS256.txt`（索引），再從固定的 `v22.23.3/` 資料夾下載 tarball（檔案） |
| bun 本身 | `GITHUB`，也就是 Reflex 的 bun 安裝腳本下載時用的基底網址 |
| Playwright | `PLAYWRIGHT_DOWNLOAD_HOST` |

5. 快取沒有回應時，記錄 `Package cache not reachable`，然後直接下載，跟還沒有快取時完全一樣。

**開發模式不會弄髒你的 checkout。** 開發模式安裝會把 app 的 checkout 連結進 container，但
container 會改動的檔案都拿一份自己的副本（`pyproject.toml`、`poetry.lock`…）。快取開著時，
`reflex.lock/` 也會複製一份：bun 只有在用 npm 預設 registry 時，才不把 registry 寫進
`bun.lock`；經過快取時，它會在每一筆都寫上 `http://pkg-cache:3142/npm/…`。這樣的 lock 絕不能
進到 repo，因為在沒有快取的地方會安裝失敗。代價是：開發模式 container 裡對前端 lock 的變更
只留在 container 裡，跟 `poetry.lock` 原本的做法一樣。

container 會一直使用建立它時的 image，所以只有新建立的 container 才會用到新的 launcher
image：重建 `re-ddns/smart-launcher:latest` 之後，重新安裝 app 才會走快取。

## 9. 出錯時會怎樣

| 狀況 | 結果 |
|------|------|
| pkg-cache 沒在跑 | launcher 試了約 5 秒後直接下載 |
| app 安裝好之後 pkg-cache 停了 | 那個 app 下次啟動時會還原 apt 來源，並直接下載 |
| 斷網，檔案已保存 | 從硬碟提供 |
| 斷網，索引已保存 | 送出最後一份副本（`STALE`），裝過的版本照樣裝得起來 |
| 斷網，從沒下載過 | 回 `502`；安裝會失敗，跟沒有快取時一樣 |
| 下載中斷或檢查沒過 | 什麼都不保存，切斷用戶端連線，用戶端會重試 |
| 下載到一半時 pkg-cache 重啟 | 啟動時清空 `tmp/`；用戶端會重試 |
| 硬碟滿了 | 下載會像上面一樣失敗；請清出 `pkg_cache/data/` 的空間 |
| 保存的檔案竟然壞了 | 用戶端自己的雜湊檢查會擋下來；刪掉那個檔案，下次就會重新下載 |

## 10. 安全性

- **不是開放式 proxy。** 每個路由的上游都是固定的，`/apt/` 只能連白名單上的主機
  （`PKG_CACHE_APT_HOSTS`），而且只接受不帶查詢字串的 GET 與 HEAD。
- **不對區網開放。** 只有 Docker 網路和 Mac 上的 `127.0.0.1:3142` 連得到。
- **檢查路徑。** 網址路徑會先解碼再切成一段一段；`..`、空的片段、NUL、`\`、`#`，以及超過
  240 位元組的片段，在組出任何檔案路徑之前就會被拒絕。
- **只處理公開套件。** 不保存也不轉送任何帳號密碼。

## 11. 設計取捨

| 選擇 | 而不是 | 原因 |
|------|--------|------|
| 一個小伺服器（約 45 MB 記憶體） | devpi + Verdaccio + apt-cacher-ng + nginx | 一個 container 而不是四個，Docker VM 的記憶體之前就曾經耗盡；一個資料夾、一個狀態頁 |
| 一個伺服器 | 讓各 container 共用每個工具的快取資料夾 | Poetry 的快取不保證多個程序同時使用時安全，而 Docker 重啟後所有 app 會同時啟動；apt 與 bun 的快取格式各不相同；Node.js 和 Playwright 根本沒有可共用的快取 |
| 告訴每個工具快取的網址 | 透明的 HTTPS proxy | 不必在每個 container 安裝憑證授權中心（CA）；app 自己的網路流量完全不受影響 |
| 索引 5 分鐘後就重新確認 | 保存好幾個小時 | 安裝選到的版本跟沒有快取時一樣；需要速度時可以用 `PKG_CACHE_META_TTL` 調整 |

## 12. 設定與取捨

| 變數（pkg-cache container） | 預設值 | 效果 |
|-----------------------------|--------|------|
| `PKG_CACHE_META_TTL` | `300` | 索引在幾秒內不必問上游。調高會讓安裝更快，但這段時間內新發佈的版本不會被選到 |
| `PKG_CACHE_APT_HOSTS` | Debian、NodeSource、Ubuntu 的主機 | `/apt/` 可以連的主機 |
| `PKG_CACHE_PYPI_URL`、`PKG_CACHE_NPM_URL`… | 官方網站 | 上游位址，例如改用區域鏡像站 |

預設 300 秒的代價（實測）：第二次安裝 ReflexGrid 時，`poetry lock` 花了 45 秒。所有檔案都
來自硬碟，時間花在依序向 pypi.org 發出 54 次「這個索引有沒有更新？」的確認，在手機熱點上
每次約 1.5 秒。

## 13. 實測數據

2026-10-15，Mac 上的 Docker Desktop，透過 iPhone 熱點上網（0.3–1 MB/s）：

| 測試 | 結果 |
|------|------|
| 全新 container、空快取，安裝 ReflexGrid | 333 秒；下載 168 MB（PyPI 73 MB、npm 38 MB 共 288 個 tarball、Node.js 57 MB） |
| 同一個安裝，換一個全新 container | 83 秒；沒有下載任何套件；165 MB 從硬碟提供 |
| 全新 container 執行 `apt-get update` 並安裝 `jq` | 30 秒，第二次 2 秒 |
| 3 個請求同時要同一個沒快取過的 wheel | 只下載 1 次，3 份檔案完全相同且正確 |
| 快取完全沒有網路（`--network none`） | 索引 `STALE`、檔案 `HIT`；`pip download six` 成功 |
| uv 搭配對著 pypi.org 產生的 `uv.lock` | lock 改指向快取；six 維持鎖定的 1.16.0 |
| 快取伺服器的記憶體用量 | 約 43 MB |

## 14. 限制與後續

- **沒有快取的：** app 與 reflex_ddns_auth 的 `git clone`（很小，`--depth 1`）；各 image
  `docker build` 時的下載；app 執行時從固定網址下載的檔案（LiveKit app 的 `livekit-server`、
  Whisper 模型、Ollama 模型）。
- **不會自動清除：** 請在狀態頁留意大小，需要時刪掉 `data/files/` 底下的資料夾。
- **可以接著做的：** 透過 build 參數讓 image 建置也走快取；讓 LiveKit app 從環境變數讀下載的
  基底網址，這樣 `/github/` 就能提供 `livekit-server`；替 `git clone` 做一個鏡像。

## 15. 程式碼對照

| 位置 | 負責的事 |
|------|----------|
| `server.py` 的 `RESOLVERS`、`resolve_*()` | 網址 → 上游網址、檔案或索引、儲存位置、TTL、改寫規則、預期的雜湊值 |
| `split_tail()`、`_case_safe()` | 路徑檢查；npm 的大小寫轉換 |
| `serve_file()`、`download()`、`Fetch` | 檔案的 HIT 與 MISS、共用的單次下載、串流給加入的用戶端、檢查、原子性移動 |
| `serve_meta()`、`refresh_meta()` | 索引的 HIT、重新確認、替換與 STALE；改寫網址 |
| `passthrough()` | 還沒保存的檔案的 HEAD 請求 |
| `status_page()`、`status_json()`、`housekeeping()` | 狀態頁、`/_status`、每分鐘儲存並記錄統計數字 |
| `smart_launcher/entrypoint.sh` 第 0.5 段、`_pkg_cache_poetry_source`、`_fetch_node` | 用戶端：找到快取、設定各工具、Poetry 來源、下載 Node.js |
| `docker-compose.test.yml` 的 `pkg-cache` 服務、`docker_restart.sh` 步驟 2.6 | 執行這個服務 |
