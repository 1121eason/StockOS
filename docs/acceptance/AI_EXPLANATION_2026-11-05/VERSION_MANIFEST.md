# 版本與證據 manifest

日期：2026-11-05。所有本輪程式變更均在隔離工作副本，未 commit。

| 項目 | 採用版本／範圍 | 證據用途 |
|---|---|---|
| 隔離工作副本 | `/Users/eason/Documents/Coding/StockOS/workspaces/ai-synthesis-20261105` | 保護原始 dirty 工作區及同步參考檔 |
| 程式基線 | `18f346ee38d327fbfe49970aea0b8643e03a9e10` | AI 修訂候選與產品來源基線，包含已整合 main |
| 已整合 main | `132c367ff8fcd5d91dabc431306c9b381dae5e1a` | 已核對財報重建與產品流程基線；不代表新 AI 已合併 |
| 本輪分支 | `codex/ai-synthesis-20261105` | 只供本機變更審閱，沒有 commit／push |
| 綜合摘要契約 | `StockOSResearchSynthesisV1` | 量化衍生摘要及 AI 待審內容，不准入 |
| 本季請求契約 | `StockOSAIExplanationRequestV1` | 已核對研究與完整合格原文；預設 current_previous |
| AI 候選契約 | `StockOSAIExplanationV1` | 四類研究觀點與逐字引文，不能夾帶分數／核准欄位 |
| 本季研究 | NVDA FY2027-Q2；前季 FY2027-Q1 | 目前報告適用期 |
| 保存研究快照 | `01e6cbec5b266633514d605fed39c0d625be879dbed984d2e55044a249c86c23` | 從既存 ProductStore 唯讀匯出並核對 digest，沒有重跑財務或報價 |
| 研究 binding | `b788165e2f6687515a13de00478d7637afd9f84b74f57e6224c8d7f3514fba40` | 綁定研究輸入；股價與核對時鐘不在 binding 內 |
| 原全研究範圍包 | `outputs/ai-completion-20261105/`；29 官方來源、9,765 blocks、7,422 表格列 | 稽核準備結果；5,198,821 bytes，不可直接當作已授權可執行輸入 |
| 原全量 request canonical SHA | `0026b5cfeb9215a44ac0c8b9e7cbfca78c4bc25659cb5a0c17d1561f26ed67d9` | [原包收據](../../../outputs/ai-completion-20261105/receipt.json)；實體 JSON 格式 SHA 與 canonical SHA 是不同項目 |
| 最終本季／前季 v2 包 | `outputs/ai-completion-20261105-current-prior-v2/`；4 份官方來源（25／90／91／121）、2,735 blocks、1,647 表格列、349,168 文字字元 | [v2 收據](../../../outputs/ai-completion-20261105-current-prior-v2/receipt.json)；來源 26 被 121 supersede，但原 metrics lineage 與 bytes 核對保留 |
| v2 request canonical SHA | `32c9e4cf9760d5eb612a794437e7b9b6aab3fff02e6b74d97fd58672eaef1225` | 本輪建議執行輸入；不能沿用全量或舊 current-prior 的 hash |
| 舊 scoped 包 | `outputs/ai-completion-20261105-current-prior/` | 保留原件供稽核，不覆寫、不作最終執行包 |
| 離線分段／研究 stage 計畫 | 20 chunks（上限 18,000 chars；最大 17,999，最大 block 3,066）+ synthesis 1 + challenge 1 = 22 research stages | 未執行；prompt token 與新 transport 綁定仍待驗證 |
| 建議總 StockOS-owned 啟動上限 | 22 research + 最多 7 fresh isolation diagnostics = 最多 29 CLI invocations；序列、outer retries 0，失敗停止 | 待使用者確認；不是供應商 HTTP 呼叫計數，也不含正式 promotion |
| 舊 AI 修訂包 | FY2023-Q2，`OFFLINE_EDITORIAL_CANDIDATE`，品質 UNSCORED、promotion false | 可保留歷史審查參考；不適用本季研究 |
| 本季模型與品質 | 未執行；兩位獨立審查者 0/2 | 沒有新模型版本、分數、winner 或准入證據 |

## 檔案與測試證據

