"""Offline review revisions; frozen model runs and admission policy remain immutable.

This is an inspectable editorial candidate, not another provider run or a promotion.
Mixed observations and neutral context are not presented as contrary observations.
"""

import copy
import hashlib
import html
import json
import re
import shutil
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

VERSION = "NVDAReviewRevisionV1"
PACKET_HASH = "4664e3639dd37b3bef66eda2b52b3891ce9ffab36bdeffec67a0ad965cad7636"
CONTEXT_HASH = "7dbc20895ac74fa430e2303cf4bdf8e153c4a54492959095d79f9f0aee981a8d"
ROLE_LABELS = {
    "support": "支持目前判斷",
    "opposition": "反對目前判斷",
    "mixed": "混合訊號（同時含有不同方向）",
    "context": "背景／管理層預期（未單獨證明方向）",
}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def evidence_accounting(feature, evidence):
    """Keep the original unique-span contract; expose other counts separately."""
    keys = feature["evidence_keys"]
    if len(set(keys)) != len(keys) or any(key not in evidence for key in keys):
        raise ValueError("Feature requires distinct, admitted evidence keys")
    citations = feature["supporting_evidence"] + feature["contradicting_evidence"]
    if set(citations) != set(keys):
        raise ValueError("Citation roles and evidence keys disagree")
    groups: dict[str, list[str]] = {}
    for key in keys:
        groups.setdefault(evidence[key]["span_hash"], []).append(key)
    if feature["evidence_count"] != len(groups):
        raise ValueError("Original unique quotation count is inconsistent")
    return {
        "raw_citation_occurrences": len(citations),
        "admitted_evidence_keys": len(keys),
        "unique_quotations": len(groups),
        "original_evidence_count": feature["evidence_count"],
        "duplicate_quote_groups": [v for v in groups.values() if len(v) > 1],
        "count_contract": "unique span_hash; repeated quotes are not independent evidence",
    }


def classify_roles(feature, evidence):
    roles: dict[str, list[str]] = {key: [] for key in ROLE_LABELS}
    sign = feature["feature_value"]
    expected = "positive" if sign > 0 else "negative" if sign < 0 else None
    for key in feature["evidence_keys"]:
        item = evidence[key]
        if item["topic"] != feature["feature_name"]:
            raise ValueError("Cross-topic evidence cannot enter a revision")
        implication = item["implication"]
        if implication not in ("positive", "negative", "mixed", "neutral"):
            raise ValueError("Unknown implication")
        role = (
            "mixed"
            if implication == "mixed"
            else "context"
            if implication == "neutral" or expected is None
            else "support"
            if implication == expected
            else "opposition"
        )
        roles[role].append(key)
    return roles


