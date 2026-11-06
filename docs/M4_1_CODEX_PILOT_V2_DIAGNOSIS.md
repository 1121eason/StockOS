# M4.1 Codex PIT FY2023-Q2 V2 diagnosis

Date: 2026-09-24 UTC. This is a new execution receipt; the older Codex CLI report remains historical evidence. **Q2 gate: FAIL. The remaining six quarters were not started.**

## Isolation and launch

The installed CLI was `codex-cli 0.155.0-alpha.9.2`. A synthetic call inside the ordinary outer task sandbox failed before inference because the CLI could not initialize its in-process app-server client (`Operation not permitted`). The same synthetic call succeeded when launched through the approved outer execution path. This did not change the inner `qve_pit` profile. Fresh OS probes denied writes, outside-canary and repository reads, and direct network access. The seven synthetic cases and C1-C12 all passed with the current policy hash `8c4981121725951be4f495557cf49ecb20a9775d7bf08a9560684bfd397561ee`. See `data/m41/codex/kernel-shell-v4.json`, `experiment-v3.json`, and `discovery-final-v3.json`.

## Real Q2 result

The FY2023-Q2 cutoff was `2022-08-25T13:30:00+00:00`; the package contained four source documents and 932 narrative blocks. Package hash: `331e90ebd3ca261c06cf090a5d46ae852a4ded7eb133c434e5f7537abd3ff4c5`. The new database analysis run is ID 10.

| Check | V2 result |
|---|---:|
| Extraction batches | 20/20 valid |
| Formal admitted evidence | 591 |
| Rejected candidate spans | 4, all `evidence_span_too_long` |
| Synthesis calls | 2/2 timed out at 180 seconds |
| Completed snapshot | 0 |
| Feature rows and challenge rows | 0 |
| Automated Q2 gate | FAIL |

The two synthesis call receipts are IDs 71 and 72, both `invalid_or_unavailable` with `failure_kind=timeout`. Both used the same exact prompt, were terminated at the configured 180-second limit, and produced no final structured answer. Both recorded zero permission requests and zero tool attempts. The synthesis input serialized to 481,768 bytes for 591 evidence items, 14.8 times the median extraction request size (32,472 bytes). All evidence is sent in one synthesis request; the pilot gives it the same 180-second timeout as each extraction request. The quarter package staged another 633,819 bytes; staging does not prove the model read every file.

A separate read-only diagnostic repeated the exact synthesis prompt and quarter package under the unchanged `qve_pit` isolation policy with a 600-second diagnostic limit. It returned a structured answer after 331.2 seconds (27 feature candidates, 10 section candidates), without a tool or permission attempt or database write. Receipt: `data/m41/codex/synthesis-diagnostic-v1.json`. This proves that the 180-second limit was too short for this Q2 synthesis call. The large, unbatched request and larger expected output are plausible causes of the longer processing time; their individual latency contributions were not isolated. The diagnostic answer was not admitted to the failed run or checked as a complete Q2 snapshot.

The four rejected spans contained 56, 56, 56, and 57 whitespace-separated words against a strict maximum of 55. They were exact substrings of available Q2 source blocks, and two were the same quotation in separate source documents (three unique quotations). The response schema permits up to 500 characters but does not enforce the 55-word limit; the deterministic admission guard rejected these schema-valid candidates. The current acceptance policy treats `evidence_span_too_long` as a non-quarantinable rejection, so it is a separate Q2 blocker even if synthesis later completes. Those four candidates stayed outside formal evidence; do not admit or silently repair them. The complete blocker list is in `data/m41/codex/pilot-v2.json`.

The before/after count and content hash matched for all ten protected financial, Quant, forecast, valuation and Regime tables (`data/m41/codex/preservation-v2.json`). The six later quarters were not run; seven-quarter completion remains 0/7, repeatability 0/2, and human review 0/35. No M4.1 Final Pass, 26-quarter expansion, or M5 work follows from this run.

## Engineering follow-up

Use a general, versioned solution for large evidence sets before any new Q2 run: either a bounded, auditable evidence selection/aggregation step that retains contrary evidence and exact source links, or a measured stage timeout policy with a new receipt version. Test the same policy on synthetic large inputs and regression cases. Decide explicitly whether rejected overlong spans may be quarantined without failing an otherwise complete quarter; keep the 55-word admission limit and do not create a Q2-only exception. A later Q2 rerun must write a fresh versioned receipt. The remaining six quarters stay blocked until that new Q2 receipt passes.

Targeted regression tests for the current transport/package/pilot code: 19 passed. Ruff and `git diff --check` passed. These checks do not replace the failed real Q2 gate.
