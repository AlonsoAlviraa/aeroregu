from __future__ import annotations

MVP_AGENTS = ("reader", "checker", "refuter", "scribe", "decision_gate")
IMPLEMENTED_LATER_AGENTS = ("envelope_critic", "bench_attacker")
ACTIVE_AGENTS = MVP_AGENTS + IMPLEMENTED_LATER_AGENTS
LATER_AGENTS = (
    "moc_drafter",
    "envelope_critic",
    "change_narrator",
    "criterion_librarian",
    "connector_exporter",
    "qualification_clerk",
    "bench_attacker",
    "tenant_policy",
)


class AgentRegistryError(KeyError):
    pass


def require_mvp_agent(agent_id: str) -> str:
    if agent_id not in ACTIVE_AGENTS:
        raise AgentRegistryError(agent_id)
    return agent_id


def require_active_agent(agent_id: str) -> str:
    if agent_id not in ACTIVE_AGENTS:
        raise AgentRegistryError(agent_id)
    return agent_id