def revise_sample(sample, source_map, cutoff):
    result = copy.deepcopy(sample)
    evidence = {e["key"]: e for e in sample["evidence"]}
    if len(evidence) != len(sample["evidence"]):
        raise ValueError("Duplicate evidence key")
    blocks = {b["block_id"]: b for b in source_map["blocks"]}
    documents = {d["source_hash"]: d for d in source_map["documents"]}
    current_sources = {
        key
        for key, doc in documents.items()
        if doc["source_url"].endswith("second-quarter-fiscal-2023")
    }
    if not current_sources:
        raise ValueError("Current quarter source missing")
    for item in result["evidence"]:
        block = blocks.get(item["block_id"])
        if (
            not block
            or item["span"] not in block["text"]
            or hashlib.sha256(item["span"].encode()).hexdigest() != item["span_hash"]
            or block["source_hash"] != item["source_hash"]
            or datetime.fromisoformat(block["available_at"]) > cutoff
        ):
            raise ValueError("Evidence source, quotation or cutoff mismatch")
        item["full_source_paragraph"] = block["text"]
        item["source_url"] = documents[item["source_hash"]]["source_url"]
        item["period_context"] = (
            "CURRENT_RELEASE"
            if item["source_hash"] in current_sources
            else "PRIOR_DOCUMENT_CONTEXT"
        )
        item["quote_completeness"] = (
            "TRUNCATED_CLAUSE_REVIEW_REQUIRED"
            if re.search(r"\b(for|of|and|to|the|may|could)$", item["span"].strip(), re.I)
            else "READ_FULL_PARAGRAPH"
        )
    evidence = {e["key"]: e for e in result["evidence"]}
    changes = []
    for feature in result["features"]:
        feature["evidence_accounting"] = evidence_accounting(feature, evidence)
        roles = classify_roles(feature, evidence)
        before = {
            "support": feature.pop("supporting_evidence"),
            "opposition": feature.pop("contradicting_evidence"),
        }
        feature["original_roles"] = before
        feature["review_roles"] = roles
        feature["original_feature_value"] = feature.pop("feature_value")
        feature["original_wrapper_confidence"] = feature.pop("confidence")
        # Editorial reclassification is not calibration of a new signed signal.
        feature["feature_value"] = None
        feature["confidence"] = None
        feature["numeric_signal_status"] = "WITHHELD_PENDING_SEMANTIC_REVIEW"
        feature["current_release_evidence_count"] = sum(
            evidence[k]["period_context"] == "CURRENT_RELEASE" for k in feature["evidence_keys"]
        )
        feature["assessment_scope"] = (
            "MIXED_PERIODS_REVIEW_REQUIRED"
            if feature["current_release_evidence_count"]
            else "HISTORICAL_CONTEXT_ONLY"
        )
        if feature["feature_name"] in {"inference_demand", "training_demand"}:
            feature["revision_note"] = (
                "來源合併訓練與推論需求，且屬較早期間；不能據此分別發布當季方向值或信心分數。"
            )
        elif feature["feature_name"] == "guidance_visibility":
            feature["revision_note"] = (
                "發布指引本身只是比較基準，不代表預測可靠。應連同本季實際與前次指引落差閱讀下方 Quant 對照。"
            )
        elif feature["feature_name"] == "demand_momentum":
            feature["revision_note"] = (
                "年增與季減同時存在，因此整句屬混合訊號。前期成長只作歷史背景；本季分部變化見修訂補充。"
            )
        elif feature["feature_name"] == "margin_outlook":
            feature["revision_note"] = (
                "未來指引須標示比較基準；不能把管理層預期當作已實現結果，或用前期費用直接解釋當季壓縮。"
            )
        else:
            feature["revision_note"] = "原模型敘述保留供複核；來源時點、混合訊號及背景證據另列。"
        changes.append(
            {
                "feature": feature["feature_name"],
                "original_roles": before,
                "revised_roles": roles,
                "original_confidence": feature["original_wrapper_confidence"],
                "revised_confidence": None,
                "reason": feature["numeric_signal_status"],
            }
        )
    feature_names = {f["feature_name"] for f in result["features"]}
    for section in result["section_drafts"]:
        section["status"] = "ORIGINAL_UNREVIEWED_DRAFT"
        section["unassessed_topics"] = sorted(
            {
                evidence[k]["topic"]
                for k in section["evidence"]
                if k in evidence and evidence[k]["topic"] not in feature_names
            }
        )
    result.update(
        revision_version=VERSION,
        revision_kind="OFFLINE_EDITORIAL_CANDIDATE",
        quality_verdict="UNSCORED",
        promotion_ready=False,
        downstream_use="REVIEW_ONLY_NO_FINANCIAL_VALUATION_REGIME_WRITES",
        original_model_not_rerun=True,
        changes=changes,
        rejection_accounting={
            "raw_rejected_claims": len(sample["rejections"]),
            "included_in_admitted_counts": False,
        },
    )
    return result


