# Agent Instructions — Voice Memo Archiver

This file applies to the entire repository. It provides operational guidance
for AI coding agents. It does not replace the requirements, design documents,
or the repository's executable configuration.

## 1. Communication and language

- Use English for internal planning, analysis, and reasoning when configurable.
- Communicate with users in the language of their latest message. For a
  Japanese-language request, respond in Japanese; for an English-language
  request, respond in English, unless they explicitly request otherwise.
- Follow other applicable natural-language instructions where they do not
  conflict with these rules or with higher-priority instructions.
- Keep identifiers, API names, and Conventional Commit types in English.
- Follow the surrounding file's language and style for documentation and
  comments. The existing design documents are primarily in Japanese.
- Report verified facts separately from assumptions, proposals, and unknowns.
  Never claim that a command or test passed unless it was actually run.

## 2. Authoritative references and decision status

Before implementing a feature, review the relevant parts of:

1. `docs/REQUIREMENTS.md`, if present.
1. `docs/DESIGN.md`, particularly safety, phase gates, and open issues.
1. Applicable records under `docs/ADR/`, if present.
1. Actual source code, tests, and tool configurations in the working tree.

The design is a draft, not evidence that a feature or external API exists.
Respect its labels: `[R]` is a stated requirement; `[D]` is a provisional
design choice; `[P]` needs a proof of concept; `[O]` is unresolved.
Proposals and example commands are not automatically implemented or approved.

- Follow the actual repository layout and installed tools. The directory tree
  in `docs/DESIGN.md` is a target structure, not proof of existing files.
- Do not silently resolve an open issue or promote a PoC result to a contract.
  Document findings, alternatives, evidence, and consequences in an ADR or
  design update for material decisions.
- Prefer a small, reviewable change over unrelated restructuring. Do not
  introduce a new provider, framework, language, or service without need.
- Never weaken a safety invariant to make a test pass or meet a deadline.

## 3. System boundaries and dependencies

Preserve the planned Clean Architecture and dependency direction:

- `domain/`: entities, value objects, policies, state transitions, and pure
  business rules. No I/O, SDKs, ORM, HTTP, OS APIs, or ambient clock access.
- `application/`: use cases and abstract ports depending on the domain, not
  on concrete infrastructure. Inject the clock, IDs, repositories, and ports.
- `infrastructure/`: concrete source, storage, persistence, and telemetry
  adapters implementing the application ports.
- `interfaces/`: CLI, workers, and agent protocol; delegate business rules
  to application use cases.
- `bootstrap/`: composition root and dependency-injection wiring.

Use `ArchiveTarget` for a configured destination instance,
`StorageBackend` for its implementation type,
and `Replica` for the (target, revision) verification state.
Do not conflate these concepts.

The current design proposes a Python Core and a macOS source agent; use
Swift/native helpers only where PoC evidence justifies them. Keep the state
repository and staging store behind ports. PostgreSQL is a proposed
production adapter, not a domain-level dependency. Keep workers disposable:
recovery must come from durable external state and artifacts.

## 4. Non-negotiable data and replication invariants

- Preserve original audio bytes without transcoding, normalization, or
  overwriting. Derivatives must remain separately identifiable.
- Preserve obtainable raw metadata, its type/provenance, and unknown fields.
  Normalized views must never replace the underlying captured information.
- Maintain stable source-scoped recording identity. Do not treat a filename,
  title, recording date, or content hash alone as a recording identifier.
- Model modifications as immutable `Revision` records with immutable
  `Artifact` references and canonical manifests.
- Distinguish acquisition completeness, replica integrity, and
  restorability. Never equate `PLAYABLE` with a faithful Voice Memos restore.
- Treat `missing`, `unsupported`, `not_applicable`, and `unknown` distinctly.
  Unknown or partial acquisition cannot be reported as complete.
- Sync each `ArchiveTarget` independently. A failure, retry, lease, or rate
  limit on target A must not invalidate target B's verified receipt or block
  B solely because A failed.
- Do not claim a distributed atomic transaction across providers. Publish
  only verifiable committed revisions; a staged object alone is insufficient.
- Use stable logical operation IDs and idempotent replay. Handle crashes,
  concurrent workers, expired leases, lost responses, and duplicate uploads.
- Verify stored bytes using the documented digest and read-back guarantees.
  Provider object presence or a provider ETag alone is not universal proof.
- Do not count two targets in the same underlying failure domain as two
  independent replicas. Repairs must use previously verified data.

## 5. Source access and disposal safety

**Source deletion is disabled by default and MUST remain disabled during
feasibility and archive-only work.** `Disposal` means deletion of the
Voice Memos/iCloud source, not eviction of a local iPhone cache.

- Default all work against Apple Voice Memos to read-only observation.
- Do not write directly to the Voice Memos internal database or use
  undocumented CloudKit writes. Treat source-store layouts as unstable.
- Do not run live-source modifications, cloud uploads, or destructive
  cleanup against a real account without explicit authorization.
- Do not implement, enable, or invoke actual source deletion merely because
  an archive exists or a user asks for a routine test.
- Before any future deletion-capable release, require the approved phase
  gate, a source adapter proven to select exactly the intended recording,
  separately verified independent replicas, explicit consent, review,
  auditability, and dedicated real-environment safety tests.
- Use three-valued policy logic (`TRUE`, `FALSE`, `UNKNOWN`). A final
  `UNKNOWN` is not authorization to delete. A user-defined policy cannot
  override the independent immutable safety gates.
