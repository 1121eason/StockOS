"""Build a local Traditional Chinese report and a dependency-free NAV chart."""
import csv
import html
import json
import math
import sys
from pathlib import Path

run = Path(sys.argv[1]).resolve()
out = run/"outputs"
v = json.loads((out/"valuation.json").read_text())
metrics = json.loads((out/"metrics.json").read_text())
coverage = json.loads((out/"coverage.json").read_text())
cfg = coverage["config"]
source_manifest = json.loads((out/"source_manifest.json").read_text())
def read(name):
    return list(csv.DictReader((out/name).open(encoding="utf-8-sig")))
def pct(x):
    return f"{float(x)*100:.2f}%"
def billion(x):
    return f"{float(x)/1e9:,.3f}"
names = {"NaiveDCFPolicy":"既有純 DCF", "FixedAllocationPolicy":"固定 40% NVDA／60% 現金", "BuyAndHoldPolicy":"NVDA 買入持有"}
table = "| 策略 | 毛報酬 | 淨報酬 | 淨 CAGR | 淨最大回撤 | 淨 Sharpe | 平均股票曝險 | 交易數 | 單邊週轉 |\n|---|---:|---:|---:|---:|---:|---:|---:|---:|\n"
for key in names:
    g,n = [next(m for m in metrics if m["strategy"]==key and m["variant"]==variant) for variant in ("gross","net")]
    table += f"| {names[key]} | {pct(g['cumulative_return'])} | {pct(n['cumulative_return'])} | {pct(n['cagr'])} | {pct(n['max_drawdown'])} | {n['sharpe']:.3f} | {pct(n['mean_equity_exposure'])} | {n['trade_count']} | {pct(n['one_way_turnover'])} |\n"
flows = "| 未來年度 | FCFF 代理現金流 | 折現後現值 |\n|---|---:|---:|\n"
for row in v["explicit_cashflows"]:
    flows += f"| {row['year']} | {billion(row['fcff_proxy_usd'])} | {billion(row['present_value_usd'])} |\n"
ledger = [r for r in read("trade_ledger.csv") if r["strategy"]=="NaiveDCFPolicy" and r["variant"]=="net" and r["trade_side"]!="NO_TRADE"]
trade_table = "| 執行日 | 動作 | 中間價名目金額 USD | 交易後目標股票權重 |\n|---|---|---:|---:|\n"
for row in ledger:
    trade_table += f"| {row['execution_timestamp'][:10]} | {'買入' if row['trade_side']=='BUY' else '賣出'} | {float(row['mid_notional_usd']):,.2f} | {pct(row['target_weight'])} |\n"
