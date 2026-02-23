[English](README.md)

# Lark 連結預覽與圖片存檔機器人

一個基於 Lark Base（多維表格）的整合機器人，透過 Webhook 監聽群組訊息。收到文字訊息時，自動擷取網址、抓取網頁 metadata，並以互動卡片回覆預覽結果。收到圖片訊息（行內圖片或檔案附件）時，自動下載圖片、上傳至雲端硬碟、開啟連結分享權限，並以確認卡片回覆。所有紀錄皆自動寫入多維表格。

## 功能特色

- **連結預覽**：從文字訊息中擷取網址，抓取網頁 metadata（`og:title`、`og:description`、`<title>`、`<meta description>`、`<p>`），以互動卡片回覆預覽結果。Facebook/Meta 網址透過 Microlink.io（免費方案：每日 250 次）抓取 metadata，自動偵測並過濾通用 boilerplate，若 API 失敗則 fallback 至 URL 結構解析。
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
