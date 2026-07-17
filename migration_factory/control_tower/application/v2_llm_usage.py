"""Token usage aggregation and GPT-5 mini estimated-cost calculation."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Iterable


INPUT_PRICE_PER_1M_TOKENS = Decimal("0.25")
OUTPUT_PRICE_PER_1M_TOKENS = Decimal("2.00")
CURRENCY = "USD"
MODEL_LABEL = "GPT-5 mini"
_ONE_MILLION = Decimal("1000000")
ESTIMATE_NOTE = (
    "Estimated cost is calculated from captured API usage metadata and hardcoded "
    "GPT-5 mini token prices. It may differ from the final Azure invoice because "
    "Azure pricing can depend on region, deployment, billing agreement, rounding, "
    "retries, failed requests, or additional service charges."
)


def build_llm_usage_summary(records: Iterable[Any]) -> dict[str, Any]:
    """Aggregate captured invocation usage and calculate an estimated USD cost.

    Costs are deliberately calculated with :class:`Decimal`, never floats. Only
    input, output, and total token fields are read; cached and reasoning tokens
    are intentionally ignored.
    """

    input_tokens = output_tokens = total_tokens = 0
    for record in records:
        input_tokens += _non_negative_int(getattr(record, "prompt_tokens", None))
        output_tokens += _non_negative_int(getattr(record, "completion_tokens", None))
        total_tokens += _non_negative_int(getattr(record, "total_tokens", None))

    input_cost = Decimal(input_tokens) / _ONE_MILLION * INPUT_PRICE_PER_1M_TOKENS
    output_cost = Decimal(output_tokens) / _ONE_MILLION * OUTPUT_PRICE_PER_1M_TOKENS
    total_cost = input_cost + output_cost
    return {
        "model_or_deployment": MODEL_LABEL,
        "currency": CURRENCY,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "input_price_per_1m_tokens": _decimal_text(INPUT_PRICE_PER_1M_TOKENS),
        "output_price_per_1m_tokens": _decimal_text(OUTPUT_PRICE_PER_1M_TOKENS),
        "input_cost": _decimal_text(input_cost),
        "output_cost": _decimal_text(output_cost),
        "total_estimated_cost": _decimal_text(total_cost),
        "note": ESTIMATE_NOTE,
    }


def _non_negative_int(value: Any) -> int:
    return int(value) if isinstance(value, int) and value >= 0 else 0


def _decimal_text(value: Decimal) -> str:
    return format(value, "f")
