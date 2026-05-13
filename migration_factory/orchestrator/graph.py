from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from migration_factory.analysis_agent.node import analysis_node
from migration_factory.orchestrator.approval import approval_node
from migration_factory.orchestrator.state import MigrationState
from migration_factory.planning_agent.node import planning_node
from migration_factory.transformation_agent.node import transformation_node


def build_graph():
    graph = StateGraph(MigrationState)
    graph.add_node("analysis", analysis_node)
    graph.add_node("planning", planning_node)
    graph.add_node("approval", approval_node)
    graph.add_node("transformation", transformation_node)

    graph.add_edge(START, "analysis")
    graph.add_edge("analysis", "planning")
    graph.add_edge("planning", "approval")
    graph.add_edge("approval", "transformation")
    graph.add_edge("transformation", END)

    return graph.compile(checkpointer=InMemorySaver())
