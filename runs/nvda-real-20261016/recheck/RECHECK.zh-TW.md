# NVDA bounded independent acceptance recheck

獨立 reviewer 以唯讀 SQLite（mode=ro、query_only）及既存 vendor JSON、NVIDIA／SEC 文件驗證，沒有啟動模型、Docker、瀏覽器或服務。沒有發現需要修改估值或績效數字的錯誤。原輸出 hash 完整保留；另存四份清理後 v2 使用者交付。

- 行情：755 根 split-adjusted open／close 與 cached Yahoo quote 最大差異小於 4.991e-9，NASDAQ 日期集合完全一致。首開 2022-08-26 為 17.85700035，末收 2025-08-29 為 174.17999268。2024-06-10 前 10:1 正常化正確，沒有混用含股息調整的 adjusted_close。區間含 7 個提早收盤日：2022-11-25、2023-07-03、2023-11-24、2024-07-03、2024-11-29、2024-12-24、2025-07-03。
- 成本：每筆單邊 mid-notional 收 5 bps 手續費及 5 bps 滑價，合計 10 bps；同額完整來回約 20 bps。手續費的基礎是 mid-notional，並非滑價後成交價乘股數。
- 對照組：固定 40% 僅於 13 個季度事件開盤重平衡；其餘時間持股數量固定、權重漂移。買入持有只首日買入。兩者不是每日重平衡。
- 現金：固定年有效 4%，每交易日 `(1.04)^(1/252)-1`，交易後餘額計息一次，含首日，不另計週末。這是研究慣例，非當時每日市場利率。
- 六條毛／淨曲線及已報數值均獨立重算相符，最大每日 NAV 差異小於 3e-11 USD。買入持有毛／淨閉式解為 975415.7432157971／974441.3019138833 USD。
- CAGR 期間為 2022-08-26 13:30 UTC 至 2025-08-29 20:00 UTC，共 3.0096395163130274 年。末日確為正常收盤，runner 的「所有日皆6.5小時」註解不準確但不影響本固定區間。MDD 含初始資本高水位、只用每日收盤 NAV；Sharpe 用每日簡單超額報酬、樣本標準差及 sqrt(252)，含首日部分交易日。
- 估值：research_valuations row130／forecast run263／source valuation row71。13 季 DCF 與 NaiveDCF 權重均重算相符；2024-08-29 每股 DCF 為 70.71863746098645 USD，WACC 10%、g 2.5%、五年年末折現。現金 8.563bn、金融債務 8.461bn、SEC封面股數24.53bn。所有金額以 USD、股數以 shares 儲存，非百萬單位混用。
- 20,251 筆時間比較從 DB metadata 重新建立後與 CSV multiset 完全相符，全部通過；去重為 5,701 個 quarter/check/timestamp/cutoff 組合。它們不是獨立證據數，也不證明當時模型存在、行情版本被封存或正式 AI 准入完成。
- 2024-08-29 明確為歷史估值。2026-09-12 事後重建仍無法成為真正樣本外結果；正式 cadence guard 未被繞過，權重仍 NULL。
- 視覺 QA 仍未驗證；未繞過既有 file 協定拒絕。HTML 僅通過資料／座標檢查。

依據：

- [原估值與完整證據說明](../outputs/REPORT.zh-TW.md)
- [不可變估值輸出](../outputs/valuation.json)
- [時間比較逐筆帳](../outputs/temporal_audit.csv)
- [時間比較分類及範圍](pit_scope.json)
- [原輸出凍結 hashes](original_outputs_frozen.json)
- [原回測帳務與指標程式](../source_only/run_nvda.py)
- [Canonical DCF](../backend/src/valuation_engine/research/dcf.py)
- [發行人公告](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025)
- [SEC 10-Q](https://www.sec.gov/Archives/edgar/data/1045810/000104581024000264/nvda-20240728.htm)

不覆寫原輸出的精確重現指令，從 StockOS 專案根目錄執行：

```sh
zsh runs/nvda-real-20261016/source_only/reproduce_in_new_directory.sh
```

這會建立新的 runs/nvda-reproduce-XXXXXX，重用已固定 canonical checkout，從原資料庫建立新的本機唯讀運算副本，輸出新的 metrics/ledger/valuation/verification，不需模型、網路或 Docker。腳本已通過 shell 語法檢查；此次複核沒有重跑原 runner，以免覆寫既存輸出。

四檔 v2 在 `deliverables_v2/`，metrics 與 trade ledger 與原版逐 byte 相同。原始資料庫、文件、回應、憑證與個人路徑未包含其中。支援的 Library 保存流程已嘗試，但在程序執行前遭 automatic approval review 拒絕，理由是原始指示要求先留本機且沒有明確同意 Library 持久保存。沒有發生上傳或不確定的外部寫入，未改用替代路徑。等待明確的人類許可；本機交付可直接使用。
