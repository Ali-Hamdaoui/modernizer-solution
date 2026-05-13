from migration_factory.orchestrator.state import MigrationState


def planning_node(state: MigrationState) -> MigrationState:
    return {
        "planning_status": "PASS",
        "current_unit": "planning",
    }
