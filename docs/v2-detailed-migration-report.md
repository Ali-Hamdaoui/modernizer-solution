# V2 Detailed Migration Report

The V2 migration cockpit enables report generation after every stage included
in the selected source-to-target profile route completes successfully and no
approval gate remains open. It does not require a separate accepted output
artifact revision; real one-step routes can generate a report from command
and event evidence when no stage artifacts were persisted.

Selecting **Generate report** creates JSON, Markdown, and PDF artifacts. The
browser automatically downloads the PDF; all three artifacts remain available
through their explicit download links.

The report contains:

- the detected source stack and selected/completed target stack;
- overall elapsed time and per-stage/phase timings;
- files and lines added, deleted, and changed for each included stage;
- aggregate test, build, transform, proof, and repair results;
- the persisted migration lifecycle timeline and event counts;
- an evidence-constrained migration story generated through the configured
  Azure OpenAI assistant deployment.

The model generates narrative only. Versions, route selection, timings, line
counts, statuses, and test totals come from deterministic persisted evidence.
If the Azure OpenAI call is unavailable, report generation continues with a
deterministic narrative.

Line metrics prefer persisted stage statistics. When those statistics are not
available, the report compares the source and output trees for each stage.
Binary files, generated build output, dependency caches, and files larger than
5 MiB are excluded from that comparison.
