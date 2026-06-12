# V1 Full Implementation Rules

## Documentation workspace rule

This folder is an implementation-planning workspace only. It must not be treated as completed product work.

## V1 invariants

```text
Pipeline ID: springboot-216-to-356-java21-three-stage
Stage 1: profile springboot-2.1.6-to-2.7-java11, target Spring Boot 2.7.18, Java 11, JDK ID java11, input original legacy source
Stage 2: profile springboot-2.7-to-3.5-java17, target Spring Boot 3.5.6, Java 17, JDK ID java17, input Stage 1 sandbox
Stage 3: profile springboot-3.5-java17-to-java21, target Spring Boot 3.5.6, Java 21, JDK ID java21, input Stage 2 sandbox
```

## Hard exclusions

- Spring Boot 4 is not selectable in the V1 route.
- `3.5.14` must not be execution-relevant in V1.
- Browser cannot choose raw executable paths, raw Maven goals, shell commands, or raw model deployment IDs.
- LLM cannot execute, approve, or write files directly.
- Shell remains disabled by default.
- Maven/write actions are typed privileged actions only.
- Context Builder must exist before serious LLM behavior.
- Maven/tests/proof gates are technical truth.

## Repository safety

- Preserve unrelated work and intentionally deleted historical docs.
- Do not restore deleted docs unless explicitly asked.
- Do not stage unrelated deleted files.
- Do not use `git add .` when unrelated files exist.
- Stage only issue-owned files by explicit path.

## Implementation sequence

Use `00_INDEX.md` order unless fresh source analysis proves a safer order. If order changes, document the source conflict and rationale before editing implementation-owned files.

## Testing rule

Each future implementation issue must run focused tests, affected regression tests, and `git diff --check`. Run the full suite when practical. Do not claim success without real command output.

## Generated issue quality rules

Each `V1-*.md` issue must avoid template language. Scope bullets must name likely files/classes and concrete action. Acceptance bullets must be binary and testable. Test plans must list exact commands. Each issue must include exact do-not-touch constraints and preserve the V1 invariants above.

If a future implementer finds an issue still too broad, stop before coding and split it with `to-issues`; do not use a broad issue as permission to implement adjacent workflows.