gap = float(v["base"]["per_share"])/float(v["market_price"])-1
internal = float(v["internal_five_year_fcff_cagr"])
implied = float(v["reverse_dcf"]["implied_growth"])
report = f"""# NVDA 真實資料估值與歷史回顧診斷

估值：**2024-08-29 13:30 UTC（美東 09:30），FY2025 Q2**。每股 DCF **US${float(v['base']['per_share']):.2f}**，當日開盤 **US${float(v['market_price']):.2f}**，模型價值／市價差 **{pct(gap)}**。這是以當時可取得財報資訊重建的歷史估值，不是截至 2026-10-16 的當前估值。

回測：**2022-08-26 開盤至 2025-08-29 收盤，755 個完整 NASDAQ 交易日**。純 DCF 淨報酬 **+24.29%**，低於買入持有的 **+874.44%**。策略平均僅有 12.67% 股票曝險，錯過多數漲幅。這個結果沒有調整門檻或另挑獲利參數。

## 證據與適用範圍

本機資料有 1,682 根 NVDA 日線（2020-01-02～2026-09-11）、26 季相容的正式財務預測。此次固定 13 季與 67 份來源文件。Canonical backend 為 `{cfg['canonical_commit']}`，使用相容的 assumption set 5，hash `{coverage['assumption_hash']}`。原 SQLite schema 是 `0008_ai_analyst`，以新 backend 唯讀讀取成功，沒有 migration。

財報來源為 [NVIDIA FY2025 Q2 公告](https://nvidianews.nvidia.com/news/nvidia-announces-financial-results-for-second-quarter-fiscal-2025) 與 [SEC 10-Q](https://www.sec.gov/Archives/edgar/data/1045810/000104581024000264/nvda-20240728.htm)。當季營收 US$30.040 billion，GAAP 營業利益 US$18.642 billion。來源公告的分鐘時間證據為 2024-08-28 20:20 UTC，保守可用時間為 20:21 UTC。股數採 10-Q 封面的 **24.53 billion 股（2024-08-23）**，文件接受 2024-08-28 21:05:08 UTC，加三分鐘後的可用時間為 21:08:08 UTC。兩者均早於估值 checkpoint。

股數已在 2024 年 10:1 拆股後基準，估值日額外調整因子為 1。價格／股數及 EPS 分別按自身用途保持同一基準，沒有以 diluted weighted-average shares 代替市值股數。價格來自 Yahoo Chart、下載於 2026-09-12，屬 current-vintage 歷史拆股調整行情，並非當時封存的原始觀測價。原始 vendor JSON hash 為 `95061f2842275691749f73737b8d26dd5c5409e5c9790ea27b61370dd8b32cee`。

**所有預測都在 2026-09-12 事後生成，政策也在當時定版。此次屬真實資料的回顧性診斷，不能當作歷史當時實際產生訊號、真正樣本外績效或 AI 增益證據。** 沒有用未來實現值替代預測，也沒有讀取 outcome labels。所有使用季度的預測均重新從實際財報輸入計算，與既存數值逐欄相符。

## 估值計算

使用既有 Guidance Anchored Baseline／ForecastPolicyV1。發行人下一季營收指引 US$32.5 billion，模型依原訂歷史指引偏差修正為 US${billion(v['bias_adjusted_guidance']['revenue'])} billion。模型稅率 17%，近期非營業收益／營收 1.6624%，CapEx／營收 1.4755%，OCF 減淨利／營收 −5.2900%。營收成長、毛利率、股數與營業費用延伸及衰減均依 frozen policy，沒有新估參。逐季財務表見 `forecast_periods.csv`，完整參數與輸入鏈見 `valuation.json`、`valuation_provenance.json`。

`FCFF proxy = EBIT × (1 − tax) + (forecast OCF − forecast net income) − CapEx`。

此為 NOPAT 現金轉換代理，營運資金與非現金項目仍是近似，不把未調整的 CFO−CapEx 宣稱為完整 FCFF。前兩年各匯總四個未來季度。第三至五年將第二年成長率每年向 2.5% 衰減一半。以下金額單位均為 **USD billion**：

{flows}
基準 WACC 10%、永續成長 2.5%、年末折現。第五年末終值 **{billion(v['terminal_value_year5'])}**，其現值 **{billion(v['present_terminal_value'])}**，占企業價值 **{pct(v['terminal_fraction_of_ev'])}**。

企業價值 **{billion(v['base']['enterprise_value'])}** ＋現金與約當現金 **{billion(v['balance_cash'])}** −短／長期金融債務 **{billion(v['balance_debt'])}** ＝股權價值 **{billion(v['base']['equity_value'])}**。資產負債表日期為 2024-07-28。依既定 equity bridge，未額外加回短期投資或扣除營業租賃。除以 **24.530 billion 股**，得到 **US$70.71863746／股**。

敏感度沿用 WACC 8%～12%、永續成長 2%／2.5%／3%，15 格範圍 **US$53.05～106.00**，是情境範圍，沒有機率信賴區間含義。反向 DCF 要求五年 FCFF CAGR **{pct(implied)}**；模型內部五年 FCFF CAGR **{pct(internal)}**，成長預期差 **{(internal-implied)*100:.2f} 個百分點**。這與上面的價格差是不同指標。

已實作估值比率：NTM P/E **{float(v['ratios']['ntm_pe']):.2f}×**，FY1/FY2 P/E **{float(v['ratios']['fy1_pe']):.2f}×／{float(v['ratios']['fy2_pe']):.2f}×**，forward FCF yield **{pct(v['ratios']['forward_fcf_yield'])}**，forward EV/EBIT **{float(v['ratios']['forward_ev_ebit']):.2f}×**。

## 回測規則與數值

沿用 `NaiveDCFPolicy`：DCF／市價差 ≥+5% 配 100% 股票，−20%～+5% 配 50%，低於 −20% 配 0%。未修改分配政策。每季模型以 first-tradable checkpoint 的資訊截點及開盤價格形成估值，模擬訊號時間取該日價格資料庫記載可用時間（收盤）與 checkpoint 較晚者，**下一交易日開盤成交**。例如 FY2025 Q2 的 checkpoint 為 2024-08-29 13:30 UTC，模擬訊號於同日收盤後才可用，執行日為 2024-08-30。這保留完整一個交易日的執行延遲。

初始 USD 100,000，允許碎股、無槓桿、無放空、無稅。現金按固定研究假設年有效 4%，每交易日以 `(1.04)^(1/252)−1` 計息；不是逐日實際利率。毛結果零摩擦；淨結果每成交名目金額收 5 bps 手續費、5 bps 不利滑價，合計沿用原 10 bps 假設。費用後目標權重以自償現金帳精確求解。價格只做拆股調整，**三組均不計股息或再投資，屬 price-return 比較**，不是完整股東總報酬。日線基準固定於 2026-09-12，純供回報與持股單位一致化，不作未來拆股訊號。

{table}
淨期末資產：純 DCF **US$124,288.41**，固定 40% **US$298,078.04**，買入持有 **US$974,441.30**。純 DCF 實付手續費及滑價合計 **US$133.75**。均於期末收盤標價，未額外強制平倉；買入持有淨績效包含初次入場成本。

Sharpe 採每日簡單報酬減固定日無風險利率的算術平均，除以每日報酬樣本標準差，再乘 √252，包含首日開盤至收盤報酬。CAGR 按首日開盤至末日收盤的實際經過秒數／365.25 年化。最大回撤以每日收盤淨值及初始資產為高水位計算。股票曝險為每日收盤實際權重平均；週轉為各交易 `abs(mid notional)/pre-trade NAV` 的單邊加總，含初次買入，不年化。

純 DCF 有 13 次季決策，其中 4 筆非零交易如下。完整帳本另含零交易決策、成交價、正常化股數、成本、交易前後現金與 NAV：

{trade_table}
## 驗證與剩餘限制

13 季預測由 canonical 函式重建，13 次 DCF 重算相符，20,251 項財報／指引／校準／股數／價格／歷史參照時點檢查通過。755 根行情逐筆比對保留的 vendor JSON，交易日與 NASDAQ calendar 完全一致。獨立 CSV 帳本重建另核對六條毛／淨資產曲線、買入持有閉式解與 DCF 公式。相關 canonical 單元檢查為 **275 passed、1 skipped**；合成單元檢查僅用於程式驗證，不充當此處的實際績效。

既有 walk-forward engine 會按同日 `as_of_date` 開盤排程、將終點固定在 2026-09-11，且用 CAGR 代替每日超額報酬平均計算 Sharpe。此次用獨立 runner 明確限制日期、延後一個交易日、輸出逐筆自償帳與標準 Sharpe。它呼叫原有配置政策及估值公式，canonical source 無改動。

正式 cadence 驗證回傳 `INCOMPLETE_REVISION_CONTEXT`，股票及現金權重均為 NULL。原因是未選定 fiscal revision target，AI exact-run admission／人工核准契約也尚未具備。此次沒有用診斷權重冒充正式 cadence 核准。真正樣本外回測尚缺當時封存的模型與參數／訊號版本、當時行情版本及正式訊號完整證據與核准鏈。這是資料／證據缺口，沒有權限拒絕、待核准的付費步驟或未確定的外部執行結果。

原始工作區、索引、branch、全部原始資料檔與資料庫由前後 hash 核對；最終見 `preservation.json`。所有新輸出、獨立資料庫副本及來源 bytes 都留在本機此 run 目錄。模型呼叫 0、實際下單 0、Docker 呼叫 0。收尾發現 8501 沒有監聽程序，已依原指令啟動原示範 UI，健康 API 回應 200；UI 程式與資料未修改。帳戶共用週用量由 3% 到 4%，低於 45% 停止線；不是此任務的獨立用量計量。見 `usage_and_ui.json`。

圖表 HTML 已產出並通過資料／SVG 座標結構檢查。原生瀏覽器視覺驗收尚未完成：開啟本機 `file:///.../outputs/nav_chart.html` 被瀏覽器 URL 安全政策明確拒絕，因只允許 HTTP／HTTPS 協定。拒絕後未以替代路徑繞過，沒有待執行或結果不確定的瀏覽器操作。

## 本機交付與重現

優先閱讀 `REPORT.zh-TW.md`。資產曲線見 `nav_chart.html`，數值為 `metrics.csv`、`trade_ledger.csv`、`daily_nav.csv`、`signals.csv`。來源／重算／時點證據見 `source_manifest.json`、`forecast_lineage.csv`、`forecast_rebuild_verification.json`、`valuation_reconciliation.json`、`temporal_audit.csv`、`independent_verification.json`。原始研究資料不應上傳。

安全 source-only 交付位於上一層 `source_only/`：runner、config、獨立 verifier 與報告 builder。沒有修改 canonical tracked source。確切命令見該目錄 README；不需網路、API key、付費模型或 Docker。
"""
(out/"REPORT.zh-TW.md").write_text(report)

