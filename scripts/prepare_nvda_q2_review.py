"""Export an unscored private X/Y review packet from explicit completed candidates.

Read-only admission replay precedes export. No provider calls, database writes,
human scores, unblinding decision or promotion. Keep administrator/ from reviewers.
"""

import argparse
import importlib.util
import json
import secrets
import sqlite3
import tempfile
from pathlib import Path
from typing import get_args

from valuation_engine.ai.contracts import FeatureName
from valuation_engine.ai.native_preflight import PROTOCOL_HASH, load_bound, sha


def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def lineage(database, ids, execution_root=None):
    path = Path(__file__).with_name("verify_fsi_lineage.py")
    spec = importlib.util.spec_from_file_location("review_lineage", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.verify(database, ids, execution_root=execution_root)


def render(sample):
    lines = [
        f"# 候選 {sample['sample']}：NVDA FY2023-Q2",
        "",
        "未經真人核准的研究補充。只檢視此季度，不套用到目前工作台，也不產生買賣建議。",
        "",
        "## 研究判斷",
        "",
    ]
    for item in sample["features"]:
        lines += [
            "### " + item["feature_name"],
            "",
            item["net_assessment"],
            "",
            "支持依據：" + ", ".join(item["supporting_evidence"]),
            "",
            "反向依據：" + (", ".join(item["contradicting_evidence"]) or "未提供"),
            "",
        ]
    lines += ["## 模型檢視意見", ""]
    for item in sample["challenges"]:
        lines += [
            f"- {item['kind']} / {item['affected_model_variable']}：{item['description']}",
            "  依據：" + ", ".join(item["evidence"]),
            "",
        ]
    lines += [
        "## 缺失與拒絕",
        "",
        "未提供判斷的主題：" + ", ".join(sample["missing_features"]),
        "",
        f"保留 {len(sample['rejections'])} 筆拒絕紀錄，完整理由與原稿在同名 JSON。",
        "",
        "證據鍵、原文片段、來源段落與文件雜湊均在同名 JSON；sources/ 保留完整原件與段落。",
        "綜合段落原稿另列 section_drafts，尚未經人工逐句驗證；不視為已核准敘述。",
        "",
    ]
    return "\n".join(lines)


def prepare(database, selections, protocol_path, out, *, execution_root=None):
    if set(selections) != {"B", "C"} or len(set(selections.values())) != 2:
        raise ValueError("Two distinct explicit candidate run IDs required")
    if out.exists() or out.is_symlink():
        raise ValueError("Review output must be a new directory")
    before = sha(database.read_bytes())
    protocol = load_bound(protocol_path, "protocol_hash", PROTOCOL_HASH)
    verification = lineage(database, list(selections.values()), execution_root)
    if verification.get("lineage_status") != "CONSISTENT":
        raise ValueError("Both completed candidates require consistent admission replay")
    if any(Path(str(database) + suffix).exists() for suffix in ("-wal", "-shm", "-journal")):
        raise ValueError("Candidate is still active or has unresolved sidecars")
    ordered = list(selections.items())
    secrets.SystemRandom().shuffle(ordered)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="q2-review-", dir=out.parent) as directory:
        staging = Path(directory) / "packet"
        reviewers, admin = staging / "reviewers", staging / "administrator"
        sources = reviewers / "sources"
        sources.mkdir(parents=True)
        admin.mkdir()
        mapping = {}
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            for label, (method, run_id) in zip(("X", "Y"), ordered, strict=True):
                row = connection.execute(
                    "SELECT * FROM s2_experiment_runs WHERE id=?", (run_id,)
                ).fetchone()
                if (
                    row is None
                    or row["method"] != method
                    or row["quarter"] != "FY2023-Q2"
                    or row["status"] != "COMPLETED"
                ):
                    raise ValueError("Selected method, quarter or completion mismatch")
                context = json.loads(row["context_json"])
                evidence = [
                    json.loads(r[0])
                    for r in connection.execute(
                        "SELECT metadata_json FROM s2_evidence WHERE run_id=? ORDER BY id",
                        (run_id,),
                    )
                ]
                features = [
                    json.loads(r[0])
                    for r in connection.execute(
                        "SELECT metadata_json FROM s2_features WHERE run_id=? ORDER BY id",
                        (run_id,),
                    )
                ]
                challenges = [
                    json.loads(r[0])
                    for r in connection.execute(
                        "SELECT metadata_json FROM s2_challenges WHERE run_id=? ORDER BY id",
                        (run_id,),
                    )
                ]
                rejected = [
                    {"stage": r[0], "claim_type": r[1], "reason": r[2], "raw": json.loads(r[3])}
                    for r in connection.execute(
                        "SELECT stage,claim_type,reason,raw_json FROM s2_guard_rejections WHERE run_id=? ORDER BY id",
                        (run_id,),
                    )
                ]
                synthesis = connection.execute(
                    "SELECT raw_response FROM s2_provider_calls WHERE run_id=? AND stage='synthesize'",
                    (run_id,),
                ).fetchone()
                sample = {
                    "sample": label,
                    "quarter": "FY2023-Q2",
                    "quality_verdict": "UNSCORED",
                    "features": features,
                    "challenges": challenges,
                    "evidence": evidence,
                    "rejections": rejected,
                    "missing_features": sorted(
                        set(get_args(FeatureName)) - {f["feature_name"] for f in features}
                    ),
                    "section_drafts": json.loads(synthesis[0])["structured_output"].get(
                        "sections", []
                    ),
                    "section_status": "UNREVIEWED_DRAFTS",
                    "repeat_stability": "UNASSESSED_NO_REPEATS",
                    "model_snapshot_identity": "UNVERIFIED",
                    "historical_oos": False,
                    "promotion_ready": False,
                }
                write(reviewers / f"{label}.json", sample)
                (reviewers / f"{label}.md").write_text(render(sample))
                for source in connection.execute(
                    "SELECT source_hash,content FROM s2_source_documents WHERE run_id=?", (run_id,)
                ):
                    if sha(source[1]) != source[0]:
                        raise ValueError("Source bytes changed")
                    target = sources / source[0]
                    if target.exists() and target.read_bytes() != source[1]:
                        raise ValueError("Source hash collision")
                    target.write_bytes(source[1])
                write(sources / f"{label}-source-map.json", context["sources"])
                mapping[label] = {"method": method, "run_id": run_id}
        finally:
            connection.close()
        rule = protocol["review_rule"]
        write(
            reviewers / "rubric.json",
            {
                k: rule[k]
                for k in (
                    "version",
                    "anchors",
                    "hard_gates",
                    "quality_dimensions",
                    "scale",
                    "missing_repeat",
                    "missing_scores",
                    "independent_reviewers",
                    "disagreement",
                    "result_scope",
                )
            },
        )
        forms = {
            label: {
                "hard_gates": {key: None for key in rule["hard_gates"]},
                "scores": {key: None for key in rule["quality_dimensions"]},
                "rationale_and_evidence": None,
            }
            for label in ("X", "Y")
        }
        (reviewers / "README.md").write_text(
            "# NVDA 單季盲評資料\n\n先閱讀 X.md 與 Y.md，再用各自 JSON 的證據鍵回查 sources/ 完整段落和來源。兩位真人分別填寫 reviewer-1.json、reviewer-2.json，請勿互看答案。不得用程式通過數或候選數量代替內容評分。\n\n審查者不得已接觸方法對照、本次執行討論或帶有方法名稱的結果統計；已接觸者不能算作未揭盲的獨立審查者。只提供 reviewers/，不要提供 administrator/ 或執行稽核原件。\n\n本次只有一組分析，沒有重複實驗；穩定性應保留未評估，也不能給出完整總分。尚未審查的分數保留 null，不能把缺少審查填成零；已審查且不受支持的結論依 rubric 的零分錨點判斷。若兩人意見不同，須第三位真人裁決。候選身分在評分及裁決綁定後才揭露；不要查看 administrator/。\n\n所有 AI 敘述皆待審；數字、研究日估值和目前 NVDA 工作台不受本資料影響。此季屬重建研究資料，沒有歷史樣本外或模型快照相同的證明。\n"
        )
        hashes = {
            str(p.relative_to(reviewers)): sha(p.read_bytes())
            for p in reviewers.rglob("*")
            if p.is_file()
        }
        packet_hash = sha(json.dumps(hashes, sort_keys=True).encode())
        for index in (1, 2):
            write(
                reviewers / f"reviewer-{index}.json",
                {
                    "packet_hash": packet_hash,
                    "reviewer_identity": None,
                    "reviewed_at": None,
                    "independence_confirmed": None,
                    "samples": forms,
                    "total_score": None,
                    "status": "UNSUBMITTED",
                },
            )
        write(
            admin / "mapping.json",
            {
                "candidate_database_sha256": before,
                "protocol_hash": PROTOCOL_HASH,
                "packet_hash": packet_hash,
                "mapping": mapping,
                "unblind_only_after_bound_reviews_and_adjudication": True,
            },
        )
        write(admin / "lineage.json", verification)
        if sha(database.read_bytes()) != before:
            raise ValueError("Candidate changed during export")
        write(
            staging / "manifest.json",
            {
                "version": "NVDAQ2BlindPacketV1",
                "packet_hash": packet_hash,
                "files": hashes,
                "human_reviews_completed": 0,
                "quality_verdict": "UNSCORED",
                "winner": None,
                "promotion_ready": False,
            },
        )
        staging.rename(out)
    return {"status": "PREPARED_UNSCORED", "packet_hash": packet_hash, "human_reviews_completed": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--run-b", type=int, required=True)
    parser.add_argument("--run-c", type=int, required=True)
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--execution-root", type=Path, help="Required receipts for live candidates")
    args = parser.parse_args()
    print(
        json.dumps(
            prepare(
                args.database,
                {"B": args.run_b, "C": args.run_c},
                args.protocol,
                args.out,
                execution_root=args.execution_root,
            )
        )
    )


if __name__ == "__main__":
    main()
