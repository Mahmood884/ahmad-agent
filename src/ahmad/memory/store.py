from pathlib import Path
import json


class MemoryStore:
    """Append-only event store.

    The store persists events exactly as supplied.
    It does not evaluate, modify, or authorize events.
    """

    def __init__(self, path: str | Path = "data/events.jsonl") -> None:
        self.path = Path(path)

    def append(self, event) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(event.to_json())
            handle.write("\n")

    def read_all(self) -> list[dict]:
        if not self.path.exists():
            return []

        with self.path.open("r", encoding="utf-8") as handle:
            return [
                json.loads(line)
                for line in handle
                if line.strip()
            ]