本輪來源包含 `research/synthesis.py`、`research/ai_request.py`、`scripts/prepare_ai_explanation.py`、Workbench／Product／UI 接線與對應測試。最終原始碼雜湊應在所有修補完成後產生，不能將基線 commit SHA 當成未提交變更的內容證明。

[失敗隔離與唯讀接線測試收據](../../../reports/ai-completion-20261105/agent-synthesis-validation.json)為工程證據。[Python 最終目標收據](../../../reports/ai-completion-20261105/python-tests.xml)：117 passed、0 failed、0 skipped，涵蓋新 synthesis／request、既有 Workbench／Product／發布與財務重建整合。早期 `request` fixture 收集錯誤已修正，該次初跑不計為通過證據。

[無監聽 UI 收據](../../../reports/ai-completion-20261105/ui-focused.log)：36 passed、0 failed；語法檢查與 UI build 通過。初次完整 UI 為 35 passed、5 個既有 fixture 因 `listen EPERM` 受阻，未取得原生重跑，不宣稱整套 UI 全過。

原全量包製作時，既存 operations store 前後 SHA 均為 `47cff4fb7696a256fffc02cd28e94ad87a88fc7d329cb97eaeff54d4e8cd694f`。這只證明該次離線讀取未改該檔，不代表持續服務、模型品質或雲端部署成功。

最終未提交程式及文件的逐檔 SHA 見[原始碼 manifest](../../../reports/ai-completion-20261105/source-manifest.json)；[候選 patch](../../../reports/ai-completion-20261105/candidate.patch)可獨立審閱。[交付收據](../../../reports/ai-completion-20261105/delivery-validation.json)記錄最後測試範圍與限制。

## 2026-11-06 AGY 本地執行附錄

以上為 2026-11-05 離線準備基線；其中「未授權／模型呼叫 0」僅描述當時作業。使用者其後已授權暫時收緊權限、驗證後執行本季分析並還原。以下更新本地 AGY 診斷事實，不改判舊 W1／FSI-S2，也不更新原 source-manifest、候選 patch 或正式准入。

| 項目 | 目前固定值／狀態 | 可重核證據 |
|---|---|---|
| 模型／CLI | gemini-4-argon-high；官方 CLI 1.4.9；binary SHA `a66421b7962ffe5642e00cffdd2844dfde440e540502a29d206be5544a065c7b` | 安裝檔 `/Users/eason/.local/bin/agy`；[v6 契約](../../../outputs/agy-explanation-strict-20261106-v6/contract.json)；backend snapshot 仍 UNVERIFIED |
| 請求與資料 | NVDA FY2027-Q2／前季 FY2027-Q1；request canonical SHA `32c9e4cf9760d5eb612a794437e7b9b6aab3fff02e6b74d97fd58672eaef1225`；research binding `b788165e2f6687515a13de00478d7637afd9f84b74f57e6224c8d7f3514fba40` | [凍結 v2 收據](../../../outputs/ai-completion-20261105-current-prior-v2/receipt.json)／[request](../../../outputs/ai-completion-20261105-current-prior-v2/request.json)／[schema](../../../outputs/ai-completion-20261105-current-prior-v2/candidate.schema.json)／[22-stage 計畫](../../../reports/ai-completion-20261105/execution-plan.json)；4 官方來源、2,735 blocks、1,647 表格列，不截斷 |
| request 實體 JSON SHA | `767e69f7173aae6abf11fee7300524144fb14607ea47e664cba34e61481e9e62` | 與 canonical SHA 分列，不互相替代；資料仍未送作財報研究 |
| v6 執行契約 | StockOSAGYControlledBoundaryV2.4-PlanModeRepair；policy SHA `6d9be839112561f5f9826f85c8dda59e7d88837f66801810e83c1a9b5d6f459f` | accept-edits＋strict／明確 deny＋私有 audit hooks＋原生檔案控制；10 plugins 暫停並還原；[契約](../../../outputs/agy-explanation-strict-20261106-v6/contract.json) |
| 額度／失敗 | 上限診斷 7、研究 22；reserved 6/0，六筆全為 FAILED，剩餘 1/22；第六敗未獲例外，失敗停止仍生效 | 五份不可變固定修補鏈保留前五敗、不退款、不提高上限；[完整 ledger SHA 清單](../AGY_EXPLANATION_2026-11-05/README.md) |
| 實際研究與內容 | 財報傳送 0、研究完成 0/22；合成診斷已發生，不能再稱本輪完全零推論 | v4 診斷記一筆 synthetic generation；v5 記 5 generation／1 executor；v6 結果仍無准入 structured object。[v6 結果](../../../outputs/agy-explanation-strict-20261106-v6/attempt-0006/result.json)／[摘要](../../../outputs/agy-explanation-strict-20261106-v6/summary.json) |
| v6 工程驗證 | 單次 615 passed，0 fail/error/skip；Ruff、mypy 通過 | [合併收據](../../../reports/ai-completion-20261105/agy-final-preflight-v6-20261106.xml)：354 額度／恢復、65 設定、158 guarded、38 stages；不作原生／內容／正式准入證據 |
| 還原與正式來源 | 已完成 strict-v1～v6 的 settings／hooks 原 bytes、mode 還原；v4～v6 plugins 亦還原；各輪保護前後指紋一致；正式 DB／commit／push／部署皆 0 | [v6 還原](../../../outputs/agy-explanation-strict-20261106-v6/restoration.json)／[保護前](../../../outputs/agy-explanation-strict-20261106-v6/protection-before.json)／[保護後](../../../outputs/agy-explanation-strict-20261106-v6/protection-after.json)；各歷史輪次見 [AGY 說明](../AGY_EXPLANATION_2026-11-05/README.md) |

