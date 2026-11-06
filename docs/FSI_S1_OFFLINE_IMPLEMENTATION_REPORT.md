# FSI S1 離線實作交付

日期：2026-09-28 Australia/Brisbane。狀態：**OFFLINE_ENGINEERING_READY — 僅 SQLite 離線候選路徑**。必要的 candidate guard、身分、儲存／reader、comparator 驗證通過；PostgreSQL 未執行，整庫回歸有兩項在未修改基線同樣重現的 Gemini 失敗，因此本報告不宣稱整库全綠、跨 backend 通過或 S2 ready。

已完成 W1–W6。產品程式只新增於隔離副本；正式 checkout 只新增本報告及 ignored 的本次候選交付目錄。**股票分析 pipeline live calls=0；正式 DB／原 240 份交付／原 235 個 Git-visible 檔案未變；真人審查仍為 0/35。**

這是已授權 S1 的實際實作，不是新的設計建議。原交接當下確實尚未實作；本次從綁定當下 dirty V6 開始，沒有用 HEAD 覆蓋它。

## 交付入口

- [候選程式與測試目錄](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate)
- [可審查 patch（未套回正式 checkout）](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate.patch)；[git apply --check 收據](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/patch-check.json)
- [34 項驗收矩陣](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/ACCEPTANCE_MATRIX.md)／[machine-readable matrix](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/acceptance-matrix.json)
- [真實封存 A* 全量 audit](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/guard-impact.json)／[35 張卡 companion guide](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/REVIEW_COMPANION.md)
- [最終保全收據](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/preservation-final.json)／[candidate content manifest](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/candidate-content-manifest.json)
- [S2 待批准計畫，禁止執行](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/S2_PENDING_PLAN.json)

完整持久 root：`/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e`。不依赖暫存工作目錄。`baseline/` 是保留 dirty V6 的凍結副本，`candidate/` 是候選；`inputs/baseline.sqlite` 是唯讀來源 DB 的一致性 backup；`synthetic/B-release` 與 `synthetic/C-release` 僅為明確標示的合成示範，不混入真實 cohort。歷史 A* 結果只寫新 audit sidecars。

## W1 — 綁定基線與隔離

| 項目 | 實測 |
|---|---|
| 正式 checkout | `/Users/eason/Documents/Coding/StockOS` |
| Branch / HEAD | `main` / `22e9b9ee944408cb67d5217ca66dd880498fb440` |
| 完整 Git-visible baseline | 235 files；包括交接 MD 與既有未提交 V6 |
| 完整 worktree digest | `cec26d5984ef2361138875623bb5903bd2b91f56f1ae42340cb977e3722e896b` |
| 排除交接 MD 的旧集合 digest | `e78203651f3ec6f3bd17f16261b3615a9209572d7e66b81e8cf00ba2965acba5`，與交接一致 |
| DB instance | `dev:16777232:ino:92914711` |
| DB consistent snapshot digest | `ccae67b6ec23a23cef0a622ddf477c2ced78382280884e1edfc73d7e21ceca4c` |
| 正式 DB bytes digest | `31bcd861823f903904d1ffab16f6adf93db36044f083dac4869e0a7ff78cb679` |
| 原交付 | 240/240 bytes hash 相符 |
| PG test URL | 未配置，0 次連線 |

[完整 baseline manifest（含 dirty paths）](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/baseline.json)。以唯讀 SQLite 連線做 backup，並用獨立唯讀 transaction 的逐表完整 row multiset hash＋schema hash 比對；沒有 checkpoint、journal mode 修改或正式 migration。測試用 archive DB 另複製在候選 `data/qve.db`；未連正式 DB 執行 tests。

| Frozen file | SHA-256 | 核對 |
|---|---|---|
| `src/valuation_engine/ai/contracts.py` | `2f7f14c7ae6d59cb386a2c9110043b3cfd4f61aa91034f0d549de191b5f4884c` | 原件與候選內 frozen base 相同 |
| `src/valuation_engine/ai/prompts.py` | `f0ba44e3b3a66e8f4c8b0c9584f02fb228357ca60a7543c8920a60b98931d175` | 原件與候選內 frozen base 相同 |
| `src/valuation_engine/ai/guards.py` | `68502157a73393600311152f68a55160a088a6a669ee1af6689f1775e7f2a53c` | 原件與候選內 frozen base 相同 |
| `src/valuation_engine/ai/service.py` | `94089c072a92de2d265ca05526a4cd6508167c2ec2541f24ed990ae57e9b4286` | 原件與候選內 frozen base 相同 |

