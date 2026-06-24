# DEMO3 Risks

| Risk | Impact | Mitigation |
|---|---|---|
| Reviewer LLM treated as optional | Supported model-required artifacts become unreviewed | Fail closed unless reviewer validates exact artifact checksum. |
| Primary LLM output passed forward without final artifact | Next agent consumes unreviewed or stale reasoning | Final reviewed Markdown is the only forward contract. |
| Target profile overshoot | User asks for one target and system migrates beyond it | Persist `target_profile`, validate route, stop when reached. |
| Already-modernized app forced through old stages | False failures and unnecessary changes | Detect source profile, allow validated override, record skipped stages. |
| Build/Test Repair Agent applies patch without exact approval | Unsafe mutation | Bind approval to exact reviewed diff checksum. |
| User comments not included in repeated repair review | New proposal ignores human correction | Include comments, previous diff, prior reasoning, reviewer notes, current repo state, and checksums. |
| Stale diff applied after repo changed | Patch may apply to wrong state | Revalidate repository state and artifact/checkpoint checksums before apply. |
| Copilot/TUI path remains reachable | Product control surface remains ambiguous | F0 inventory, quarantine/removal, and cleanup report. |
| Web/vendor recipe used without backend allowlist | LLM can indirectly choose execution | Only backend-allowlisted repair modes execute after review and approval. |
| Provider/model runtime detail leaks into public contract | Frontend becomes runtime-control surface | Public docs/API fields expose IDs, statuses, decisions, profiles, refs, and checksums only. |
| Repair Agent overfits Jackson proof | F5 becomes a special-case workflow | Keep Jackson/OpenRewrite as one allowlisted proof scenario under generic Build/Test Repair Agent flow. |
