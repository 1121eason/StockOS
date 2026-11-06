# M4.1 V6 六季執行報告

本輪 review：`data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/`。

最新核對：2026-09-27（Brisbane）。**六季批次已結束，FY2023-Q3 FAIL：CLI 明確回報用量上限。其餘五季未啟動，七季目前 1／7 PASS。** Q2 run 15／snapshot 4 保持 PASS；本次 run 16 未產生 snapshot。完整 SQLite 與 PostgreSQL 均已通過；不宣稱 M4.1 Final Pass。

範圍：延續 V6 Q2 run 15／snapshot 4，依序執行其餘六季，第一個 FAIL 或 unknown 即停止；診斷 Gemini 回歸，核對專用 PostgreSQL 測試環境。不代填真人判定，不 commit／push／部署。`sources/` 唯讀，既有修改與歷史 artifacts 保留。

## 執行前已完成

新增 `scripts/run_codex_validation_v6.py`，保留原 `PromptSetV6`、`AIAnalystPolicyV3`、`FeatureSchemaV2` 與 PIT transport／guard。舊 V5 cohort runner 仍讀固定 `experiment-v3.json` 且會重新 prepare 分析資料，不具備目前 Q2 runner 的完整收據及 context 綁定，因此本輪使用獨立 V6 入口。

新入口要求明確提供 pilot／isolation／kernel 收據與 input plan 的 bytes SHA-256；重讀 DB 驗證 Q2 確實通過。每季在推論前核對固定順序、來源／cutoff／package／完整 context 指紋、收據實際 bytes、當前 CLI／設定。分析使用同一份核准 context。每季保存獨立 context、preflight、preservation、result 收據，檢查新增 run、正式引用、敘述安全、呼叫生命週期與保護表；首個非 PASS 即停止。unknown 保留共用 lock。

先在隔離副本驗證，受影響測試 **138 passed**。封存 plan 的第一次執行發現唯讀 session 尚未關閉即 dispose engine 的問題；新增測試重現後修正，重做封存 exit 0。失敗 log 與第一次 plan 均保留，不覆寫。

候選 patch 經 `git apply --check` 通過後套用，僅新增 runner 與回歸測試，未修改既有產品程式。Ruff、mypy（71 source files）通過。

## Gemini 與完整 SQLite

最小 `sandbox-exec` 呼叫在受限外層回報 `sandbox_apply: Operation not permitted`，exit 71。正式受限環境全套為 **347 passed、2 Gemini failed、1 skipped**，exit 1。

透過正式主機執行權限，完全相同的 Gemini 假 CLI 測試 **9 passed**，exit 0；接著相同正式 checkout 的完整 SQLite **349 passed、1 PostgreSQL-only skipped、0 failed**，exit 0。這證實先前兩項失敗與外層沙箱無法啟動原生 sandbox 有關；未修改 Gemini 程式、測試、skip 或判定，也沒有呼叫真實 Gemini。

證據：`gemini-environment-diagnosis.json`、`gemini-host-tests.log`、`formal-sqlite-tests.log`、`formal-host-sqlite-tests.log`。

## 六季固定輸入

Plan：`cohort-plan-final.json`；SHA-256 `d1c4ef1f001bbb8b5cfc36d823d51cf62b35841d98a62423ec6e94622e331abb`。本輪不重新分析既有 Q2。每季完整 context／package 指紋保存在 plan 中。

| 順序 | 季度 | 資訊截止時間 UTC | Source IDs | Blocks | 狀態 |
|---|---|---|---|---:|---|
| 1 | FY2023-Q3 | 2022-11-17 14:30 | 10、11、106、107 | 615 | FAIL；用量上限，run 16 無 snapshot |
| 2 | FY2024-Q1 | 2023-05-25 13:30 | 12、13、104、105 | 990 | NOT_RUN |
| 3 | FY2024-Q2 | 2023-08-24 13:30 | 13、14、103、104 | 1,030 | NOT_RUN |
| 4 | FY2025-Q4 | 2025-02-27 14:30 | 19、20、96、97 | 1,007 | NOT_RUN |
| 5 | FY2026-Q1 | 2025-05-29 13:30 | 20、21、95、96 | 1,022 | NOT_RUN |
| 6 | FY2027-Q2 | 2026-08-27 13:30 | 25、26、90、91 | 648 | NOT_RUN |

