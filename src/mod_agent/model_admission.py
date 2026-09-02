"""Shared read-only local model identity admission without generation."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.libs.llm import validate_loopback_http_base_url


class ModelAdmissionError(RuntimeError):
    """A read-only local model identity or context gate failed."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def read_ollama_model_identity(base_url: str, model: str) -> dict[str, Any]:
    normalized = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized}/api/tags")
        if response.status_code != 200:
            raise ModelAdmissionError(
                f"OLLAMA_MODEL_CATALOG_HTTP_{response.status_code}"
            )
        payload = response.json()
    except ModelAdmissionError:
        raise
    except Exception as exc:
        raise ModelAdmissionError(
            f"OLLAMA_MODEL_CATALOG_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    return select_ollama_model_identity(
        payload,
        base_url=normalized,
        expected_model=model,
    )


def read_ollama_server_version(base_url: str) -> str:
    normalized = validate_loopback_http_base_url(base_url)
    try:
        import httpx

        with httpx.Client(
            timeout=10.0,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.get(f"{normalized}/api/version")
        if response.status_code != 200:
            raise ModelAdmissionError(
                f"OLLAMA_SERVER_VERSION_HTTP_{response.status_code}"
            )
        payload = response.json()
    except ModelAdmissionError:
        raise
    except Exception as exc:
        raise ModelAdmissionError(
            f"OLLAMA_SERVER_VERSION_UNAVAILABLE:{type(exc).__name__}"
        ) from exc
    if not isinstance(payload, dict):
        raise ModelAdmissionError("OLLAMA_SERVER_VERSION_SHAPE_INVALID")
    version = payload.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ModelAdmissionError("OLLAMA_SERVER_VERSION_MISSING")
    return version


def select_ollama_model_identity(
    payload: Any,
    *,
    base_url: str,
    expected_model: str,
) -> dict[str, Any]:
    if not isinstance(payload, dict) or not isinstance(payload.get("models"), list):
        raise ModelAdmissionError("OLLAMA_MODEL_CATALOG_SHAPE_INVALID")
    if not payload["models"]:
        raise ModelAdmissionError("OLLAMA_MODEL_LIST_EMPTY")
    matches = [
        item
        for item in payload["models"]
        if isinstance(item, dict) and item.get("name") == expected_model
    ]
    if len(matches) != 1:
        raise ModelAdmissionError("OLLAMA_MODEL_NOT_EXACTLY_PRESENT")
    selected = matches[0]
    identity = {
        "name": selected.get("name"),
        "model": selected.get("model"),
        "digest": selected.get("digest"),
        "modified_at": selected.get("modified_at"),
        "size": selected.get("size"),
        "details": selected.get("details"),
        "capabilities": selected.get("capabilities"),
        "base_url": base_url,
    }
    validate_ollama_model_identity(
        identity,
        expected_base_url=base_url,
        expected_model=expected_model,
    )
    return identity


def validate_ollama_model_identity(
    identity: Mapping[str, Any],
    *,
    expected_base_url: str,
    expected_model: str,
) -> None:
    if identity.get("name") != expected_model:
        raise ModelAdmissionError("OLLAMA_MODEL_NAME_MISMATCH")
    if identity.get("model") != expected_model:
        raise ModelAdmissionError("OLLAMA_MODEL_IDENTITY_MISMATCH")
    if identity.get("base_url") != expected_base_url:
        raise ModelAdmissionError("OLLAMA_MODEL_BASE_URL_MISMATCH")
    digest = identity.get("digest")
    if (
        not isinstance(digest, str)
        or len(digest) != 64
        or any(character not in "0123456789abcdef" for character in digest)
    ):
        raise ModelAdmissionError("OLLAMA_MODEL_DIGEST_INVALID")
    if not isinstance(identity.get("details"), dict):
        raise ModelAdmissionError("OLLAMA_MODEL_DETAILS_INVALID")
    capabilities = identity.get("capabilities")
    if not isinstance(capabilities, list) or not all(
        isinstance(item, str) for item in capabilities
    ):
        raise ModelAdmissionError("OLLAMA_MODEL_CAPABILITIES_INVALID")


def validate_ollama_context_window(
    identity: Mapping[str, Any],
    *,
    requested_context_window: int | None,
) -> int:
    if (
        requested_context_window is None
        or isinstance(requested_context_window, bool)
        or not isinstance(requested_context_window, int)
        or requested_context_window <= 0
    ):
        raise ModelAdmissionError("OLLAMA_CONTEXT_WINDOW_INVALID")
    details = identity.get("details")
    context_limit = (
        details.get("context_length") if isinstance(details, Mapping) else None
    )
    if (
        isinstance(context_limit, bool)
        or not isinstance(context_limit, int)
        or context_limit <= 0
    ):
        raise ModelAdmissionError("OLLAMA_MODEL_CONTEXT_LENGTH_INVALID")
    if requested_context_window > context_limit:
        raise ModelAdmissionError("OLLAMA_CONTEXT_WINDOW_EXCEEDS_MODEL_LIMIT")
    return context_limit


def assert_ollama_model_identity_stable(
    *, expected: Mapping[str, Any], observed: Mapping[str, Any]
) -> None:
    """Reject exact model-name or digest drift across one admitted run."""

    if expected.get("name") != observed.get("name"):
        raise ModelAdmissionError("OLLAMA_MODEL_NAME_DRIFT")
    if expected.get("digest") != observed.get("digest"):
        raise ModelAdmissionError("OLLAMA_MODEL_DIGEST_DRIFT")


def local_no_external_disclosure_record() -> dict[str, Any]:
    """Expose the existing exact local no-disclosure projection read-only."""

    return {
        "occurred": False,
        "approved": False,
        "approved_at": None,
        "approval_id": None,
        "approval_actor_type": None,
        "consent_mechanism": None,
        "provider_adapter": None,
        "destination": None,
        "approved_data_classes": [],
        "requested_data_classes": [],
        "scope": "this_run_only",
        "reason": "local_model_execution",
    }


def local_model_admission_record(
    *, model_identity: Mapping[str, Any], provider_adapter: str
) -> dict[str, Any]:
    """Expose the existing exact local model-admission projection read-only."""

    base_url = str(model_identity["base_url"])
    return {
        "provider": "ollama",
        "model": str(model_identity["name"]),
        "model_digest": str(model_identity["digest"]),
        "provider_adapter": provider_adapter,
        "execution_locality": "local",
        "base_url": base_url,
        "destination": f"{base_url}/api/chat",
        "external_disclosure_occurred": False,
        "api_key_required": False,
        "api_key_read": False,
        "api_key_persisted": False,
        "automatic_provider_fallback": False,
        "automatic_external_retry": False,
        "data_processing_location": "machine_local",
    }
