from langgraph.checkpoint.memory import InMemorySaver

from migration_factory.orchestrator.preflight import PreflightError


def default_checkpointer() -> InMemorySaver:
    return InMemorySaver()


def require_thread_id(config: dict, run_id: str) -> None:
    thread_id = config.get("configurable", {}).get("thread_id")
    if thread_id != run_id:
        raise PreflightError(f"thread_id must match run_id: {run_id}")
