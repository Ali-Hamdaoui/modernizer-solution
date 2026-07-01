# Migration Knowledge System Architecture

## Purpose

The governed Control Tower needs memory without giving memory authority.
Memory can suggest. The backend still validates, persists, applies in sandbox, and proves.

## Layer 1: Deterministic Rule Registry

Use for stable repeatable fixes.

Rule fields:

- rule id
- stage applicability
- source and target Boot versions
- source and target Java versions
- required evidence kinds
- required file checksums
- allowed path scope
- patch generator id
- reviewer evidence requirements
- verification plan
- promotion source cases
- anti-patterns
- rollback expectations

Promotion criteria:

- at least three successful governed cases or one project-approved golden reference plus tests;
- exact evidence requirements documented;
- patch generator has path containment and checksum tests;
- reviewer can explain why the rule fits;
- apply and verification artifacts prove sandbox-only behavior;
- no legacy mutation.

## Layer 2: Migration Case Memory / RAG

Use for solved cases, golden references, reviewer critiques, human decisions, failed attempts, and anti-patterns.

Case schema:

- case id
- project family
- stage index
- stage name
- source Boot version
- target Boot version
- source Java version
- target Java version
- failure type
- repair family
- classifier confidence
- evidence pack id and checksum
- artifact refs and checksums
- exact-match signature
- embedding text
- proposed patch checksum
- reviewer decision
- human decision
- apply result
- verification result
- rollback result
- sandbox-only proof
- legacy-unchanged proof
- final outcome
- trust level
- stale markers
- redaction status

Exact-match signature fields:

- stage version tuple
- normalized compiler or test error category
- dependency coordinates
- source namespace signals
- test framework markers
- public API signature hash
- artifact checksum set

Embedding text:

- stage target summary
- normalized failure summary
- dependency signals
- source/test markers
- proposed repair summary
- reviewer critique summary
- verification outcome summary

Stage/version filters:

- never retrieve Boot 3/4 Jakarta cases as authoritative for Boot 2.7 javax repairs;
- never retrieve Java 21 compiler fixes for Java 11 stages without downgrade note;
- prefer same stage index and same target versions;
- allow cross-stage retrieval only as weak analogy.

Trust levels:

- `golden_reference_verified`
- `governed_success`
- `governed_partial_success`
- `reviewed_human_only`
- `failed_attempt`
- `anti_pattern`
- `untrusted_import`

Stale memory detection:

- artifact checksum mismatch;
- dependency version drift;
- stage version mismatch;
- rule superseded;
- verifier changed;
- repeated apply failure;
- reviewer rejects retrieved analogy.

Privacy and redaction:

- store path-redacted snippets for UI/model prompts;
- keep backend artifact refs and checksums authoritative;
- never let prompt text override backend gates;
- do not store secrets or raw local absolute paths in memory payloads.

## Layer 3: LLM Reasoning

Use for novel or ambiguous cases.

Proposer role:

- read evidence pack and retrieved memory;
- draft bounded proposal;
- cite evidence and memory ids;
- include uncertainty and missing evidence;
- never choose paths, commands, env, or apply action from browser input.

Reviewer role:

- critique proposal against evidence;
- check stage/version fit;
- check memory relevance;
- reject stale or overbroad proposals;
- require deterministic verification plan.

Fallback role:

- inspect low confidence classifications;
- inspect reviewer disagreement;
- inspect apply or verification failure;
- detect repeated blockers;
- recommend next governed action.

## Gate Preservation

Memory never bypasses:

- classifier evidence requirements;
- reviewer gate;
- human exact checksum approval;
- patch gate;
- backend-owned apply;
- git apply check;
- Maven/build/test verification;
- sandbox-only proof;
- legacy-unchanged proof;
- downstream stage policy.

## How msa-utils Enters

Use `msa-utils` as:

- deterministic rule candidates;
- human review gate candidates;
- RAG seed cases;
- anti-pattern examples;
- test fixture ideas.

Do not import its patch apply or executor path as authority. Current Control Tower apply spine remains owner.

## Roadmap

R7C.2:

- Import/refine classifier labels and stage filters from `msa-utils`.
- Keep repair disabled.

R7C.3:

- Add read-only migration memory seed store and retrieval API.
- No proposal or apply.

R7D:

- Add evidence-bound proposer for one narrow family.
- Reviewer and human gates required.

R7E:

- Use memory in proposer, reviewer, fallback, and chatbot explanations.

R7F:

- Run first real seeded governed repair smoke.

R8:

- Selectively adapt remediation modules into backend-owned proposal generators.

R9:

- Reconcile with 4-stage branch using shared stage/evidence contracts.