`sources/` 未修改。未複製 credentials、`.env` 或 HOME 設定；沿用原 `.venv` 的已安裝 dependencies，產品 import 與 tests cwd 指向副本，沒有下載依賴。

## W2–W5 — 實際程式

| 檔案 | 變更 | SHA-256 |
|---|---|---|
| [scripts/run_fsi_s1_offline.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/scripts/run_fsi_s1_offline.py) | 新增；57 行 | `f98000f1615fde3638e62d7dcc57bc0a2a5bdb7c1fde6336ca6db7aa734d6409` |
| [src/valuation_engine/ai/fsi/__init__.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/__init__.py) | 新增；1 行 | `ecfe7858b3f3fa28be4d1fee409dfeec7b68d5f9260f8a3432c92f7065fdb75a` |
| [src/valuation_engine/ai/fsi/audit.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/audit.py) | 新增；298 行 | `d137302d12ab6f732ddcc7e7f1f819a2114ec195bdbc9e133dc5d1d0800adace` |
| [src/valuation_engine/ai/fsi/compare.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/compare.py) | 新增；343 行 | `3e1b4550c81cc94a3607408d3acc72abb069a6763d6469f82ecc2982b6b73dc7` |
| [src/valuation_engine/ai/fsi/guard.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/guard.py) | 新增；125 行 | `cc39368d0066948445012184049d8c4dccd35705e9f33242bf8ed7ddb9c4bfcd` |
| [src/valuation_engine/ai/fsi/profile.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/profile.py) | 新增；133 行 | `7b5f8adc6181ce9b70ec7e275a3d13bbce6041c3c0ce7e20dc918f1fda167576` |
| [src/valuation_engine/ai/fsi/service.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/service.py) | 新增；209 行 | `6b37f06dea1a07f65a7bbede79cb76d6006dee7b6a43c44b20cb55c85278c6b8` |
| [src/valuation_engine/ai/fsi/storage.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/src/valuation_engine/ai/fsi/storage.py) | 新增；270 行 | `dde32773b4a3ab39579dcca7c575f488caed92a64c29f8a015eb76a06a5572e0` |
| [tests/unit/test_fsi_s1.py](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/tests/unit/test_fsi_s1.py) | 新增；605 行 | `bc066be3f3d4e918968cf082320134d10772c002a125a2be8a5289eeed72619c` |

Guard G=`FSI-S1-G-EvidenceIntegrity-v1`，實作 hash=`cc39368d0066948445012184049d8c4dccd35705e9f33242bf8ed7ddb9c4bfcd`。runner hash=`2868bfb81d9d2b76406a093a701ef4b91eddd16631b8c63497c3173716f8eb5b`，涵蓋實際產品 Python bundle。B/C 使用同一 G；V6／V2／V3 全域常數、原 prompt、policy、service 與正式 defaults 沒有修改。

- `guard.py`：全 28 個 feature 保持正有利／負不利；同側穩定去重、跨側直接 role-conflict 拒收；mixed 留在 sidecar，不自動當反駁或決定性支持。整理後再檢查非零 support／topic／reference。源資料准入重用原 span／speaker guard 與 PIT package validation。
- G 是另立候選 policy overlay。舊 V3 對 mixed 自動加入反證、跨側採反證優先；G 改為 sidecar 與拒收衝突。對零分且只含 mixed，G 保守拒收 `FSI.ZERO_MIXED_UNRESOLVED`，不把 mixed 轉成 neutral；有來源的 neutral 零分保留。這些差異均未改写原 V3。
- `profile.py`：frozen profile 保存方法與各 stage 模板，包含 method ID／hash、effective bundle hash、baseline／input／schema／policy／G／runner 身分。所有 request、run payload、feature binding、cache key 與明確 reference 都帶候選身分，不冒用 V6。cache 目前只計算隔離 key，**沒有生成結果快取重用功能**；因此不把 cache 命中算 fresh。
- `service.py` 與独立 script：只接受確切型別的 immutable `SyntheticTransport` 資料，拒絕任何 live provider／子類／auth callback；`live_entrypoint` 固定硬失敗。每批 extraction 保存實際完整 request hash；後段帶本次已准入 evidence／features 與 call lineage。confidence 由既有函式產生。
- `storage.py`：獨立 SQLite schema 和 DB instance UUID，不改正式 tables／migrations。run＋snapshot＋profile＋quarter＋input／guard／schema／policy／payload hashes 為唯一 resolver 的必填身分；detail、review、aggregate 都使用它，沒有 latest／earliest fallback。保存使用 transaction、外鍵、支持關聯回讀與重新准入核對；故障時 rollback，另留 sanitized engineering error。root 與所有既有輸出檔拒絕 symlink／hardlink／正式路徑別名，DB／output／cache／logs／config／receipt 都在候選 root。
- `compare.py`：method 只允許 B 的角色澄清加上 C 的固定 FSI 段落；其餘固定條件逐欄比較。repeat 固定 profile、原始來源與設定，extract hash 必須一致；synthesis／challenge hash 可以因本次新上游產物不同而不同，並重建 request／檢查輸出准入與本次 call lineage。cache／resume／A* 不算 fresh。未知 actual model 保持 null／false，標示 `OBSERVABLE_SETTINGS_MATCHED_ACTUAL_MODEL_UNVERIFIED`。

