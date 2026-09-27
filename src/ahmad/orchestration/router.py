from ahmad.core.types import Mode


class Router:
    def route(self, request: str) -> Mode:
        text = request.lower()

        if any(
            word in text
            for word in ("security", "audit", "vulnerability")
        ):
            return Mode.SECURITY

        if any(
            word in text
            for word in ("research", "search", "investigate")
        ):
            return Mode.RESEARCH

        return Mode.GENERAL
