"""Hermes adapter contract; no CLI or network transport is launched here."""

from ahmad.providers.base import ProviderAdapter


class HermesProvider(ProviderAdapter):
    name = "hermes"