strict-v6 執行時未提交的 AGY 核心檔案 SHA 如下；這是當次內容指紋，沒有新 commit／push。它們不宣稱更新了上方較早的 source-manifest；下方另列同日後續離線修補。

| 檔案 | SHA-256 |
|---|---|
| `src/valuation_engine/ai/agy_explanation.py` | `052352db2cfff35337b0112c7e44fb89d0d48ff232cab1e023ceea4132c74bc2` |
| `src/valuation_engine/ai/agy_guarded.py` | `1a2b756e65da9cb28742e0ac0f80365335b6330bffa858cf3cfa80ba99ee5b84` |
| `src/valuation_engine/ai/agy_policy.py` | `a0aeb3487b5fe5a3b33c1d27cce497b0398f8c3003d216a2d07def37699d80e8` |
| `src/valuation_engine/ai/explanation_stages.py` | `cef9e038012638c300264c7a4b0ec39f6eea5762603eb7c1cc4e841ae652d1f7` |
| `scripts/agy_evidence_hook.py` | `4e48b72058f92376a0cc03c8a905f1cb0fbea0c8c8ce3af2b9d3065b856a3019` |
| `scripts/run_agy_explanation.py` | `9858d14f4530f0d964ea154215c4c274678660fe01eb79921e950a6f117fdb4a` |

剩餘缺口是命令／寫入／子代理的真實負向覆蓋、完整 fresh gate、零外部嘗試的注入測試與正確結構化完成；`finish` 的實際可用性仍 UNVERIFIED。terminal SUCCESS／原始 JSON 文字不等於 schema 通過。品質 UNSCORED、獨立審查 0/2、promotion=false，沒有正式 AI 估值或自動 AI 排程。

## 同日後續：回傳相容性離線修補

`agy_guarded.py` 的後續版本為 `StockOSAGYGuardedTransportV3-ResponseCompatibility`，解碼器 `StockOSAGYResultDecoderV1`。原生欄位缺席時可嚴格解碼 schema 綁定的完整 `response` JSON；原生欄位無效、雙份答案矛盾或階段驗證失敗仍拒收。此修改不涵蓋工具配置／權限門檻，不啟動 AGY 或重判任何歷史失敗。

最新逐檔 SHA、保護與 ledger 前後核對見[新離線修補收據](../../../outputs/agy-response-compat-20261106/receipt.json)；[667 項合併測試](../../../reports/ai-completion-20261105/agy-response-compat-tests-20261106.xml)包含 52 項新回歸。這一版尚未取得原生重跑證據，研究維持 0/22、品質 UNSCORED、promotion=false。上表的 v6 guard SHA 是歷史執行指紋，不是這份新修補的內容指紋。