六季 attempt `20260926T050302Z-7fd8997cdb80` 已於 2026-09-26T05:03:02Z 啟動，FY2023-Q3 preflight PASS，05:03:10Z 進入第一個 extract。啟動前完整程序名稱清單 686 列、0 解析錯誤；五個 Codex／code-mode PID 分別核明為三個 app-server 與兩個輔助程序，沒有相關 runner／模型呼叫。338 份歷史檔案、正式 DB bytes、原修改、CLI 設定與舊隔離收據均保全通過。表格將依實際收據更新，不以外層 exit 0 代替季度 gate。

## Q3 終止原因與獨立複核

2026-09-26T05:20:33.960743Z 與 05:20:36.900072Z，provider calls 173／174 的首個 CLI error 均為 `You've hit your usage limit`（原始字形為彎引號）。runner 隨後記錄 SIGKILL 要求與有界 wait 完成，child exit -9、`confirmed_stopped`。這次有明確的 CLI 失敗證據；不能僅看 -9 推論 OS 原因，也不倒填 9 月 25 日歷史 R03 的 unknown 原因。

Q3 共 12 calls，10 valid、2 failed；取得 307 筆證據，但 extract 未完成、沒有 features／challenges／snapshot。六季 runner 在第一個季度 FAIL 後於 05:20:46.393394Z 結束，outer exit 1，未啟動其餘五季，沒有外層自動重試。`active.lock` 已由確認停止的 attempt 正常解除。

2026-09-27 的唯讀獨立複核：**cohort gate FAIL，integrity gate PASS**。Q2 仍通過重算；338 份舊 artifacts、十張保護表、十二張 AI／建議表的既有 rows 未變；本次只新增 run 16、12 calls、307 evidence、4 events。無新增 snapshot。所有 launch references、順序、季度收據及核准 context 符合。

證據：[批次收據](/Users/eason/Documents/Coding/StockOS/data/m41/codex/attempts/20260926T050302Z-7fd8997cdb80/validation.json)、[失敗診斷](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/q3-failure-diagnosis.json)、[獨立複核](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/cohort-independent-review.json)。

目前 Codex app 帳戶查詢為一般使用可用、每週剩餘 98%；此為查詢當下快照，不能代替 runner 使用的 CLI 帳戶及 fresh preflight。沒有兌換 reset credit、購買額度或用此結果改寫失敗收據。[用量快照](/Users/eason/Documents/Coding/StockOS/data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/current-usage-snapshot.json)。

另以 `--prepare-plan` 唯讀重新驗證正式 Q2 與六季輸入，exit 0；`cohort-plan-after-quota.json` 的 SHA-256 仍是 `d1c4ef1f001bbb8b5cfc36d823d51cf62b35841d98a62423ec6e94622e331abb`，確認輸入未漂移。此模式不執行 CLI 或模型，沒有新增 attempt／run；日誌 `plan-after-quota-preparation.log`。下一次實際執行仍需 fresh 程序、CLI、帳戶可用性、設定與收據檢查；使用新 attempt 從 Q3 開始，不把 run 16 的部分結果當作新驗收或跳過 Q3。

## PostgreSQL 與後續

原本沒有設定 `QVE_TEST_POSTGRES_URL`。經正式主機權限取得 Docker，使用本機既有 PostgreSQL 16 image 建立本輪唯一容器 `stockos-v6-pg-32bd1394`，僅綁定 127.0.0.1、無主機目錄掛載。測試 core／labels database 均為新建，核對空庫後 migration；只經本輪 `QVE_TEST_POSTGRES_URL` 使用專用 core database。

首次完整 PostgreSQL：**347 passed、3 failed、0 skipped**，exit 1。三項皆為 `test_archived_nvda_visibility_and_historical_pe`，分別是 FY2022-Q1／FY2024-Q1／FY2027-Q2；空庫尚未安裝真實歷史 archive，`repo.quarter()` 回傳 None。其他 347 項含 migration 與獨立 schema 測試通過，public rows 未被測試修改，無殘留 pytest schema。初次 FAIL 收據與日誌保留。

補齊方式：59 份 manifest／離線來源先核對 bytes hash；從正式 SQLite 以 `mode=ro` 讀取既有 price bars，透過既有 ingestion／timestamp／split／price-basis 程式載入本輪專用 PostgreSQL。所有新 raw copies 保存於本輪 review，禁止 SourceClient 網路取得資料，不改正式 DB、產品程式或原測試斷言。補齊後的完整回歸結果另存新收據。