- Re-read the source immediately before a deletion request and verify the
  stable recording ID, current revision, settled sync state, and freshness
  of proof. If any predicate is false or unknown, return `BLOCKED`.
- Handle ambiguous deletion responses through reconciliation, not a blind
  retry. Do not add permanent-deletion capability in initial releases.
- Keep verified archives and immutable audit records after source deletion.

For PoC work, use synthetic recordings, snapshots, mocks, and dry-run plans
wherever possible. A source adapter without a demonstrated stable ID or
consistent snapshot is a **No-Go** for automated disposal.

## 6. Security, privacy, and credentials

- Audio, transcripts, metadata, Apple account identifiers, OAuth tokens,
  and provider paths may be sensitive. Use least privilege.
- Never commit or print credentials, refresh tokens, recording contents,
  private source databases, or production archive snapshots.
- Inject secrets through explicit references to a secret provider or an
  approved host credential facility. Do not bake secrets into images,
  fixtures, logs, or example configuration.
- Prefer synthetic/redacted fixtures and local mocks. Do not send real
  audio/transcripts to external services or observability backends.
- Make telemetry content-free by default. OTel and opt-in Sentry must not
  leak raw audio, transcript text, tokens, or sensitive metadata.
- Preserve verifiable integrity and restoration paths. If encryption is
  enabled, test key availability and successful restore independently.

## 7. Implementation and quality standards

- Prefer strict typing, explicit error types, small focused modules,
  domain-specific invariants, and constructor-based dependency injection.
- For Python, use type hints compatible with `mypy --strict` and `ty check`.
  Avoid uncontrolled `Any`, silent exceptions, and type-ignore workarounds.
- Follow Ruff and the repository's configured formatting and lint rules.
  Use value objects where they encode genuine invariants, not reflexively.
- Keep tests near Python implementation files as `test_<module>.py` where
  specified. Place integration, contract, and E2E tests in their respective
  test directories, matching the actual project layout.
- Write deterministic domain and use-case tests with injected time, IDs,
  and adapters. Add provider contract tests and fault injection for I/O.
- Target 100% C1 branch coverage as specified by the design. Never weaken
  coverage thresholds or add exclusions just to achieve a passing build.
- For Markdown, follow repository lint configuration. In the current
  documentation, keep lines within 80 characters and nested unordered
  lists at the indentation accepted by `mdl` (typically three spaces).
- Preserve valid YAML, JSON, shell, diagrams, and code blocks when editing
  documentation. Do not alter semantics solely to appease a formatter.

When the corresponding tools/configuration are available, validate with:

```bash
ruff check .
ruff format --check .
ty check
mypy --strict
tach check
pytest --cov=src/voice_memo_archiver --cov-branch \
  --cov-report=xml --cov-fail-under=100
```

Also run the repository's configured Markdown, YAML, JSON, TOML, Shell,
Dockerfile, and workflow checks for affected files. Do not assume all tools
or project configuration already exist; report missing prerequisites rather
than misrepresenting success.

## 8. Required tests for affected behavior

Choose relevant tests from the design's test matrix, especially:

- Replaying the same recording/revision/operation many times yields one
  logical result; renames produce revisions without destroying history.
- One archive target suffering 401, 429, 5xx, quota failure, corruption,
  or timeout does not prevent healthy targets from completing.
- Manifest staging without commit is not considered fully archived.
- Partial capture, unknown metadata, in-progress recording, uncertain
  cloud materialization, or revision races block disposal.
- `NOT UNKNOWN = UNKNOWN`, and failure-domain quorum is enforced even if a
  policy expression itself evaluates to true.
- Lost provider responses, duplicate uploads, concurrent workers,
  migrations, crashes, and restarts converge without data loss.
- Restore and verify work independently from each target on another host.
- Telemetry and diagnostic bundles contain no raw content or credentials.

## 9. Phases and change management

Follow the planned sequence, subject to approved design changes:

1. Phase 0: read-only macOS feasibility and acquisition PoC.
1. Phase 1: archive-only, durable manifests, replication, verification,
   replay, and independent export/restore; deletion still disabled.
1. Phase 2: completeness, change detection, revalidation, and repair.
1. Phase 3: typed disposal policy and **dry-run only** safety evaluation.
1. Phase 4: separately approved, per-recording controlled disposal.
1. Phase 5: explicitly opted-in autonomous disposal after strong evidence.
1. Phase 6: optional adapters, interfaces, and portable enhancements.

Do not skip a Go/No-Go condition or treat a future phase as authorized by
this file. Track open issues in the design and ADRs; document what was
measured, which environment was used, and what remains unverified.

## 10. Agent workflow and delivery

1. Inspect relevant documents, code, tests, and working-tree changes.
1. State the smallest feasible change and risks; retain unrelated edits.
1. Implement behind the correct layer/port and add or update tests.
1. Run relevant available quality checks and inspect the resulting diff.
1. Report modified files, observed outcomes, limitations, and pending
   safety/phase decisions. Do not claim completion beyond the evidence.

Use Conventional Commits with English types, such as `feat:`, `fix:`,
`docs:`, `test:`, `refactor:`, and `chore:`. Preserve repository Git policy:
no direct push to `main`, required checks, and merge-commit conventions when
those workflows are configured. Do not create a commit, push, or merge unless
requested and authorized.
