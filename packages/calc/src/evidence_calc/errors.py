class AbstainError(Exception):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason
        self.escalate_to = "human_engineer"