補齊後結果：**350 passed、0 failed、0 skipped，139.69 秒，exit 0**；驗收收據於 2026-09-26T15:45:14Z（Brisbane 2026-09-27 01:45）保存，gate PASS。載入 55 份 hash 驗證來源、713 筆 financial facts、1,682 筆價格、兩次拆股與 1,682 筆價格基準，測試原斷言保持不變。正式 DB bytes、59 份輸入、labels DB、測試前後 public rows 均相同，pytest schemas 無殘留。原始三項 FAIL 與新 PASS 收據分開保留。

專用容器 stop exit 0；第一次 inspect 尚見容器，初次清理收據 `removed=false` 保留。後續唯讀確認 inspect 回報 no such object、完整狀態的精確 ID 查詢 exit 0 且無匹配，確認已自動移除；最終收據 `postgres-cleanup-confirmed.json`。沒有操作其他容器。

完整 SQLite 與 PostgreSQL 測試缺口均已補齊。六季批次仍是 FAIL，七季 1／7、重跑 0／2、真人 0／35；測試通過不能替代模型季度驗收，M4.1 Final Pass 仍未達成。

## 本輪驗證命令與紀錄

工作目錄皆為 `/Users/eason/Documents/Coding/StockOS`；需要主機原生 sandbox 或 Docker 的命令使用工具正式 `require_escalated` 審核，內層 PIT 限制不變。

| 項目 | 命令／入口 | 收據或日誌 |
|---|---|---|
| Gemini 主機驗證 | `tests/unit/test_gemini_provider.py`（主機執行） | `gemini-host-tests.log`、`gemini-environment-diagnosis.json` |
| 完整 SQLite | 清除 `QVE_TEST_POSTGRES_URL` 後 `.venv/bin/python -m pytest -q -ra` | `formal-host-sqlite-tests.log` |
| 靜態檢查 | `.venv/bin/ruff check src tests scripts`；`.venv/bin/mypy src`；`git diff --check` | `formal-ruff.log`、`formal-mypy.log`、`final-diff-check.log` |
| 六季執行 | `scripts/run_codex_validation_v6.py --plan … --plan-sha256 … --pilot-receipt … --isolation-receipt … --kernel-receipt …` | `launch-intent.json`、attempt `validation.json`／`progress.jsonl` |
| 唯讀獨立複核 | `verify_cohort.py --attempt-dir data/m41/codex/attempts/20260926T050302Z-7fd8997cdb80` | `cohort-independent-review.json` |
| PostgreSQL 初次 | `validate_postgres.py --container-id 496838d589e1ecd392f8e9dcc4493046dc76c5c64b86930b5c3d4cd66f038683` | `postgres-validation.json`、`postgres-full-tests.log` |
| PostgreSQL 補資料及全套 | `.venv/bin/python -u data/m41/codex/reviews/v6-cohort-20260926T044941Z-32bd1394/replay_postgres_archive.py`；內部 `python -m pytest -q -ra` | `postgres-archive-intent.json`、`postgres-archive-replay.json`、`postgres-archive-full-tests.log`、`postgres-archive-validation.json` |


## 交付狀態

| 階段 | 完成情況 | 白話說明 |
|---|---|---|
| 啟動、隔離、Q2 | PASS | 模型可在限制內處理單季，Q2 仍有完整通過收據 |
| 其餘六季 | 0／6 PASS | 第一季 Q3 遇用量上限而停止，後五季尚未跑 |
| SQLite／Gemini | PASS | 349 passed、1 項 PostgreSQL-only skip；Gemini 同測試主機執行通過 |
| PostgreSQL | PASS | 補齊真實 archive 測試資料後 350 passed，沒有 failed／skipped |
| 保全／清理 | PASS | 舊資料與收據保留、無 active lock、專用測試容器已移除 |
| 重跑／真人／結案 | 未完成 | 仍需 2 次同版本重跑、35 項真人判定，不能宣稱 Final Pass |

下一步是以新 attempt 從 Q3 開始恢復模型驗收，先做 fresh CLI／程序／設定／收據閘門；不得覆寫 run 16 或直接跳到後五季。已備妥重新核對的六季 plan，本回合沒有重新送出模型批次。資料保全詳見 `final-preservation.json`，交付檔案 SHA-256 詳見 `delivery-manifest-final.json`。
