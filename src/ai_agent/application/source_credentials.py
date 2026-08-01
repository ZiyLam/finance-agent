"""Safe status and maintenance operations for configured data-source tokens."""

from __future__ import annotations

from os import getenv

from ..data_sources import DataSourceDefinition, get_data_source, ordered_data_sources
from ..provider_activation import ProviderActivationError, ProviderActivationStore
from ..secrets import SecretStoreError, TokenStore


class SourceCredentialError(RuntimeError):
    """Safe credential-maintenance error that never includes a token value."""


class SourceCredentialService:
    """Manage per-user encrypted tokens without ever returning their plaintext."""

    def __init__(
        self,
        store: TokenStore | None = None,
        activation: ProviderActivationStore | None = None,
    ) -> None:
        self._store = store or TokenStore()
        self._activation = activation or ProviderActivationStore()

    def list_sources(self) -> list[dict[str, object]]:
        """Return catalog metadata and configuration state without token values."""

        return [self._status(definition) for definition in ordered_data_sources()]

    def set_token(self, source: str, token: str) -> dict[str, object]:
        """Encrypt and save a token for the current Windows user."""

        definition = self._definition(source)
        try:
            self._store.set_token(definition.name, token)
        except (OSError, ValueError, SecretStoreError) as error:
            raise SourceCredentialError("The token could not be saved to the secure local store.") from error
        return self._status(definition)

    def delete_token(self, source: str) -> dict[str, object]:
        """Delete one locally stored token; environment values are unaffected."""

        definition = self._definition(source)
        try:
            deleted = self._store.delete_token(definition.name)
        except (OSError, ValueError, SecretStoreError) as error:
            raise SourceCredentialError("The saved token could not be deleted.") from error
        result = self._status(definition)
        result["stored_token_deleted"] = deleted
        return result

    def set_enabled(self, source: str, enabled: bool) -> dict[str, object]:
        """Persist whether one external provider may be called at runtime."""

        definition = self._definition(source)
        try:
            self._activation.set_enabled(definition.name, enabled)
        except (OSError, ValueError, ProviderActivationError) as error:
            raise SourceCredentialError("The provider enablement setting could not be saved.") from error
        return self._status(definition)

    def _status(
        self,
        definition: DataSourceDefinition,
    ) -> dict[str, object]:
        environment_value = getenv(definition.token_environment_variable, "").strip()
        try:
            stored_token = self._store.get_token(definition.name)
        except (OSError, SecretStoreError) as error:
            raise SourceCredentialError("A saved token could not be read from the secure local store.") from error
        try:
            enabled = self._activation.is_enabled(definition.name)
        except (OSError, ProviderActivationError) as error:
            raise SourceCredentialError("Provider enablement settings could not be read.") from error

        if environment_value:
            configured, origin = True, "environment_variable"
        elif stored_token:
            configured, origin = True, "secure_local_store"
        else:
            configured, origin = False, "not_configured"
        result: dict[str, object] = {
            "name": definition.name,
            "display_name": definition.display_name,
            "configured": configured,
            "credential_origin": origin,
            "token_environment_variable": definition.token_environment_variable,
            "token_required_by_adapter": definition.token_required_by_adapter,
            "status_description": definition.status_description or None,
            "base_url_environment_variable": definition.base_url_environment_variable,
            "tags": sorted(tag.value for tag in definition.tags),
            "routing_priority": definition.routing_priority,
            "latency_class": definition.latency_class.value,
            "configuration_group": definition.configuration_group.value,
            "enabled": enabled,
        }
        return result

    @staticmethod
    def _definition(source: str) -> DataSourceDefinition:
        definition = get_data_source(source)
        if definition is None:
            raise ValueError("Unknown data source")
        return definition
