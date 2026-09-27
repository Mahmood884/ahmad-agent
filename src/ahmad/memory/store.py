from pathlib import Path


class MemoryStore:
    """
    Placeholder for event-sourced memory.
    Events will become the source of truth.
    """

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, event: dict) -> None:
        raise NotImplementedError(
            "Event store not implemented yet"
        )
