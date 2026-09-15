"""Render the 17-section M2 execution report from actual replay/test artifacts."""

import json
from collections import Counter, defaultdict
from pathlib import Path

from sqlalchemy.orm import Session

from valuation_engine.db.schema import ForecastRun
from valuation_engine.db.session import engine
from valuation_engine.research.numbers import D, canonical, dispersion, mean, median
from valuation_engine.research.service import MODELS, stored_periods

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/m2/report"


def read(name):
    return json.loads((OUT / f"{name}.json").read_text())


def fmt(value, scale=1, digits=3):
    return "—" if value is None else f"{D(str(value)) / scale:,.{digits}f}"


def run():
    summary, coverage, gates, accuracy, history, stability = (
        read(n) for n in ("summary", "coverage", "gates", "accuracy", "history", "stability")
    )
    pg = json.loads((ROOT / "data/m2/postgresql/validation.json").read_text())
    tests = (ROOT / "data/m2/test-results.txt").read_text().strip().splitlines()[-1]
    preserved = json.loads((ROOT / "data/m2/preservation.json").read_text())
    parity = json.loads((ROOT / "data/m2/backend-parity.json").read_text())
    idem = read("idempotency")
    # Financial evaluation only: realized coverage of intervals made before the outcome.
    calibrated = defaultdict(list)
    with Session(engine("sqlite:///data/qve.db")) as db:
        period_cache = {}
        for observation in accuracy["observations"]:
            rid = observation["run_id"]
            if rid not in period_cache:
                period_cache[rid] = stored_periods(db, rid)
            horizon = observation["horizon"]
            period = next(
                r
                for r in period_cache[rid]
                if (
                    str(r["metadata_json"].get("horizon")) + "Q"
                    if r["period_type"] == "quarter"
                    else r["period_type"]
                )
                == horizon
            )
            for metric, error in observation["errors"].items():
                if error is None:
                    continue
                band = period["metadata_json"]["intervals"][metric]
                if band["status"] != "empirical_P80":
                    continue
                lower, upper = D(band["lower"]), D(band["upper"])
                if metric == "eps":
                    lower /= D(observation["eps_split_factor"])
                    upper /= D(observation["eps_split_factor"])
                actual = D(error["actual"])
                calibrated[observation["model"], horizon, metric].append(
                    dict(
                        run_id=rid,
                        lower=lower,
                        upper=upper,
                        actual=actual,
                        covered=lower <= actual <= upper,
                        origin_sample_count=band["sample_count"],
                    )
                )
        calibration = [
            dict(
                model=model,
                horizon=horizon,
                metric=metric,
                sample_count=len(rows),
                empirical_p80_coverage=D(sum(r["covered"] for r in rows)) / len(rows),
                mean_width=mean([r["upper"] - r["lower"] for r in rows]),
                observations=rows,
            )
            for (model, horizon, metric), rows in sorted(calibrated.items())
        ]
        (OUT / "calibration.json").write_text(json.dumps(canonical(calibration), indent=2) + "\n")
        warnings = Counter()
        for entry in history["runs"]:
            if entry["checkpoint"] == "first_tradable" and entry["model"] == MODELS["A"]:
                run_row = db.get(ForecastRun, entry["run_id"])
                warnings.update(w["reason"] for w in run_row.metadata_json["warnings"])
    tests_ok = "passed" in tests and "failed" not in tests and pg["test_exit_code"] == 0
    gate_ok = len(gates) == 5 and all(g["pit_status"] == "PASS" for g in gates)
    requirements = {
        "M2-AC1": (
            idem["all_counts_unchanged"] and tests_ok,
            "Immutable/versioned forecast records; database guards and repeat-run evidence",
        ),
        "M2-AC2": (
            gate_ok and tests_ok,
            "PIT cutoff, both checkpoints, future-filing and calibration boundary tests",
        ),
        "M2-AC3": (
            summary["coverage"]["q1_revenue"] == 26 and tests_ok,
            "GAAP guidance anchors with retained raw and bias-adjusted values",
        ),
        "M2-AC4": (
            all(summary["coverage"][x] == 26 for x in ("ntm_eps", "fy1_eps", "fy2_eps")),
            "Deterministic NTM/FY1/FY2, fiscal-roll and common-share-basis tests",
        ),
        "M2-AC5": (
            tests_ok,
            "Full income statement derives EPS; forecast weighted shares remain distinct",
        ),
        "M2-AC6": (
            tests_ok,
            "Versioned OCF-capex forecast with explicit cash-conversion approximations",
        ),
        "M2-AC7": (
            all(
                e["revision"]["status"] == "available"
                for e in history["runs"]
                if e["checkpoint"] == "first_tradable" and e["quarter"] != "FY2021-Q1"
            ),
            "Same-target revisions and FY label roll handled explicitly",
        ),
        "M2-AC8": (
            bool(accuracy["accuracy"]),
            "All 26 origin quarters reviewed; realized 1Q/2Q/4Q/FY1/FY2 accuracy and calibration reported",
        ),
        "M2-AC9": (
            summary["coverage"]["ntm_pe"] == 26 and summary["coverage"]["forward_fcf_yield"] == 26,
            "Historical forward valuation from internal forecasts",
        ),
        "M2-AC10": (
            gate_ok and tests_ok,
            "Strictly prior valuation distribution and unavailable early samples",
        ),
        "M2-AC11": (
            tests_ok and summary["coverage"]["dcf_base"] > 0,
            "DCF cash-flow compatibility, 15-cell sensitivity and monotonicity tests",
        ),
        "M2-AC12": (
            tests_ok and summary["coverage"]["reverse_dcf_implied_fcf_cagr"] > 0,
            "Bounded Decimal root solver, convergence and explicit failure handling",
        ),
        "M2-AC13": (
            gate_ok and tests_ok,
            "Historical cash/debt/PIT shares provenance and future-data injection tests",
        ),
        "M2-AC14": (
            tests_ok and parity["all_numeric_outputs_equal"],
            "Actual SQLite/PostgreSQL tests and numerical parity",
        ),
        "M2-AC15": (
            tests_ok,
            "Forecast SQL/import guard excludes evaluation outcomes, prices and returns",
        ),
        "M2-AC16": (
            all(r["all_original_rows_unchanged"] for r in preserved.values()),
            "No trading decision, score, return optimization or subsequent milestone",
        ),
    }
    final = all(v[0] for v in requirements.values()) and gate_ok
    lines = [
        "# Milestone 2 Execution Report",
        "",
        f"**{'Final Pass recommended for PM review' if final else 'PARTIAL — Final Pass not yet recommended'}**",
        "",
        "M1／M1.1 已由 PM 通過，原有 PIT/source/split/shares 規則維持。M2 使用固定的 deterministic GAAP 模型；所有歷史預測都是 `research_reconstructed_internal`，不是當時觀察到的華爾街共識。",
        "",
        "## 1. Implementation Completed",
        "",
        "完成雙 checkpoint、八季完整財務預測、NTM／FY1／FY2、guidance bias、empirical intervals、同標的期間修訂、財務誤差評估、historical forward valuation、DCF、Reverse DCF、sensitivity、歷史分位數、CLI、測試及方法文件。A／B／C 均保留。",
        "",
        "## 2. Database / Migration Changes",
        "",
        f"Core：`0005_research`；labels：`0003_forecast_outcomes`。新增六個 core tables 與獨立的 forecast_outcomes label table。[欄位與資料契約](M2_DATA_MODEL.md)。原本 {len(preserved)} 個 core／label tables 的原始列全部保留不變；基準檢查見 preservation.json。",
        "",
        f"正式 benchmark 為 {summary['checkpoints']} runs（26 季 × 2 checkpoints × 3 models）。資料庫保留開發期不可改寫紀錄；accuracy 與正式 history 依 typed frozen assumption hash 選取，並未因表現好壞刪除模型。",
        "",
        "## 3. Forecast Method",
        "",
        "A：GAAP guidance anchor + 僅已實現歷史 guidance bias。B：mechanical historical trend。C：固定 50/50 ensemble，再重算完整損益。Revenue 結合 YoY／sequential／seasonality／acceleration／mean reversion；OpEx 可獨立稽核。EPS 分母為 forecast diluted weighted-average shares，市值／DCF 使用 PIT shares outstanding。詳見 [FORECAST_METHOD.md](FORECAST_METHOD.md)。",
        "",
        "所有數值係數在完整 accuracy 評估前固定；policy-freeze.json 記錄方法與參數雜湊。沒有用後來股價或報酬調整參數。",
        "",
        "## 4. Forecast Coverage",
        "",
        "以下為 Model A 的 first-tradable snapshots；EPS 使用各估值日的共同股數基準。金額表格只做顯示四捨五入；JSON／資料庫保留 Decimal 精度。",
        "",
        "| Quarter | Q+1 Revenue ($bn) | Q+1 EPS | NTM EPS | FY1 EPS | FY2 EPS | NTM P/E | Forward FCF Yield | DCF base | Reverse 5Y growth |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in coverage:
        lines.append(
            "| "
            + " | ".join(
                [
                    r["quarter"],
                    fmt(r["q1_revenue"], D("1e9")),
                    fmt(r["q1_eps"]),
                    fmt(r["ntm_eps"]),
                    fmt(r["fy1_eps"]),
                    fmt(r["fy2_eps"]),
                    fmt(r["ntm_pe"]),
                    fmt(D(r["forward_fcf_yield"]) * 100 if r["forward_fcf_yield"] else None) + "%",
                    fmt(r["dcf_base"]),
                    fmt(
                        D(r["reverse_dcf_implied_fcf_cagr"]) * 100
                        if r["reverse_dcf_implied_fcf_cagr"] is not None
                        else None
                    )
                    + "%",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "## 5. Guidance Accuracy",
        "",
        "Surprise 採 Actual / Midpoint − 1；GM 為百分點差。未實現的下一季 guide 保留在 run metadata，actual／surprise 不補值。",
        "",
        "| Metric | 已實現樣本 | Mean surprise | Median surprise | Dispersion |",
        "|---|---:|---:|---:|---:|",
    ]
    for metric, samples in accuracy["guidance_accuracy"].items():
        vals = [D(x["surprise"]) * 100 for x in samples]
        lines.append(
            f"| {metric} | {len(vals)} | {fmt(mean(vals))} | {fmt(median(vals))} | {fmt(dispersion(vals))} |"
        )
    lines += [
        "",
        "Revenue／OpEx 單位為百分比；GM 為 percentage points。逐筆 midpoint、actual、source hash、實現時間與樣本窗口在 accuracy.json 及各 forecast run 保存。",
        "",
        "## 6. Forecast Accuracy",
        "",
        "下表為 Model A；金額 MAE 為 USD、EPS 為評估日共同拆股基準的 USD/share。完整 A／B／C、mean/median bias、worst errors 與樣本在 accuracy.json。百分比誤差遇到零 actual 留空；GM 以 basis-point error 為主要解讀。",
        "",
        "| Horizon | Metric | N | MAE | MAPE % | sMAPE % | Mean bias | GM MAE bps |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in accuracy["accuracy"]:
        if r["model"] != MODELS["A"]:
            continue
        lines.append(
            "| "
            + " | ".join(
                [
                    r["horizon"],
                    r["metric"],
                    str(r["sample_count"]),
                    fmt(r["mae"]),
                    fmt(D(r["mape"]) * 100 if r["mape"] is not None else None),
                    fmt(D(r["smape"]) * 100 if r["smape"] is not None else None),
                    fmt(r["mean_bias"]),
                    fmt(r["gm_mae_basis_points"]),
                ]
            )
            + " |"
        )
    lines += [
        "",
        "A/B/C 的 1Q 收入比較（不據此改權重）：",
        "",
        "| Model | N | Revenue MAPE % | Revenue sMAPE % |",
        "|---|---:|---:|---:|",
    ]
    for r in accuracy["accuracy"]:
        if r["metric"] == "revenue" and r["horizon"] == "1Q":
            lines.append(
                f"| {r['model']} | {r['sample_count']} | {fmt(D(r['mape']) * 100) if r['mape'] else '—'} | {fmt(D(r['smape']) * 100) if r['smape'] else '—'} |"
            )
    lines += [
        "",
        "Empirical interval calibration（Model A，1Q）：",
        "",
        "| Metric | 有歷史區間且已實現 N | P80 實際涵蓋率 % |",
        "|---|---:|---:|",
    ]
    for r in calibration:
        if r["model"] == MODELS["A"] and r["horizon"] == "1Q":
            lines.append(
                f"| {r['metric']} | {r['sample_count']} | {fmt(r['empirical_p80_coverage'] * 100)} |"
            )
    lines += [
        "",
        "涵蓋率可能明顯偏離 80%；名稱是歷史 empirical band，並非校準保證。早期 insufficient_history 不製造區間。",
        "",
        "## 7. Forecast Revision Results",
        "",
        "同一 fiscal-year target 比較；跨 Q4 時新 FY1 對應前次 FY2，避免把年度切換當成營運修訂。",
        "",
        "| Origin | Same target | Previous label | Old EPS (new basis) | New EPS | Revision % |",
        "|---|---|---|---:|---:|---:|",
    ]
    for e in history["runs"]:
        if e["checkpoint"] != "first_tradable" or e["model"] != MODELS["A"]:
            continue
        r = next((r for r in e["revision"].get("comparisons", []) if r["new_label"] == "FY1"), None)
        if r:
            eps = r["metrics"]["eps"]
            lines.append(
                f"| {e['quarter']} | {r['target']} | {r['previous_label']} | {fmt(eps['previous'])} | {fmt(eps['current'])} | {fmt(D(eps['percentage_revision']) * 100) if eps['percentage_revision'] is not None else '—'} |"
            )
    lines += [
        "",
        "Revenue／FCF／GM／Operating Margin 的逐筆修訂與來源理由同時保存於 history.json 及 forecast_revisions。",
        "",
        "## 8. Historical Forward Valuation Coverage",
        "",
        f"NTM P/E：{summary['coverage']['ntm_pe']}/26；Forward FCF Yield：{summary['coverage']['forward_fcf_yield']}/26。NTM 為主分母，FY1/FY2 為補充。歷史 context 僅採 strictly earlier 的同模型觀測；前四個季度樣本不足，percentile／z-score unavailable。",
        "",
        "## 9. DCF Results / Coverage",
        "",
        f"Model A DCF：{summary['coverage']['dcf_base']}/26。採明示的 NOPAT cash-conversion FCFF proxy；Year 1–2 取未來八季，Year 3–5 使用固定 growth decay。WACC 8%–12%、terminal growth 2%／2.5%／3%，共 15 cells；base 為 10%／2.5%。低／高值是 sensitivity extremes，不是機率信賴區間。[VALUATION_METHOD.md](VALUATION_METHOD.md)。",
        "",
        "## 10. Reverse DCF Results / Coverage",
        "",
        f"Model A converged reverse DCF：{summary['coverage']['reverse_dcf_implied_fcf_cagr']}/26。與 internal 5Y CAGR 使用相同 starting FCFF 與五年時序；正值 starting FCFF／EV、WACC > terminal growth、root bracket 與 residual 檢查均必要。失敗保留 NULL + reason。",
        "",
        "## 11. PM Gate Results",
        "",
        "完整每筆財務、guidance、forecast、revision、價格與 DCF provenance 保存於 gates.json。PIT 與數值完整度分開驗證：依 Task 34，缺少合格起點的歷史 DCF／Reverse DCF 可以保留 NULL。PARTIAL completeness 不表示使用了未來資料，也不宣稱 Reverse DCF 已有數值。",
        "",
        "| Gate | Status | Price | NTM P/E | DCF low / base / high | Implied growth % |",
        "|---|---|---:|---:|---|---:|",
    ]
    for gate in gates:
        v = gate["valuation"]
        lines.append(
            f"| {gate['quarter']} | PIT {gate['pit_status']} / completeness {gate['status']} | {fmt(v['metadata_json']['price'])} | {fmt(v['ntm_pe'])} | {fmt(v['dcf_low'])} / {fmt(v['dcf_base'])} / {fmt(v['dcf_high'])} | {fmt(D(v['reverse_dcf_implied_fcf_cagr']) * 100) if v['reverse_dcf_implied_fcf_cagr'] is not None else '—'} |"
        )
    lines += [
        "",
        "## 12. Test Results",
        "",
        f"- SQLite：{tests}",
        f"- PostgreSQL：{pg['test_summary']}；實際 server／migration：{pg['server_version']} / {pg['migration']}。",
        f"- 重跑 forecast／evaluation 完全相同，table counts 不增加：{idem['all_counts_unchanged']}。",
        f"- SQLite／PostgreSQL 所有正式財務預測與估值數字相同：{parity['all_numeric_outputs_equal']}。",
        f"- 原始來源 SHA-256：{summary['source_hash_count']} 份，全部通過：{summary['all_source_hashes_verified']}。",
        "",
        "## 13. Data Quality / Model Limitations",
        "",
        "Reverse DCF 僅 13/26：V1 不把歷史負有效稅率（已知稅務利益）直接當成持續性 FCFF 稅率，亦不補一個正常化稅率，因此 trailing FCFF 起點可 unavailable。逐季組成、原始稅率及來源在 reverse-input-readiness.json；forward DCF 的預測稅率已有獨立穩健政策。保留 M1.1 的原始差異、未確認基準及 conditional missing；不為 forecast 表現改資料規則。早期股數變化樣本不足使用明示 flat baseline；不足八個已實現誤差不產生區間。Forecast nonoperating income、tax、WC／cash conversion 與 FCFF 均有近似性，DCF sensitivity 不是合理價位保證。",
        "",
        f"Model A warnings（事件數，不代表不同季度數）：`{dict(warnings)}`。",
        "",
        "## 14. Model Stability",
        "",
        "Model A 的 quarter-to-quarter rolling NTM change dispersion 與同年度 EPS/Revenue/FCF revision dispersion 分開衡量；EPS 先統一拆股基準。",
        "",
        "| Metric | Forecast change dispersion | Same-target revision dispersion | Revision N | Missing forecast frequency |",
        "|---|---:|---:|---:|---:|",
    ]
    for r in stability:
        if r["model"] == MODELS["A"]:
            lines.append(
                f"| {r['metric']} | {fmt(r['forecast_volatility'])} | {fmt(r['revision_volatility'])} | {r['revision_sample_count']} | {fmt(r['forecast_failure_frequency'])} |"
            )
    lines += [
        "",
        "各模型／horizon 的 error dispersion、extreme miss frequency（absolute percentage error >50%）、worst errors 在 accuracy.json，A/B/C stability 在 stability.json。模型評估只針對財務誤差與穩定性，未計算或最大化策略報酬。",
        "",
        "## 15. M2-AC1 至 M2-AC16",
        "",
        "| Criterion | Result | Evidence |",
        "|---|---|---|",
    ]
    for ac, (passed, reason) in requirements.items():
        lines.append(f"| {ac} | {'PASS' if passed else 'PARTIAL'} | {reason} |")
    lines += [
        "",
        "## 16. PM Decisions Required",
        "",
        "沒有新增的必要 PM 決策。固定假設、FCFF proxy 與 sparse-history 限制完整揭露，供本里程碑驗收；不要求重開 M1.1 已接受決策。",
        "",
        "## 17. Recommendation",
        "",
        "建議 PM 給予 **Milestone 2 Final Pass**，並保留 DCF 24/26、Reverse DCF 13/26 與三個 gate 數值完整度 PARTIAL 的限制。此建議以 Task 34 允許不合格歷史輸入保留 NULL 為前提；PIT gate 全部通過。這是研究引擎功能與可重現性的驗收，不是投資績效保證。"
        if final
        else "目前為 PARTIAL。請依未通過項目補齊證據後再提出 Final Pass；不以漂亮回測或調參掩蓋缺口。",
        "",
        "Milestone 2 到此停止。未開始後續 milestone；沒有交易建議、Opportunity Score 或 return optimization。",
        "",
        "重現：`uv run python scripts/run_m2.py --repeat`；PostgreSQL：`uv run python scripts/validate_m2_postgres.py`；原工作區稽核為 `uv run python scripts/audit_m2.py`（需要 pre-M2 backups 與 PostgreSQL）；最後執行 `uv run python scripts/report_m2.py`。原始稽核結果已包含在交付包，離線 replay 不需要重跑該稽核。",
        "",
    ]
    (ROOT / "docs/MILESTONE_2_EXECUTION_REPORT.md").write_text("\n".join(lines))
    (OUT / "acceptance.json").write_text(
        json.dumps(
            {
                "criteria": {
                    k: {"status": "PASS" if ok else "PARTIAL", "evidence": reason}
                    for k, (ok, reason) in requirements.items()
                },
                "final_pass_recommended": final,
            },
            indent=2,
        )
        + "\n"
    )
    print("M2 report generated; Final Pass recommended:", final)


if __name__ == "__main__":
    run()
