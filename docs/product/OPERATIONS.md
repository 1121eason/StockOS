# NVDA 背景研究與雲端部署

本階段運行行情、官方公告收集、財報解析待對帳及既有研究核對。AI、全新財報自動重估、未來目標價尚未啟用。啟動前準備可信研究 seed；空白 clone 不會補入示範資料。

## 本機

```sh
uv sync --locked
uv run python scripts/serve_ui.py --port 8511 --automation \
  --source-db /absolute/path/qve.db \
  --raw-dir /absolute/path/raw \
  --product-store data/nvda-product
```

開啟 `http://127.0.0.1:8511/nvda`。背景每 5 分鐘抓行情、每小時檢查官方來源、每 6 小時核對既有研究。瀏覽器每 15 秒更新狀態。手動按鈕只排入工作，不接受股票、資料庫路徑或財務模型參數。

產品狀態獨立保存於 `operations.sqlite` 與 `raw/`。程序鎖只允許一個 worker 使用同一儲存區；工作最多嘗試 3 次，重啟不歸零。不要在 NFS、多個副本或短暫容器檔案系統上共用此 SQLite。此版本使用單一持久主機；高可用與多節點需另外採用伺服器資料庫和分散式工作租約。

## 建置與 seed

```sh
docker build --platform linux/amd64 --tag stockos:review .
uv run python scripts/prepare_product_seed.py \
  --source-db /absolute/path/qve.db --raw-dir /absolute/path/raw \
  --out /absolute/path/new-private-seed
```

資料包包含現有研究 DB 的完整複本與兩季工作台實際引用的原件。DB 保留既有歷史 AI 紀錄；匯出不批准、重用或重新驗收這些紀錄。工具要求目標為新目錄，核對來源及複本，再原子完成資料包。`seed-manifest.json` 綁定 DB／raw hashes；啟動時再次檢查。這是私有部署資料，不是程式碼或容器映像檔。原始來源不寫入、不遷移，不複製本機登入檔或環境設定。只傳送至使用者指定的私有部署位置。

映像只包含程式與鎖定相依套件；建置 context 使用 `.dockerignore` 白名單。正式部署使用建置後的 image digest，記錄 CPU 架構及基礎映像 digest。沒有正式 push／部署程序或預設雲端專案。

## 雲端入口與持久保存

`deploy/compose.yaml` 是單一 Linux 主機的部署組合：

- `app`：非 root、唯讀程式檔案系統、無 host port、持久 `/state`、唯讀 `/seed`。
- `gateway`：Caddy HTTPS 與帳密驗證；只有 NVDA 頁面與必要 API 可達。移除傳往後端的 Authorization；保留來源檢查。示範試算與研究匯入端點不對外開放。
- `research` 儲存操作 DB 與原件；`tls` 保存 TLS 資料；更新映像不更換資料卷。不能以 `docker compose down -v` 當一般更新程序。
- 容器退出會重新啟動；健康檢查驗證 worker 心跳。**Docker 的 restart policy 不會單靠 unhealthy 狀態重啟容器**，平台健康監控與無回應處理須在選定平台後綁定、測試。
- 單機磁碟仍需外部備份。離機保存地點、保留期、磁碟告警及服務目標尚未設定，不能聲稱災難復原已完成。

先確定使用者指定的雲端專案、預算、域名與登入方式。若使用既有 Google／組織身分入口，可將 Caddy 帳密入口替換為受控認證代理；不得直接公開 app port。

在目標主機複製 `deploy/.env.example` 為未追蹤的 `.env`，填入已測 image digest、已核對 seed 目錄、專用網域與登入資料。Caddy 密碼雜湊以互動方式建立，不把密碼貼進文件、日誌或提交。`.env` 權限應限制於管理者。

```sh
docker compose --env-file deploy/.env -f deploy/compose.yaml config --quiet
docker compose --env-file deploy/.env -f deploy/compose.yaml up -d
```

第一次部署必須實測：未登入拒絕、登入後 NVDA 可用、跨來源更新拒絕、後端 port 不公開、背景工作完成、關閉本機後仍取得資料、主機重啟後研究保留。DNS、TLS 與實際雲端配置完成才算上線。

Cloud Run 的預設 request-based CPU 與短暫檔案系統不是本版本的持久單機運行契約；若採用 Cloud Run，需另接持久伺服器 DB、工作租約，並配置背景 CPU／排程。參考 [Cloud Run billing settings](https://docs.cloud.google.com/run/docs/configuring/billing-settings)、[runtime contract](https://docs.cloud.google.com/run/docs/container-contract)。

## 備份與還原

```sh
uv run python scripts/product_backup.py backup \
  --source /absolute/path/product-state --out /absolute/path/new-backup
uv run python scripts/product_backup.py restore \
  --source /absolute/path/new-backup --out /absolute/path/new-restored-state
```

備份使用 SQLite 一致快照，只收錄該快照引用的不可變原件。驗證 DB integrity、schema、artifact hashes、pointer 與 raw hashes。還原必須到新目錄，不覆蓋運行中的資料；先驗證再切換停機後的 volume。中斷工作將由取得 worker lock 的程序接續，嘗試次數保留。

此工具不自行上傳、刪除舊資料或建立備份排程。部署時須將通過驗證的備份保存至使用者指定的獨立位置，並實際測試從該位置還原。

## 可檢查的介面

| 介面 | 用途 |
|---|---|
| `GET /api/nvda` | 原子研究 snapshot、獨立報價、事件、提醒與狀態 |
| `POST /api/nvda/update` | 空 JSON，排入行情與既有研究核對 |
| `GET /api/operations/health` | worker、近期工作、錯誤及資格狀態 |
| `GET /api/operations/history` | 最近研究與來源版本，不含全部歷史分頁 |
| `GET /api/operations/artifact?id=…` | 依 immutable ID 讀取與核對單一紀錄 |

UI、job succeeded、研究發布、AI 語意驗收及通知送達是不同狀態。UI 顯示 Partial 並不表示故障，而是本階段仍有明確未完成的研究能力。

## 未啟用的 CI 範本

`deploy/ci/product-checks.example.yml` 提供合成測試、靜態檢查、容器建置與入口設定驗證；沒有位於 `.github/workflows/`，不會自動執行。現有 GitHub 憑證不含 workflow 修改權限；啟用時由具該權限的維護者將範本放入正式 workflow 目錄。CI 範本不部署或讀取私有 seed。