def quant_comparison(context, source_map):
    """Read the frozen Quant record and exact outlook; never produce new forecasts."""
    cutoff = datetime.fromisoformat(context["information_cutoff"])
    samples = context["quant_guidance_accuracy"]["revenue"]["samples"]
    rows = [s for s in samples if s["target"] == "FY2023-Q2"]
    if len(rows) != 1:
        raise ValueError("Exactly one same-quarter actual/guidance comparison required")
    row = rows[0]
    if any(
        datetime.fromisoformat(t) > cutoff
        for t in (
            row["actual_available_at"],
            row["guidance"]["available_at"],
        )
    ):
        raise ValueError("Quant comparison exceeds cutoff")
    outlook = [
        b
        for b in source_map["blocks"]
        if b["source_document_id"] == 10
        and "Revenue is expected to be $5.90 billion, plus or minus 2%." in b["text"]
    ]
    if len(outlook) != 1 or datetime.fromisoformat(outlook[0]["available_at"]) > cutoff:
        raise ValueError("Frozen next-quarter outlook unavailable")
    match = re.search(
        r"Revenue is expected to be \$([\d.]+) billion, plus or minus (\d+)%", outlook[0]["text"]
    )
    assert match is not None
    midpoint = Decimal(match[1]) * Decimal(10**9)
    width = Decimal(match[2]) / 100
    forecast = next(f for f in context["quant_forecasts"] if f["period_type"] == "quarter")
    actual, previous = Decimal(row["actual"]), Decimal(row["guidance"]["midpoint"])
    predicted, upper = Decimal(forecast["revenue"]), midpoint * (1 + width)
    return {
        "status": "READ_ONLY_QUANT_COMPARISON",
        "currency": "USD",
        "actual_quarter": row["target"],
        "forecast_target": "FY2023-Q3",
        "actual_revenue": str(actual),
        "prior_guidance_midpoint": str(previous),
        "actual_vs_prior_guidance": str(actual / previous - 1),
        "forecast_id": forecast["id"],
        "forecast_revenue": str(predicted),
        "next_guidance_midpoint": str(midpoint),
        "next_guidance_low": str(midpoint * (1 - width)),
        "next_guidance_high": str(upper),
        "forecast_vs_guidance_high": str(predicted / upper - 1),
        "historical_guidance_adjustment": context["quant_guidance_accuracy"]["revenue"][
            "adjustment"
        ],
        "guidance_source_block": outlook[0]["block_id"],
        "actual_fact_ids": row["actual_fact_ids"],
        "interpretation_zh": "本季實際低於前次指引，而原模型下季預測高於新指引上緣。歷史超標假設需要重新檢視；本對照不直接改寫預測或估值。",
    }