[B/C prompt allowlist 與完整方法差異](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/METHOD_DIFF.md)。[B 合成 explicit reference](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/synthetic/B-release/receipts/reference.json) 與 [C 合成 explicit reference](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/synthetic/C-release/receipts/reference.json) 的整數 IDs 都是 1/1，但 DB instances 不同，測試證明不可互換。[合成 method comparator 結果](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/synthetic-method-comparison-release.json) 只證明比較前提實作，不是 FSI 模型效果。

## W6 — 真實封存 A* 與影響

使用明確 run/snapshot：15/4、17/5、18/6、20/7、21/8、22/9、23/10、24/11、25/12。每個來源包重建 hash；所有 synthesis evidence 對照 DB metadata、原 extraction raw output、當批 source block、PIT cutoff、span 與 speaker 重新准入。沒有模型再分析。

| 計數單位：raw feature candidate／保存 feature 實例 | 結果 |
|---|---:|
| 9 runs 的 raw candidates | 232 |
| 原 accepted / rejected | 171 / 61 |
| G accepted / rejected | 98 / 134 |
| 原 accepted 現被 G 拒收 | 73：72 role overlap＋1 direction unsupported |
| G accepted 非零而 final support 為空 | **0 / 98** |
| 固定 16 個空支持案例 | **16/16 拒收**；原資料不改 |
| 固定 Q2 10 個原拒收案例 | **10/10 維持拒收**；沒有恢復分數 |
| 16／10 的实例交集 | 0；不同 run 的同名 feature 仍是不同實例 |
| G 仍接受且 confidence 輸入／值改變 | 14；僅歸因 G |

**G 的影響超過原先 16 個案例。** 16 個目標的 raw supporting／contradicting 已存在重疊且涉及 mixed，新 G 在 role-overlap 階段拒收；不能把它們重新標成方向已判錯。全部 232 個 raw candidates 的拒收理由為 overlap 72、final support empty 31、direction unsupported 31。這是保守新規則的機械影響，未經人審不得推論正確率上升或下降，也不應直接正式 promotion。

| 季度 | Run / snapshot | 明確 row ID | Feature | 原狀態 | G 結果（均拒收） | Confidence |
|---|---|---|---|---|---|---|
| FY2023-Q3 | 17 / 5 | [feature-43](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-43.md) | `demand_momentum` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.4025625 → null |
| FY2023-Q3 | 17 / 5 | [feature-44](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-44.md) | `pricing_power` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.312375 → null |
| FY2023-Q3 | 17 / 5 | [feature-53](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-53.md) | `inventory_quality` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.33685417 → null |
| FY2024-Q1 | 18 / 6 | [feature-60](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-60.md) | `pricing_power` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.35217857 → null |
| FY2024-Q1 | 18 / 6 | [feature-65](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-65.md) | `working_capital_quality` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.37525 → null |
| FY2024-Q1 | 18 / 6 | [feature-68](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-68.md) | `export_control_outlook` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.36955 → null |
| FY2024-Q2 | 20 / 7 | [feature-77](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-77.md) | `pricing_power` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.2624375 → null |
| FY2025-Q4 | 21 / 8 | [feature-102](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-102.md) | `china_outlook` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.34021875 → null |
| FY2027-Q2 | 23 / 10 | [feature-140](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-140.md) | `training_demand` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.208 → null |
| FY2027-Q2 | 23 / 10 | [feature-141](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-141.md) | `competition_outlook` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.3113625 → null |
| FY2027-Q2 | 23 / 10 | [feature-147](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-147.md) | `inventory_quality` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.37012 → null |
| FY2027-Q2 | 23 / 10 | [feature-149](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-149.md) | `export_control_outlook` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.35133036 → null |
| FY2023-Q2 | 24 / 11 | [feature-155](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-155.md) | `demand_momentum` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.39372222 → null |
| FY2023-Q2 | 24 / 11 | [rejected-197](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-197.md) | `demand_visibility` | rejected | `direction_unsupported` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-198](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-198.md) | `pricing_power` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-199](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-199.md) | `supply_constraint` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-200](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-200.md) | `custom_asic_outlook` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-201](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-201.md) | `customer_insourcing_outlook` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [feature-164](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-164.md) | `working_capital_quality` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.39786905 → null |
| FY2023-Q2 | 24 / 11 | [rejected-202](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-202.md) | `customer_financing_quality` | rejected | `direction_unsupported` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-203](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-203.md) | `china_outlook` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-204](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-204.md) | `export_control_outlook` | rejected | `FSI.FINAL_SUPPORT_EMPTY` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-205](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-205.md) | `guidance_visibility` | rejected | `direction_unsupported` | null → null |
| FY2023-Q2 | 24 / 11 | [rejected-206](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/rejected-206.md) | `management_credibility_signal` | rejected | `direction_unsupported` | null → null |
| FY2023-Q3 | 25 / 12 | [feature-172](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-172.md) | `demand_momentum` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.39526064 → null |
| FY2023-Q3 | 25 / 12 | [feature-181](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/cases/feature-181.md) | `inventory_quality` | accepted | `FSI.EVIDENCE_ROLE_OVERLAP` | 0.35852174 → null |

