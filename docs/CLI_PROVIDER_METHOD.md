# CLITransportV1 — M4.1

The default transport is the official Claude Code executable, requested model `sonnet`.
This is an explicit alias, not a claim of a pinned underlying model. Set
`QVE_CLAUDE_MODEL` to a supported full model identifier when a specific model is required.
The actual model is taken only from CLI output (`model` or one `modelUsage` key), otherwise
`unavailable` / `requested_only`. CLI version is checked at execution time; a change fails the call.

No API key is required. The user signs in through `claude auth login` using their subscription.
QVE calls `claude auth status --json` and admits only `loggedIn=true, authMethod=claude.ai (legacy claudeAi also accepted)`.
It never reads authentication files, keychain values, or tokens. Optional Gemini/Codex adapters
only inspect executable versions and help; model requests fail closed pending PM activation.

Runtime discovery checks the installed help for every required flag. Each request launches
an argv array with `--print --output-format json --json-schema ... --tools "" --safe-mode
--strict-mcp-config --no-session-persistence`. The frozen system prompt is a separate argument;
untrusted documents are JSON on stdin. The process runs in a disposable empty directory.
Only HOME, PATH, TMPDIR, USER, LOGNAME, SHELL and locale environment variables are inherited. USER/LOGNAME/SHELL are required by the installed official CLI to detect the existing subscription session. No API-key, private
token, endpoint override or proxy variable is forwarded. `--bare` is deliberately not used:
installed help says it disables subscription authentication. No permission bypass is used.

There are at most two application attempts per stage. Each process has a timeout (default
240 seconds); its process group is killed on timeout and the temporary directory is removed.
CLI-internal network retries are governed by the official CLI, still bounded by that timeout.
Stdout is parsed as a JSON object; only `structured_output` reaches the existing Pydantic
schemas. Prose is never repaired into financial results. Error diagnostics are not persisted;
their hash and byte count are kept. Successful structured envelopes are allowlisted and their
original stdout hash is recorded. Prompt/source/version metadata lives in existing immutable
run and call JSON fields. The response hash remains the hash of the persisted wrapper; the raw
output hash identifies original CLI bytes. No schema migration is needed.

AIAnalystPolicyV1, PromptSetV1, FeatureSchemaV1, source selection, confidence, contradiction
handling, quote validation and deterministic Quant code remain unchanged. The only change to
the frozen service is CLI identity/admission metadata and the seven-quarter execution gate.
The original M4 freeze and delivery archives remain intact. `data/m41/transport-freeze.json`
records the new execution implementation separately.

## Operation

```text
qve ai-provider-check --provider claude_cli
qve ai-analyze --ticker NVDA --quarter FY2027-Q2 --provider claude_cli
qve ai-run-validation-set --ticker NVDA --provider claude_cli --repeat
qve ai-review-status --ticker NVDA
qve ai-features --ticker NVDA --quarter FY2027-Q2
qve ai-challenges --ticker NVDA --quarter FY2027-Q2
```

The validation command prepares seven contexts even when auth is unavailable. It never
substitutes fixture results. It commits completed/failed analyses per quarter and writes
progress after each quarter. A process interruption before a quarter commit can require
that quarter to be rerun; there is no hidden partial-result resume. Cached completed analyses
are reused, while `--repeat` explicitly reruns the first two quarters with refresh.
Repeatability includes evidence Jaccard, direction agreement, absolute magnitude difference
and challenge dimension overlap; it is not a human semantic judgment.

Generated review cards are separate from filled review files. Review submission contains
the unchanged ReviewDraft fields plus an aware `reviewed_at`; the immutable review row stores
that human-supplied timestamp. Each review must reference evidence from that same completed
run. Import accepts reviewer attestations, not authenticated reviewer identities. Notes should
record supported / partially_supported / unsupported material claims and distinguish extraction,
interpretation, unsupported assertions and missed insights. Do not call automated checks human
review. Raw exact-quote support is insufficient to establish semantic support. Pending or adverse
human reviews block Final Pass and any expansion decision; they do not rewrite immutable
historical snapshots. Unsupported claims identified by human review require a separately
reviewed remediation before the output is used as an accepted research dataset.

## Interface references

- [Claude CLI reference](https://code.claude.com/docs/en/cli-usage)
- [Claude programmatic execution](https://code.claude.com/docs/en/headless)
- [Codex non-interactive execution](https://learn.chatgpt.com/docs/non-interactive-mode)

Installed `--help` is the runtime capability authority. Documentation is not treated as
proof of an installed flag, active authentication, successful real output, or model quality.
