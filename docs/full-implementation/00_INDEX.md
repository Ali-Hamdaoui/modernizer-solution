# V1 Full Implementation Index

This folder is documentation-only. Implementation status for every issue is `NOT_STARTED`. Product code, tests, YAML profiles/catalogs, SQLite migrations, and deleted historical docs were not changed by generating this workspace.

Issue count: `50`.

## implementation order
| order | issue | title | type | effort | blocked_by | blocks | recommended primary skill | implementation status |
|---:|---|---|---|---|---|---|---|---|
| 1 | `V1-01` | Remove local runtime artifacts | `chore` | `XS` | `none` | `V1-00A,V1-00B,V1-02` | `test-discipline` | `NOT_STARTED` |
| 2 | `V1-00A` | Add V1 contract fixture module | `test` | `S` | `V1-01` | `V1-00B,V1-02,V1-03A` | `test-discipline` | `NOT_STARTED` |
| 3 | `V1-00B` | Register V1 pipeline and runner fixtures | `chore` | `S` | `V1-00A` | `V1-02,V1-05` | `test-discipline` | `NOT_STARTED` |
| 4 | `V1-02` | Lock V1 migration route | `feat` | `M` | `V1-00B` | `V1-03A,V1-03B,V1-04` | `test-discipline` | `NOT_STARTED` |
| 5 | `V1-03A` | Add stage-chain ledger schema | `feat` | `M` | `V1-02` | `V1-03B,V1-04,V1-08A,V1-19A` | `test-discipline` | `NOT_STARTED` |
| 6 | `V1-03B` | Persist ledger during job creation | `feat` | `M` | `V1-03A` | `V1-04,V1-06A,V1-08A` | `test-discipline` | `NOT_STARTED` |
| 7 | `V1-04` | Expose stage chain projections | `feat` | `M` | `V1-03B` | `V1-05,V1-18B,V1-19A` | `test-discipline` | `NOT_STARTED` |
| 8 | `V1-05` | Validate runner JDK readiness | `feat` | `L` | `V1-04` | `V1-06B1,V1-08B,V1-18A` | `test-discipline` | `NOT_STARTED` |
| 9 | `V1-00C` | Define V1 event type registry | `feat` | `S` | `V1-04` | `V1-06A,V1-07A,V1-08A,V1-10,V1-18B` | `test-discipline` | `NOT_STARTED` |
| 10 | `V1-09` | Register Azure model profiles | `feat` | `M` | `V1-00C` | `V1-10,V1-11A,V1-12B,V1-14C,V1-16A,V1-18D` | `test-discipline` | `NOT_STARTED` |
| 11 | `V1-10` | Audit model invocations | `feat` | `M` | `V1-09` | `V1-00D,V1-11A,V1-12B,V1-14C,V1-16A,V1-18D` | `test-discipline` | `NOT_STARTED` |
| 12 | `V1-00D` | Define redaction and forbidden-path baseline | `security` | `M` | `V1-10` | `V1-11C,V1-16A,V1-17B,V1-15A,V1-19B` | `test-discipline` | `NOT_STARTED` |
| 13 | `V1-11A` | Persist context pack manifests | `feat` | `M` | `V1-00D` | `V1-11B,V1-11C,V1-12B,V1-14C,V1-16A` | `test-discipline` | `NOT_STARTED` |
| 14 | `V1-11B` | Add bounded evidence retrievers | `feat` | `L` | `V1-11A` | `V1-11C,V1-12B,V1-14C,V1-16A` | `test-discipline` | `NOT_STARTED` |
| 15 | `V1-11C` | Add redaction filtering to context packs | `security` | `M` | `V1-11B` | `V1-12B,V1-14C,V1-16A,V1-19B` | `test-discipline` | `NOT_STARTED` |
| 16 | `V1-06A` | Define orchestrator stage command manifest | `feat` | `M` | `V1-05` | `V1-06B1,V1-08B` | `test-discipline` | `NOT_STARTED` |
| 17 | `V1-06B1` | Define stage command launcher contract | `feat` | `M` | `V1-06A` | `V1-06B2` | `test-discipline` | `NOT_STARTED` |
| 18 | `V1-06B2` | Launch worker-owned Stage One | `feat` | `L` | `V1-06B1` | `V1-07A` | `test-discipline` | `NOT_STARTED` |
| 19 | `V1-07A` | Persist Control Tower approvals | `feat` | `L` | `V1-06B2` | `V1-07B,V1-12C,V1-13` | `test-discipline` | `NOT_STARTED` |
| 20 | `V1-07B` | Queue approval resume commands | `feat` | `M` | `V1-07A` | `V1-08A,V1-08B` | `test-discipline` | `NOT_STARTED` |
| 21 | `V1-08A` | Enforce stage continuation policy | `feat` | `M` | `V1-07B` | `V1-08B,V1-19A` | `test-discipline` | `NOT_STARTED` |
| 22 | `V1-08B` | Queue Stage Two and Stage Three execution | `feat` | `L` | `V1-08A` | `V1-12A,V1-19A` | `test-discipline` | `NOT_STARTED` |
| 23 | `V1-12A` | Persist plan amendments and revisions | `feat` | `M` | `V1-11A` | `V1-12B,V1-12C,V1-13` | `test-discipline` | `NOT_STARTED` |
| 24 | `V1-12B` | Generate fake-provider plan proposals | `feat` | `M` | `V1-12A,V1-11C,V1-10` | `V1-12C,V1-13` | `test-discipline` | `NOT_STARTED` |
| 25 | `V1-12C` | Add plan amendment preview API/UI | `feat` | `M` | `V1-12B` | `V1-13,V1-18C` | `test-discipline` | `NOT_STARTED` |
| 26 | `V1-13` | Gate plans with reviewer | `feat` | `M` | `V1-12C` | `V1-14A,V1-18C` | `test-discipline` | `NOT_STARTED` |
| 27 | `V1-14A` | Classify failed commands for repairability | `feat` | `M` | `V1-13` | `V1-14B,V1-14C,V1-18E` | `test-discipline` | `NOT_STARTED` |
| 28 | `V1-14B` | Persist repair attempts and limits | `feat` | `M` | `V1-14A` | `V1-14C,V1-15A,V1-18E` | `test-discipline` | `NOT_STARTED` |
| 29 | `V1-14C` | Generate fake-provider repair proposals | `feat` | `L` | `V1-14B,V1-11C,V1-10` | `V1-15A,V1-18E` | `test-discipline` | `NOT_STARTED` |
| 30 | `V1-16A` | Define read-only assistant tool contracts | `feat` | `M` | `V1-00D,V1-10,V1-11C` | `V1-16B` | `test-discipline` | `NOT_STARTED` |
| 31 | `V1-16B` | Add assistant streaming and redaction | `feat` | `L` | `V1-16A` | `V1-17A,V1-18F` | `test-discipline` | `NOT_STARTED` |
| 32 | `V1-17A` | Persist pending privileged actions | `feat` | `M` | `V1-16B` | `V1-17B,V1-17C,V1-18C` | `test-discipline` | `NOT_STARTED` |
| 33 | `V1-17B` | Validate action policy and checksums | `security` | `L` | `V1-17A,V1-00D` | `V1-17C,V1-17D,V1-15A` | `test-discipline` | `NOT_STARTED` |
| 34 | `V1-17C` | Approve or reject privileged actions | `feat` | `M` | `V1-17B` | `V1-17D,V1-18C` | `test-discipline` | `NOT_STARTED` |
| 35 | `V1-17D` | Execute allowed Maven and write actions | `feat` | `L` | `V1-17C` | `V1-15A,V1-18C` | `test-discipline` | `NOT_STARTED` |
| 36 | `V1-15A` | Validate patch policy | `security` | `M` | `V1-17D,V1-14C,V1-00D` | `V1-15B,V1-15C` | `test-discipline` | `NOT_STARTED` |
| 37 | `V1-15B` | Snapshot sandbox before patch | `feat` | `M` | `V1-15A` | `V1-15C,V1-15E` | `test-discipline` | `NOT_STARTED` |
| 38 | `V1-15C` | Apply approved patch in sandbox | `feat` | `L` | `V1-15B` | `V1-15D,V1-15E` | `test-discipline` | `NOT_STARTED` |
| 39 | `V1-15D` | Validate patch with typed Maven operation | `feat` | `M` | `V1-15C` | `V1-15E,V1-19A` | `test-discipline` | `NOT_STARTED` |
| 40 | `V1-15E` | Roll back failed repair | `feat` | `M` | `V1-15D` | `V1-19A,V1-18E` | `test-discipline` | `NOT_STARTED` |
| 41 | `V1-19A` | Compute deterministic proof gates | `feat` | `M` | `V1-08A` | `V1-19B,V1-19C,V1-18G` | `test-discipline` | `NOT_STARTED` |
| 42 | `V1-19B` | Generate final report artifact | `feat` | `M` | `V1-19A,V1-00D` | `V1-19C,V1-18G` | `test-discipline` | `NOT_STARTED` |
| 43 | `V1-19C` | Expose proof and report API | `feat` | `S` | `V1-19B` | `V1-18G` | `test-discipline` | `NOT_STARTED` |
| 44 | `V1-18A` | Render V1 job creation form | `feat` | `M` | `V1-05,V1-09,V1-02` | `V1-18B` | `test-discipline` | `NOT_STARTED` |
| 45 | `V1-18B` | Render stage timeline panel | `feat` | `S` | `V1-04` | `V1-18C,V1-18G` | `test-discipline` | `NOT_STARTED` |
| 46 | `V1-18C` | Render approvals and action cards | `feat` | `M` | `V1-17C,V1-07B` | `V1-18D` | `test-discipline` | `NOT_STARTED` |
| 47 | `V1-18D` | Render model activity panel | `feat` | `S` | `V1-10` | `V1-18E` | `test-discipline` | `NOT_STARTED` |
| 48 | `V1-18E` | Render repair panel | `feat` | `M` | `V1-14C,V1-15E` | `V1-18F` | `test-discipline` | `NOT_STARTED` |
| 49 | `V1-18F` | Render assistant panel | `feat` | `M` | `V1-16B` | `V1-18G` | `test-discipline` | `NOT_STARTED` |
| 50 | `V1-18G` | Render proof and final report panel | `feat` | `S` | `V1-19C` | `none` | `test-discipline` | `NOT_STARTED` |