每個案例檔保留 DB instance／snapshot digest、raw call ID＋JSON pointer、來源包與 synthesis hash、原角色、實際保存 links、原文／speaker／source IDs、G trace、confidence 函式 hash／evidence keys／去重 span set／反證扣分。新 G 拒收時 accepted confidence=null，沒有寫成 0。

### 仍接受的 14 個 confidence 變動

| Run | Feature | Old saved | G | Delta（G only） |
|---|---|---:|---:|---:|
| 15 | `demand_momentum` | 0.38624286 | 0.38221667 | -0.00402619 |
| 15 | `demand_visibility` | 0.50342149 | 0.51069922 | +0.00727773 |
| 15 | `margin_outlook` | 0.53360906 | 0.58437461 | +0.05076555 |
| 15 | `working_capital_quality` | 0.57823920 | 0.67623111 | +0.09799191 |
| 15 | `revenue_quality` | 0.40748214 | 0.43520118 | +0.02771904 |
| 15 | `regulatory_outlook` | 0.46379297 | 0.50604079 | +0.04224782 |
| 17 | `long_term_demand_durability` | 0.44755556 | 0.76000000 | +0.31244444 |
| 22 | `demand_momentum` | 0.36078409 | 0.34068056 | -0.02010353 |
| 22 | `demand_visibility` | 0.45425779 | 0.48772852 | +0.03347073 |
| 22 | `margin_outlook` | 0.33770968 | 0.33692241 | -0.00078727 |
| 22 | `working_capital_quality` | 0.36347826 | 0.36596591 | +0.00248765 |
| 22 | `inventory_quality` | 0.55189474 | 0.59357407 | +0.04167933 |
| 22 | `export_control_outlook` | 0.58354325 | 0.60941016 | +0.02586691 |
| 25 | `long_term_demand_durability` | 0.31350000 | 0.52000000 | +0.20650000 |

公式本身未改；mixed／角色整理改變其 items、contradictory、去重集合與扣分，所以變動可正可負。完整實際輸入見 audit 的 `all_feature_results[].confidence`。不得把變动解讀為 FSI 或人類語意信心改善。

### 原 35 卡

[Companion guide](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/audit/release/REVIEW_COMPANION.md) 保留 35 張原卡的所有人工欄位；8 個目標案例屬原卡 run 集合，18 個不屬於這 35 卡的 run 集合，單列額外診斷。沒有發明 feature-to-category 對應，也沒有改變 35 分母。真人 verdict、reviewer、reviewed_at 均未代填。

無官方 transcript 的 Q&A 能力列不適用，合法其他 management source 仍可審查。類別 missed rate 與 gold-item omission／recall 分開；目前沒有真人分母或 gold set，全部 null／NOT_MEASURED。

## 測試與驗收

