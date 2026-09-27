"""Provider discovery only. Selection and registration grant no tool authority."""

from ahmad.providers.base import Provider


class ProviderRegistry:
    def __init__(self) -> None:
        self._providers: dict[str, Provider] = {}

    def register(self, provider: Provider) -> None:
        if provider.name in self._providers:
            raise ValueError(f"provider already registered: {provider.name}")
        self._providers[provider.name] = provider

    def get(self, name: str) -> Provider | None:
        return self._providers.get(name)

    def list(self) -> tuple[Provider, ...]:
        return tuple(self._providers.values())