## source and split notes
- Original issues consumed: `V1-01` through `V1-19`.
- Support issues added: `V1-00A`, `V1-00B`, `V1-00C`, `V1-00D`.
- Large issues split per Codex analysis: `V1-03`, `V1-06B1`/`V1-06B2`, `V1-07`, `V1-08`, `V1-11`, `V1-12`, `V1-14`, `V1-15`, `V1-16A`/`V1-16B`, `V1-17`, `V1-18`, and `V1-19`.
- `V1-09` is moved earlier than serious LLM workflows. `V1-16A`/`V1-16B` are split before privileged action/patch execution. Backend proof/report work is placed before proof UI.

## corrected skill and split notes
- Every issue requires `test-discipline`; the primary-skill column is the baseline, not the full recommendation set.
- Issue files list optional `graphify` where code navigation is needed and require Graphify before broad scans when `graphify-out/graph.json` exists.
- Security, execution, approval, redaction, model, action, patch, and proof/report issues list optional `requesting-code-review`.
- Dependency/risk-sensitive issues list optional `triage`; only split/backlog-shaping stop cases list optional `to-issues`.
- STOP split markers were expanded into `V1-06B1`/`V1-06B2` and `V1-16A`/`V1-16B`; keep the split docs before product coding if the named sub-splits cannot be completed independently.