curve = read("daily_nav.csv")
colors = {"NaiveDCFPolicy":"#2563eb", "FixedAllocationPolicy":"#059669", "BuyAndHoldPolicy":"#d97706"}
w,h=1060,500
left,right,top,bottom=90,30,32,65
dates=[r["date"] for r in curve if r["strategy"]=="NaiveDCFPolicy" and r["variant"]=="net"]
def x(i): return left+i/(len(dates)-1)*(w-left-right)
def y(value): return top+(math.log(1200000)-math.log(value))/(math.log(1200000)-math.log(50000))*(h-top-bottom)
svg=[]
for val in (50000,100000,200000,500000,1000000):
    yy=y(val)
    svg.append(f'<line x1="{left}" x2="{w-right}" y1="{yy}" y2="{yy}" stroke="#e2e8f0"/><text x="{left-12}" y="{yy+5}" text-anchor="end" fill="#475569">{val/1000:g}k</text>')
for year in ("2022","2023","2024","2025"):
    i=next(j for j,d in enumerate(dates) if d.startswith(year))
    xx=x(i)
    svg.append(f'<text x="{xx}" y="{h-30}" text-anchor="middle" fill="#475569">{year}</text>')
for key in names:
    points=[r for r in curve if r["strategy"]==key and r["variant"]=="net"]
    coords=' '.join(f'{x(i):.2f},{y(float(r["nav_usd"])):.2f}' for i,r in enumerate(points))
    svg.append(f'<polyline id="{key}" points="{coords}" fill="none" stroke="{colors[key]}" stroke-width="2.6"/>')
