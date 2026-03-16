# Smart Launcher – 一鍵部署任意 Reflex App

Smart Launcher 是一個通用 Docker 容器，能自動從 GitHub 下載任何 Reflex 應用程式的原始碼，
並透過 re-ddns 自動設定 DNS、TLS 憑證和 nginx 反向代理，讓原本只能在 `localhost:3000/8000`
執行的應用程式，可以用自訂域名（如 `https://myapp.reflex-ddns.com`）來存取。

## 運作原理

```
┌──────────────────────────────────────────────────────────┐
│  Smart Launcher Container                                │
│                                                          │
│  1. git clone <your-repo>     ← 從 GitHub 下載原始碼     │
│  2. poetry install            ← 安裝 Python 依賴         │
│  3. reflex init               ← 初始化 Reflex            │
│  4. register_dns.py           ← 向 re-ddns 註冊 DNS      │
│  5. reflex run :3000/:8000    ← 啟動 Reflex 服務         │
│                                                          │
└──────────────┬───────────────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────┐
│  re-ddns Container                                       │
│                                                          │
│  • BIND9: myapp.reflex-ddns.com → 172.28.0.10           │
│  • nginx: Host header routing → smart-app:3000/8000     │
│  • TLS:   自動產生 local CA 憑證                          │
│                                                          │
└──────────────────────────────────────────────────────────┘
               │
               ▼
         瀏覽器存取
    https://myapp.reflex-ddns.com
```

## 快速開始

### 1. 啟動服務

```bash
docker compose -f docker-compose.smart-launcher.yml up --build
```

### 2. 設定 DNS（macOS）

```bash
# 將 DNS 指向本地 BIND9
sudo bash macos_set_dns.sh
```

### 3. 存取應用

- **re-ddns 管理介面**: https://home.reflex-ddns.com
- **你的應用程式**: https://chat.reflex-ddns.com（以範例 reflex-chat 為例）

## 環境變數

### 必填

| 變數 | 說明 | 範例 |
|------|------|------|
| `GITHUB_REPO` | GitHub 倉庫 clone URL | `https://github.com/reflex-dev/reflex-chat.git` |
| `APP_NAME` | Reflex app 模組名稱（含 `__init__.py` 的資料夾） | `reflex_chat` |

### 選填

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `GITHUB_BRANCH` | `main` | 要 clone 的分支或 tag |
| `GITHUB_SUBDIR` | _(空)_ | 如果 Reflex 專案在 monorepo 的子目錄中 |
| `SERVICE_SUBDOMAIN` | `$APP_NAME` | DNS 子域名 |
| `SERVICE_ZONE` | `reflex-ddns.com` | DNS 區域 |
| `FRONTEND_PORT` | `3000` | Reflex 前端埠號 |
| `BACKEND_PORT` | `8000` | Reflex 後端埠號 |
| `RE_DDNS_API_URL` | `http://re-ddns:8000` | re-ddns API 位址 |
| `EXTRA_PIP_PACKAGES` | _(空)_ | 額外安裝的 pip 套件（空格分隔） |
| `EXTRA_APT_PACKAGES` | _(空)_ | 額外安裝的 apt 套件（空格分隔） |
| `SKIP_DNS_REGISTER` | `0` | 設為 `1` 跳過 DNS 註冊 |

## 部署多個應用

在 `docker-compose.smart-launcher.yml` 中複製 `smart-app` 服務區塊，
修改環境變數和 IP 即可：

```yaml
  smart-app2:
    build:
      context: ./smart_launcher
      dockerfile: Dockerfile
    container_name: smart-app2
    hostname: smart-app2
    networks:
      ddns-net:
        ipv4_address: 172.28.0.51
    depends_on:
      - re-ddns
    environment:
      - GITHUB_REPO=https://github.com/user/another-app.git
      - APP_NAME=another_app
      - SERVICE_SUBDOMAIN=another
      - SERVICE_ZONE=reflex-ddns.com
      - RE_DDNS_API_URL=http://re-ddns:8000
      - REFLEX_FRONTEND_HOST=0.0.0.0
      - REFLEX_BACKEND_HOST=0.0.0.0
    restart: unless-stopped
```

## 適用場景

- **展示 Demo**: 快速將 GitHub 上的 Reflex 範例部署到有域名的環境
- **開發測試**: 在 Docker 中測試應用程式是否能正確在反向代理後運作
- **團隊協作**: 一個 `docker-compose.yml` 同時啟動多個 Reflex 微服務

## 注意事項

1. **原始碼不需修改**: 大部分 Reflex 應用程式可以直接使用，不需要修改程式碼。
   Smart Launcher 會自動處理 `rxconfig.py`、Vite 設定等。

2. **如果 repo 沒有 `pyproject.toml`**: Launcher 會自動建立一個，預設安裝
   `reflex 0.8.24.post1` 和 `httpx`。

3. **如果 repo 沒有 `rxconfig.py`**: Launcher 會根據 `APP_NAME` 自動建立一個。

4. **私有倉庫**: 目前只支援公開倉庫的 HTTPS clone。如需私有倉庫，可以掛載
   SSH key 或使用 GitHub personal access token：
   ```
   GITHUB_REPO=https://<token>@github.com/user/private-repo.git
   ```

## 與 testapp3 的關係

此設計學習自 `testapp3/` 的經驗驗證模式：
- 相同的 DNS 註冊機制（`register_dns.py`）
- 相同的 Dockerfile 基礎（Python 3.11 + Node.js + Poetry）
- 相同的 Vite allowedHosts 修補
- 相同的 entrypoint 啟動流程

差別在於 testapp3 是「靜態打包」原始碼，而 Smart Launcher 是「動態拉取」原始碼。
