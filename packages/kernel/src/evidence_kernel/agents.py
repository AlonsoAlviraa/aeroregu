from __future__ import annotations

MVP_AGENTS = ("reader", "checker", "refuter", "scribe", "decision_gate")
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
    if agent_id not in MVP_AGENTS:
        raise AgentRegistryError(agent_id)
    return agent_id