legend=''.join(f'<label><input type="checkbox" checked data-line="{key}"/> <span style="color:{colors[key]}">{html.escape(names[key])}</span></label>' for key in names)
chart=f'''<!doctype html><html lang="zh-Hant"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>NVDA 回顧性診斷資產曲線</title><style>body{{font:17px system-ui,sans-serif;max-width:1120px;margin:35px auto;padding:0 20px;color:#0f172a;background:#f8fafc}}h1{{font-size:27px}}p{{line-height:1.65}}.panel{{background:white;border:1px solid #e2e8f0;border-radius:14px;padding:20px}}label{{display:inline-block;margin:0 20px 12px 0}}svg{{width:100%;height:auto}}small{{color:#475569}}</style><h1>NVDA 真實資料：回顧性診斷</h1><p>2022-08-26～2025-08-29，755 交易日，初始 US$100,000。<b>事後重建模型，不能視為真正樣本外績效。</b></p><div class="panel">{legend}<svg viewBox="0 0 {w} {h}" role="img" aria-label="三個策略扣除成本後的每日資產曲線，縱軸為美元對數尺度"><rect width="{w}" height="{h}" fill="white"/>{''.join(svg)}<text x="{left}" y="18" fill="#475569">NAV USD（對數尺度）</text></svg></div><p>純 DCF +24.29%；固定 40% 股票 +198.08%；買入持有 +874.44%。扣 5 bps 手續費及 5 bps 滑價。現金固定年有效 4%，不計股息／稅。勾選圖例可切換曲線。</p><small>資料僅讀取本機輸出；此頁無外部資源、追蹤或網路請求。完整條件與證據見 REPORT.zh-TW.md。</small><script>document.querySelectorAll('input[data-line]').forEach(el=>el.addEventListener('change',()=>{{document.getElementById(el.dataset.line).style.display=el.checked?'':'none'}}));</script></html>'''
(out/"nav_chart.html").write_text(chart)
print(out/"REPORT.zh-TW.md")
print(out/"nav_chart.html")