def render(sample, comparison, source_map):
    esc = html.escape
    lines = [
        "<!doctype html><html lang='zh-Hant'><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width,initial-scale=1'>",
        "<style>body{max-width:1040px;margin:40px auto;padding:0 24px;font:17px/1.7 system-ui;color:#172b3a}h1,h2,h3{line-height:1.4}section{border-top:1px solid #ccd5dc;padding:16px 0}blockquote{margin:12px 0;padding:14px;background:#f2f6f8;overflow-wrap:anywhere}small{color:#52626d}details{margin:12px 0}a{color:#166294}.notice{padding:18px;background:#fff1ce}table{border-collapse:collapse;width:100%}td,th{border:1px solid #dce3e8;padding:8px;text-align:left}</style>",
        f"<title>候選 {esc(sample['sample'])} 修訂版｜NVIDIA FY2023-Q2</title>",
        f"<h1>候選 {esc(sample['sample'])}：NVIDIA FY2023-Q2 修訂版</h1>",
        "<p class='notice'>離線修訂候選，尚待複核。原模型沒有重跑；歷史單季結果不套用到目前 FY2027-Q2 工作台。原分數與模型方向值保留備查，修訂版不發布數值訊號。</p>",
        "<h2>先看修訂後的研究重點</h2>",
        "<p>本季需求同時有成長與收縮，必須分開看年增、季增及不同業務。Data Center 的年增不能代替季增，也不能單靠管理層對 AI 的信心支持高於原模型的營收。</p>",
        "<p>前季營收指引只是當時的預期。現在已有本季實際結果，應以兩者的落差檢視能見度；未來指引仍不是已實現收入。</p>",
        "<h3>已保存 Quant 數據對照</h3><table><tr><th>項目</th><th>數值</th></tr>",
    ]
    for label, key in [
        ("本季實際營收（美元）", "actual_revenue"),
        ("前次對本季的指引（美元）", "prior_guidance_midpoint"),
        ("原模型下季營收（美元）", "forecast_revenue"),
        ("管理層下季指引上緣（美元）", "next_guidance_high"),
    ]:
        lines.append(f"<tr><td>{label}</td><td>{Decimal(comparison[key]):,.2f}</td></tr>")
    lines += [
        "</table>",
        f"<p>本季實際較前次指引 {Decimal(comparison['actual_vs_prior_guidance']):.2%}；原模型高於下季指引上緣 {Decimal(comparison['forecast_vs_guidance_high']):.2%}。</p>",
        "<p>以上為保存的後端資料比較。可支持『重新檢視歷史超標假設』的研究問題，尚不足以自動選定新的下修幅度。</p>",
        "<h3>本季分部原文與反向證據</h3>",
    ]
    segments = {
        "10:413e2bbc07bd22a38e25": "Gaming",
        "10:000b3506e8120f1b78e8": "Professional Visualization",
        "10:4fd87ec6cacb0d235124": "Data Center",
        "10:f4ef3e20f0eb41868ed3": "Automotive",
    }
    for block in source_map["blocks"]:
        if block["block_id"] in segments:
            lines.append(
                f"<p><strong>{segments[block['block_id']]}</strong>（本季官方公告；離線補充，未冒充原模型抽取）</p><blockquote>{esc(block['text'])}</blockquote>"
            )
    lines += [
        "<p>毛利展望必須分別比較本季實際與前次指引；前期存貨費用不能直接歸因為本季壓縮。若未來去庫存或供應承諾費用持續，復甦敘述須重新檢視。現金流差異仍缺完整當季因果證據，保留未解。</p>",
        "<h2>逐項研究判斷與修訂紀錄</h2>",
    ]
    evidence = {e["key"]: e for e in sample["evidence"]}
    for feature in sample["features"]:
        counts = feature["evidence_accounting"]
        lines += [
            f"<section><h3>{esc(feature['feature_name'])}</h3>",
            f"<p>{esc(feature['revision_note'])}</p>",
            f"<p>引用編號 {counts['admitted_evidence_keys']}；去重引文 {counts['unique_quotations']}；原始引用次數 {counts['raw_citation_occurrences']}。重複引文不算獨立證據。</p>",
            f"<p><small>當季公告引文 {feature['current_release_evidence_count']}；原包裝器分數 {feature['original_wrapper_confidence']}（不是正確機率）；修訂版方向值與分數暫不發布。</small></p>",
            f"<details><summary>保留的原模型敘述</summary><p>{esc(feature['net_assessment'])}</p></details>",
        ]
        for role, label in ROLE_LABELS.items():
            lines.append(
                f"<details><summary>{label}：{len(feature['review_roles'][role])} 筆</summary>"
            )
            for key in feature["review_roles"][role]:
                item = evidence[key]
                period = (
                    "本季公告" if item["period_context"] == "CURRENT_RELEASE" else "前期文件／背景"
                )
                lines += [
                    f"<p><strong>{esc(key)}</strong>｜{period}｜{esc(item['available_at'])}</p>",
                    f"<blockquote>{esc(item['span'])}</blockquote>",
                    f"<details><summary>完整來源段落與出處</summary><blockquote>{esc(item['full_source_paragraph'])}</blockquote><a href='{esc(item['source_url'], quote=True)}'>官方來源</a><p>段落 {esc(item['block_id'])}；來源雜湊 {esc(item['source_hash'])}</p></details>",
                ]
                if item["quote_completeness"] == "TRUNCATED_CLAUSE_REVIEW_REQUIRED":
                    lines.append(
                        "<p>此短引文句尾不完整，須連同完整段落複核；未把補充段落冒充已採納引文。</p>"
                    )
            lines.append("</details>")
        lines.append("</section>")
    lines += [
        "<h2>缺失、拒收與尚待複核</h2>",
        f"<p>主題未評：{esc(', '.join(sample['missing_features']))}。拒收原稿 {len(sample['rejections'])} 筆，與採納證據分開計算。</p>",
        "<p>原段落草稿與挑戰意見仍完整保存在 JSON。提到未評主題的草稿已加上 unassessed_topics；沒有把草稿提升為已核准判斷。</p>",
        "<p>兩份評閱意見均已獲使用者同意採用。第二份已填原件尚待核對；正式品質、獨立人審、重複穩定性與當期適用性尚未完成。財務、估值與 Regime 不受本檔影響。</p></html>",
    ]
    return "\n".join(lines)


