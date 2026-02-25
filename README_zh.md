[English](README.md)

# Lark 連結預覽與圖片存檔機器人

一個基於 Lark Base（多維表格）的整合機器人，透過 Webhook 監聽群組訊息。收到文字訊息時，自動擷取網址、抓取網頁 metadata，並以互動卡片回覆預覽結果。收到圖片訊息（行內圖片或檔案附件）時，自動下載圖片、上傳至雲端硬碟、開啟連結分享權限，並以確認卡片回覆。所有紀錄皆自動寫入多維表格。

## 功能特色

- **連結預覽**：從文字訊息中擷取網址，抓取網頁 metadata（`og:title`、`og:description`、`<title>`、`<meta description>`、`<p>`），以互動卡片回覆預覽結果。Facebook 網址有特殊處理（詳見下方[處理 Facebook 連結](#處理-facebook-連結)）。
- **圖片存檔**：下載聊天中發送的圖片（行內圖片及圖片檔案附件），上傳至指定的雲端硬碟資料夾，啟用連結分享，並以「圖片已儲存」確認卡片回覆。
- **檔案處理**：處理副檔名為圖片格式的檔案附件（png/jpg/jpeg/gif/bmp/webp/tiff/heic），流程與圖片存檔相同；非圖片檔案則略過。
- **多維表格整合**：自動將所有紀錄（連結預覽及圖片上傳）寫入指定的多維表格。

## 前置需求

1. 擁有 Lark 開發者帳號，並在 [Lark 開發者後台](https://open.larksuite.com/) 建立應用程式。
2. 啟用以下權限：
   - `im:message` — 接收訊息
   - `im:resource` — 下載訊息中的圖片/檔案
   - `drive:file:write` — 上傳檔案至雲端硬碟
   - `drive:file:permission:write` — 設定檔案分享權限
   - `bitable:app` — 讀取及編輯多維表格
3. 啟用事件訂閱：
   - 監聽 `im.message.receive_v1` 事件。
4. 已安裝 Python 3.10+。

## 安裝步驟

1. **進入專案目錄**：
   ```bash
   cd Lark_CrawlerBot
   ```

2. **安裝相依套件**：
   ```bash
   pip install -r requirements.txt
   ```

3. **環境變數設定**：
   將 `.env.example` 複製為 `.env`，並填入開發者後台的應用程式資訊：
   ```bash
   cp .env.example .env
   ```
   **必要 — Lark 應用程式憑證**
   *（開發者後台 → 你的應用程式 → 憑證與基本資訊）*
   - `APP_ID` — **App ID**，位於「憑證與基本資訊」頁面頂部。
   - `APP_SECRET` — **App Secret**，同一頁面，點選「顯示」後複製。

   **必要 — 事件訂閱安全設定**
   *（開發者後台 → 你的應用程式 → 事件訂閱）*
   - `ENCRYPT_KEY` — **Encrypt Key**，位於事件訂閱頁面的「加密策略」區塊。
   - `VERIFICATION_TOKEN` — **Verification Token**，位於同一頁面上方。

   **選填 — 多維表格** *（需要儲存紀錄時才設定）*
   - `BITABLE_APP_TOKEN` — 在瀏覽器中開啟多維表格文件，從網址列取得 `{app_token}` 部分：`https://xxx.feishu.cn/base/{app_token}`。
   - `BITABLE_TABLE_ID` — 同一頁面網址中的 `?table={table_id}` 部分；或在多維表格左側分頁名稱上按右鍵 → 複製連結取得。

   **選填 — 雲端硬碟** *（需要圖片存檔功能時才設定）*
   - `DRIVE_FOLDER_TOKEN` — 在雲端硬碟中開啟目標資料夾，從網址列取得 `{token}` 部分：`https://xxx.feishu.cn/drive/folder/{token}`。

   **選填 — Facebook Proxy** *（改善雲端伺服器上的 Facebook 網址 metadata 抓取）*
   - `FB_PROXY_URL` — Cloudflare Worker proxy 網址。先部署 `cf-worker/`，再將 Worker 網址填入此處（例如 `https://fb-meta-proxy.<subdomain>.workers.dev`）。
   - `FB_PROXY_KEY` — proxy 的 API key，須與 Worker 端設定的 `API_KEY` 一致；若未設定 key 則留空。

   **選填 — 伺服器**
   - `PORT` — Flask 伺服器端口，預設 `5000`，通常不需修改。

4. **多維表格設定**：
   確認目標多維表格包含以下欄位：
   - `Title`（類型：文字）
   - `Description`（類型：文字）
   - `URL`（類型：連結 或 文字）
   - `Timestamp`（類型：日期時間）
   - `Sender`（類型：人員）

## 啟動機器人

在本地啟動 Flask 伺服器：
```bash
python bot.py
```

*注意：* 若在本地測試 Lark Webhook，需使用 [ngrok](https://ngrok.com/) 或 Cloudflare Tunnels 等工具將本地伺服器暴露至公網：
```bash
ngrok http 5000
```
然後將 `https://<your-ngrok-url>.ngrok-free.app/webhook/event` 網址填入 Lark 應用程式的事件訂閱設定中。

## Docker 部署

使用 Docker Compose 建置並啟動：
```bash
docker compose up -d
```

或手動建置並執行：
```bash
docker build -t lark-crawlerbot .
docker run -d --env-file .env -p 5000:5000 lark-crawlerbot
```

容器使用 Gunicorn 作為生產級 WSGI 伺服器（2 個 worker、30 秒 timeout）。健康檢查端點為 `GET /`。

## 處理 Facebook 連結

Facebook 會封鎖大部分伺服器讀取頁面標題和描述。當你分享 Facebook 連結時，一般伺服器只會看到登入頁面，而非實際內容。Bot 透過依序嘗試四種方法來解決此問題，只要任一方法成功即停止：

```
偵測到 Facebook 網址
        |
        v
  1. Microlink.io API ---- 免費第三方服務（無需設定）
        |
      失敗？
        v
  2. 直接爬取 ------------- bot 偽裝為 Facebook 自身的爬蟲
        |
      失敗？
        v
  3. Cloudflare Worker --- 透過 Cloudflare 網路的 proxy（需選配部署）
        |
      失敗？
        v
  4. URL 解析 ------------- 從網址本身擷取名稱
                            例如 facebook.com/TeslaInsider → "TeslaInsider"
```

每一步 bot 都會檢查 Facebook 回傳的是真實內容還是通用的登入頁面。若結果看起來是制式內容，就會繼續嘗試下一個方法。

| 方法 | 運作方式 | 需要設定 | 限制 |
|------|---------|---------|------|
| Microlink.io | 第三方 API 代為抓取頁面 | 無（免費方案） | 每日 250 次、每秒 1 次 |
| 直接爬取 | 使用 Facebook 自身爬蟲的身份請求頁面 | 無 | 在雲端伺服器上經常被封鎖 |
| Cloudflare Worker | 部署在 Cloudflare 網路上的小型 proxy，其 IP 不被 Facebook 封鎖 | 部署 `cf-worker/`（見下方） | 每日 10 萬次（免費方案） |
| URL 解析 | 直接從網址結構讀取頁面名稱 | 無 | 無描述，僅能取得基本標題 |

> **一般使用者提示**：Bot 開箱即用（方法 1、2、4 無需任何設定）。僅當你的伺服器上 Facebook 預覽經常缺失時，才需要部署 Cloudflare Worker（方法 3）。

### Facebook 照片網址

Facebook 照片連結（`/photo/?fbid=XXX`）有特殊處理。由於 Facebook 封鎖大多數伺服器直接存取照片圖檔，Bot 會透過 Cloudflare Worker 的 lookaside 備援機制：

1. **Worker 偵測照片網址** — 從網址擷取 `fbid`，透過 Facebook 的 `lookaside.fbsbx.com/lookaside/crawler/media/?media_id={fbid}` endpoint 取得圖片。
2. **Worker 圖片代理** — Worker 上的 `?image_fbid={fbid}` endpoint 會將 lookaside 圖片以二進位格式代理回傳，讓 Bot 無需特殊 User-Agent 即可下載。
3. **Bot 下載並儲存** — 當 crawler.py 回傳照片網址的 `image_url` 時，Bot 會透過 Worker 代理下載圖片、上傳至雲端硬碟，並以「View Image」卡片回覆。

> **注意**：此功能需要部署 Cloudflare Worker（須設定 `FB_PROXY_URL`）。若未部署，照片網址僅會從 URL 結構擷取基本標題。

### 部署 Cloudflare Worker（選配）

```bash
# 1. 安裝相依套件
cd cf-worker && npm install

# 2. 登入 Cloudflare（首次使用會開啟瀏覽器授權）
npx wrangler login

# 3. 本地開發測試
npx wrangler dev
# 測試：curl 'http://localhost:8787/?url=https://www.facebook.com/share/p/1DWWsctUwX/'

# 4. 部署至 Cloudflare 邊緣網路
npx wrangler deploy
# 輸出範例：Published fb-meta-proxy (https://fb-meta-proxy.<your-subdomain>.workers.dev)

# 5.（選填）設定 API key 保護
npx wrangler secret put API_KEY
```

然後在 `.env` 加入：
```
FB_PROXY_URL=https://fb-meta-proxy.<your-subdomain>.workers.dev
FB_PROXY_KEY=your_secret_key
```

**Cloudflare Workers 免費方案額度**：每日 100,000 次請求、每次 10ms CPU、無需綁定信用卡。
