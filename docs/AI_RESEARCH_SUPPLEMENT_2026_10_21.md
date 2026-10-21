# AI 研究補充：單季驗收工作線

日期：2026-10-21。定位：補充需求、競爭與風險的證據分析；不修改 Quant、Regime、估值或配置，不產生買賣建議。

本輪完成既有 W1 六個候選檔案的現況雜湊核對、凍結協定內容雜湊及來源準備的綁定核對，並從指定的原始 run 15 重新準備 FY2023-Q2 來源封包。重新讀取原始 bytes、重解析、核對來源 ID／URL／hash／company／cutoff 及既存時間紀錄；沒有重用歷史 AI 輸出，沒有模型調用或正式 DB 寫入。

這一季是受控試驗季度，不是目前工作台的最新研究季度。即使試驗完成，也不能將該季結果套用到工作台的另一季度。

## 固定的版本與評分

| 項目 | 已核對的既有凍結版本 |
|---|---|
| 協定 | `FSIS2ProspectiveProtocolV1` |
| Policy／Schema | `AIAnalystPolicyV1`／`FeatureSchemaV1` |
| Guard | `Guard_G_Strict` |
| Protocol hash | `5aff6b73e6b83a5f159e66dce277eb4412c83d13624bfda6a3ce2dce91d44e1d` |
| 盲評 | `FSIS2BlindRubricV1`，兩位獨立審查者；分歧須第三人裁決 |
| 硬門檻 | 引用精確、沒有未解決的重大無依據主張、沒有非法准入 |
| 品質維度 | 爭議穩定性、洞察深度、挑戰品質，各 0–3 分；缺分與缺重複實驗保持未評，不補零或產生完整總分 |
| 呼叫上限 | 每方法 22、單對 44；Q2 重新準備計畫在此上限內，不增加外層重試或追加 repeats 預算 |

核對不等於把未提交的 W1 程式升格到正式基線；其原 reference commit 與隔離身分保留。審查分數、winner 與升格狀態仍未產生。

## 還需要的當次執行證據

1. 固定實際 CLI／模型／版本及封包身分；驗證本輪實際模型回報，不能以工具存在或舊 receipt 代替。
2. 完成適用本輪 runtime 的 native 隔離、全域程序辨識、鎖、呼叫生命周期與殘留清理證據。
3. 核實所選來源的真實性與歷史發布／可用時間。重新核對 cached bytes 與資料庫時間紀錄，不能自行升格為獨立時間驗證。
4. 前項通過後，執行一季新分析並保存完整 request／response／attempt／拒絕帳／evidence lineage。
5. 依凍結規則取得真人盲評與必要裁決，再決定是否擴展季度；不得自填分數或沿用舊固定分數。

本輪 `ready_for_live=false`、`quality_verdict=UNSCORED`、`winner=null`、`promotion_ready=false`。尚未執行新模型分析與真人評分。阻擋來自尚未完成的 runtime、模型身分與來源時間證據，不是以產品等待 AI 為交付前提。

## 可重現的離線核對

```sh
python scripts/audit_nvda_ai_readiness.py \
  --w1-checkout /absolute/path/to/isolated-w1-checkout \
  --w1-evidence /absolute/path/to/w1-evidence \
  --out data/nvda-workbench/ai-readiness.json
```

此工具只讀取與核對既有交付；不匯入或執行候選 provider，不更新舊紀錄，不授權或呼叫模型。新封包與完整來源紀錄留在本機，與公開原始碼分開。