def prepare_revision(packet, context_path, out):
    if out.exists() or out.is_symlink():
        raise ValueError("Revision output must be a new directory")
    if out.resolve().is_relative_to(packet.resolve()):
        raise ValueError("Revision must remain outside the original packet")
    reviewers = packet / "reviewers"
    manifest = json.loads((packet / "manifest.json").read_text())
    calculated = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()
    if manifest["packet_hash"] != PACKET_HASH or calculated != PACKET_HASH:
        raise ValueError("Unrecognized frozen review packet")
    if digest(context_path) != CONTEXT_HASH:
        raise ValueError("Unrecognized frozen Quant context")
    before = {str(p.relative_to(packet)): digest(p) for p in packet.rglob("*") if p.is_file()}
    for name, expected in manifest["files"].items():
        path = (reviewers / name).resolve()
        if (
            (reviewers / name).is_symlink()
            or not path.is_relative_to(reviewers.resolve())
            or digest(path) != expected
        ):
            raise ValueError("Frozen packet integrity mismatch")
    context = json.loads(context_path.read_text())
    cutoff = datetime.fromisoformat(context["information_cutoff"])
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="review-revision-", dir=out.parent) as directory:
        staging = Path(directory) / "revision"
        staging.mkdir()
        summaries = {}
        for label in ("X", "Y"):
            sample = json.loads((reviewers / f"{label}.json").read_text())
            if sample["quarter"] != "FY2023-Q2" or sample["promotion_ready"]:
                raise ValueError("Only the unpromoted historical quarter is eligible")
            source_map = json.loads((reviewers / f"sources/{label}-source-map.json").read_text())
            revised = revise_sample(sample, source_map, cutoff)
            comparison = quant_comparison(context, source_map)
            revised["quant_comparison"] = comparison
            write_json(staging / f"{label}.json", revised)
            (staging / f"{label}.html").write_text(render(revised, comparison, source_map))
            summaries[label] = {
                "features": len(revised["features"]),
                "duplicate_quote_features": sum(
                    bool(f["evidence_accounting"]["duplicate_quote_groups"])
                    for f in revised["features"]
                ),
                "reclassified_features": sum(
                    c["original_roles"]["support"] != c["revised_roles"]["support"]
                    or c["original_roles"]["opposition"] != c["revised_roles"]["opposition"]
                    for c in revised["changes"]
                ),
                "withheld_numeric_signals": len(revised["features"]),
            }
        shutil.copytree(reviewers / "sources", staging / "sources")
        shutil.copy2(context_path, staging / "quant-context.json")
        after = {str(p.relative_to(packet)): digest(p) for p in packet.rglob("*") if p.is_file()}
        if before != after:
            raise ValueError("Original review packet changed during revision")
        receipt = {
            "version": VERSION,
            "revision_engine_sha256": digest(Path(__file__)),
            "status": "REVISED_CANDIDATE_AWAITING_REVIEW",
            "original_packet_hash": manifest["packet_hash"],
            "original_files_unchanged": True,
            "context_sha256": digest(context_path),
            "samples": summaries,
            "provider_calls": 0,
            "database_writes": 0,
            "quality_verdict": "UNSCORED",
            "promotion_ready": False,
            "files": {
                str(p.relative_to(staging)): digest(p) for p in staging.rglob("*") if p.is_file()
            },
        }
        write_json(staging / "receipt.json", receipt)
        staging.rename(out)
    return receipt
