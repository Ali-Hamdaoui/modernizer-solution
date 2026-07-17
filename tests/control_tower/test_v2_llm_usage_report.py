from __future__ import annotations

import sqlite3
from pathlib import Path
from types import SimpleNamespace

from migration_factory.control_tower.application.v2_llm_invocation_ledger import V2LLMInvocationLedger
from migration_factory.control_tower.application.v2_llm_usage import build_llm_usage_summary
from migration_factory.control_tower.application.v2_migration_report import _llm_usage_for_job, render_detailed_report_markdown
from migration_factory.control_tower.infrastructure.sqlite.v2_llm_invocation_repository import (
    SqliteV2LLMInvocationRepository,
)


MIGRATION_PATH = Path(
    "migration_factory/control_tower/infrastructure/sqlite/migrations/0050_v2_llm_invocations.sql"
)


def test_usage_is_persisted_aggregated_with_decimal_prices_and_rendered(tmp_path: Path) -> None:
    connection = sqlite3.connect(tmp_path / "usage.sqlite3")
    connection.row_factory = sqlite3.Row
    connection.executescript(MIGRATION_PATH.read_text(encoding="utf-8"))
    repository = SqliteV2LLMInvocationRepository(connection)
    ledger = V2LLMInvocationLedger(repository)

    first = ledger.start_invocation(job_id="job-usage", role="main", responsibility="explanation")
    ledger.complete_invocation(
        first,
        output="first output",
        prompt_tokens=2_500,
        completion_tokens=500,
        total_tokens=3_000,
    )
    second = ledger.start_invocation(job_id="job-usage", role="reviewer", responsibility="repair_review")
    ledger.complete_invocation(
        second,
        output="second output",
        prompt_tokens=1_500,
        completion_tokens=250,
        total_tokens=1_750,
    )

    usage = build_llm_usage_summary(repository.list_by_job("job-usage"))

    assert usage["model_or_deployment"] == "GPT-5 mini"
    assert usage["currency"] == "USD"
    assert usage["input_tokens"] == 4_000
    assert usage["output_tokens"] == 750
    assert usage["total_tokens"] == 4_750
    assert usage["input_cost"] == "0.00100"
    assert usage["output_cost"] == "0.0015000"
    assert usage["total_estimated_cost"] == "0.0025000"

    report_narrative = ledger.start_invocation(
        job_id="job-usage",
        role="main",
        responsibility="explanation",
        schema_name="DetailedMigrationReportNarrative",
    )
    ledger.complete_invocation(
        report_narrative,
        output="report narrative",
        prompt_tokens=100,
        completion_tokens=50,
        total_tokens=150,
    )
    job_usage = _llm_usage_for_job(
        SimpleNamespace(v2_llm_invocations=repository), "job-usage"
    )
    assert (job_usage["input_tokens"], job_usage["output_tokens"], job_usage["total_tokens"]) == (4_100, 800, 4_900)

    report = {
        "migration_scope": {},
        "summary": {},
        "stages": [],
        "timeline": [],
        "event_counts": {},
        "llm_token_usage": usage,
    }
    markdown = render_detailed_report_markdown(report)

    assert "## LLM Token Usage and Estimated Cost" in markdown
    assert "Total input tokens: 4000" in markdown
    assert "Total estimated cost: $0.0025000" in markdown
    assert usage["note"] in markdown


def test_response_usage_ignores_cached_and_reasoning_tokens() -> None:
    from migration_factory.control_tower.application.v2_assistant_model_client import _completion_from_response

    completion = _completion_from_response(
        {
            "usage": {
                "input_tokens": 12,
                "output_tokens": 7,
                "total_tokens": 19,
                "input_tokens_details": {"cached_tokens": 999},
                "output_tokens_details": {"reasoning_tokens": 111},
            }
        },
        "ok",
    )

    assert completion.input_tokens == 12
    assert completion.output_tokens == 7
    assert completion.total_tokens == 19