| 執行 | 實際結果 | 收據 |
|---|---|---|
| 凍結 V6 漏洞重現 | 預期 4 failed：mixed-only、overlap、final empty、實際 legacy service 保存空支持 | [red receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/legacy-red.log) |
| 最終 S1 測試 | **104 passed，0 failed，0 skipped**；102 synthetic candidate cases＋1 real archived audit＋1 offline harness boundary | [JUnit](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/s1-release.xml)／[command/start/end/exit](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/s1-release.json) |
| 整套 SQLite 離線回歸 | **519 passed，2 failed，1 skipped**；共 522。唯一 skip 為 PostgreSQL migration contract | [full log](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/offline-full-release.log)／[JUnit](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/offline-full-release.xml) |
| 未修改 baseline 的兩項 Gemini 重驗 | 相同兩項均 failed，證明此隔離執行環境下不由 S1 diff 引入 | [baseline receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/baseline-gemini.log) |
| Ruff | PASS | [receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/ruff-release.json) |
| mypy | PASS，78 source files | [receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/mypy-release.json) |
| Patch apply check | PASS；未 apply | [receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/patch-check.json) |
| PostgreSQL | **BLOCKED／NOT RUN**，無 `QVE_TEST_POSTGRES_URL`，未改接正式 DB | [receipt](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/postgres.json) |

兩項 baseline failures 為 `test_google_probe_and_isolation` 與 `test_service_ineligibility_is_not_login_failure`，都是本地 Python 假 CLI fixture。沒有修改 Gemini 來湊通過，未探測真實 Gemini；本輪未定位其底層環境原因。

早期測試收據亦保留：最初 guard loader 與 Python 既載入的 `sitecustomize` 名稱相撞，harness 自測暴露 DNS 阻擋未生效；修正為明確載入指定 guard。之後第一輪整庫 run 的 38 項 fake CLI 被過度嚴格的 process gate 攔下；縮小允許範圍為本輪 test root 內、已知 Python shebang 的 synthetic scripts 及其 OS sandbox wrapper 後，剩上述兩個 baseline failures。沒有刪除失敗 fixtures、放寬 G、連正式 provider 或更換 DB。

最終 process audit 只記錄合成 Python／本次目錄內假 CLI／其 OS sandbox，以及預期被攔下的網路自測。[process boundary log](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/process-boundary.jsonl) 不保存 argv、環境變數或 credentials。獨立的 candidate API 仍在任何 callback 前拒絕 live provider。

34 項矩陣為 **33 PASS_OFFLINE，1 PARTIAL（A04 的 PostgreSQL 未跑）**。C03a／b／c 均有獨立測試但仍算一個矩陣項。C07／C08 僅證明 fixture、source applicability 与契約行為，不代表真實模型不會犯語意錯誤。完整測試 source／fixture／收據 hashes 見交付 manifest。

重現 S1：使用現有 `/Users/eason/Documents/Coding/StockOS/.venv/bin/python` 執行 `/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/run_tests.py tests/unit/test_fsi_s1.py /Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/tests/test_real_archive.py -q`。launcher 會把 cwd／imports 綁定 candidate，設置新的獨立 test root 並禁止外網與真實 provider process。原生入口 `/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/candidate/scripts/run_fsi_s1_offline.py` 僅接受 `synthetic`／`audit`，需明確 config/root/formal-root；沒有 live mode。

## 保全、剩餘決策與回復

[保全收據](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/receipts/preservation-final.json) 證明原 235 files、240 份交付、正式 DB 全表（含 Quant／Regime／AI／human review）與 schema 一致。正式 DB bytes hash 亦一致；journal mode 仍 delete，無 WAL。候選 frozen base files 未被改寫，只有上述新檔。

本次沒有 commit、push、PR、merge、deploy、正式 migration、guard promotion、provider fallback、plugin 安裝、原分數回填、M4.1 Final Pass 或 M5。`data/m41/fsi/s1/...` 是新資料目錄，不覆寫原交付。停止使用候選入口即停止候選；不需要 reset／清掉 owner 原有修改。

S1 的 SQLite 離線工程 gate 已可供審查；PostgreSQL 與上述 baseline Gemini 回歸限制仍明列。S2 不具授權，也未具 live-ready profile。[待批准計畫](/Users/eason/Documents/Coding/StockOS/data/m41/fsi/s1/20260927T162109Z-2bb2cc6e/S2_PENDING_PLAN.json) 固定 FY2023-Q2 原 run 15/snapshot 4，附 repeat 24/11；source package hash 相同。條件式估算為 20 extraction＋1 synthesis＋1 challenge，每組 22；B/C 各一次 44，且各 fresh repeat 共 88，均未含重試／探測，不是批准額度。

開始 S2 前仍須 Owner 批准範圍、total-call/retry cap、actual-model-unverified 比較限制；補齊 live profile／可觀察設定，並另案接入與驗證 live adapter。先審查 G 的 73 個額外拒收影響與固定人審 rubric。**目前沒有 B/C 品質勝者、語意 repeat PASS 或新增真人完成數。**
