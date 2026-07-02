"""Screenshot registry payload builders for runtime visual evidence."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


class ScreenshotRegistryError(ValueError):
    """Raised when screenshot metadata is unsafe or malformed."""


@dataclass(frozen=True)
class ScreenshotMetadata:
    """Metadata for one screenshot without claiming runtime acceptance."""

    screenshot_id: str
    feature_id: str
    file_path: str
    source: str
    captured_at: str | None = None
    caption: str | None = None
    caption_status: str = "missing"
    metadata: Mapping[str, Any] | None = None
    content_hash: str | None = None
    supports_acceptance: tuple[str, ...] = ()
    confidence: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Return the DEV_SPEC 15.4 screenshot registry row shape."""

        return {
            "screenshot_id": self.screenshot_id,
            "feature_id": self.feature_id,
            "file_path": self.file_path,
            "source": self.source,
            "captured_at": self.captured_at,
            "caption": self.caption,
            "caption_status": self.caption_status,
            "metadata": dict(self.metadata or {}),
            "content_hash": self.content_hash,
            "supports_acceptance": list(self.supports_acceptance),
            "confidence": self.confidence,
            "verification_status": "visual_evidence_only",
        }


def build_screenshot_metadata(
    *,
    screenshot_id: str,
    feature_id: str,
    file_path: str,
    source: str,
    captured_at: str | None = None,
    caption: str | None = None,
    caption_status: str | None = None,
    metadata: Mapping[str, Any] | None = None,
    content_hash: str | None = None,
    supports_acceptance: Iterable[str] = (),
    confidence: float = 0.0,
) -> ScreenshotMetadata:
    """Build one screenshot metadata record.

    The record may carry visual hints, but it does not verify runtime acceptance.
    """

    if not screenshot_id:
        raise ScreenshotRegistryError("screenshot_id is required")
    if not feature_id:
        raise ScreenshotRegistryError("feature_id is required")
    if not file_path:
        raise ScreenshotRegistryError("file_path is required")
    if not source:
        raise ScreenshotRegistryError("source is required")
    normalized_caption_status = _caption_status(
        caption=caption,
        caption_status=caption_status,
    )
    if confidence < 0.0 or confidence > 1.0:
        raise ScreenshotRegistryError("confidence must be between 0.0 and 1.0")
    return ScreenshotMetadata(
        screenshot_id=screenshot_id,
        feature_id=feature_id,
        file_path=file_path,
        source=source,
        captured_at=captured_at,
        caption=caption,
        caption_status=normalized_caption_status,
        metadata=dict(metadata or {}),
        content_hash=content_hash,
        supports_acceptance=tuple(supports_acceptance),
        confidence=confidence,
    )


def build_screenshot_registry_payload(
    *,
    feature_id: str,
    screenshots: Iterable[ScreenshotMetadata],
) -> dict[str, Any]:
    """Build a screenshot_registry artifact payload."""

    items = tuple(screenshots)
    if any(item.feature_id != feature_id for item in items):
        raise ScreenshotRegistryError(
            "All screenshot metadata records must match feature_id"
        )
    captioned_count = sum(1 for item in items if item.caption)
    missing_caption_count = sum(1 for item in items if not item.caption)
    return {
        "node_name": "register_runtime_screenshots",
        "stage": "runtime_evidence",
        "message": (
            "Runtime screenshots were registered as visual evidence only. "
            "They do not prove gameplay acceptance without separate runtime evidence."
        ),
        "feature_id": feature_id,
        "screenshot_count": len(items),
        "captioned_count": captioned_count,
        "missing_caption_count": missing_caption_count,
        "screenshots": [item.to_dict() for item in items],
        "verification_status": "inconclusive",
        "acceptance_status": "visual_evidence_only",
        "claims_real_runtime_success": False,
        "limitations": [
            "Screenshot metadata alone cannot verify that the requested gameplay behavior occurred.",
            "Caption text is auxiliary evidence and requires separate runtime or manual verification.",
        ],
    }


def screenshot_registry_to_runtime_item(
    screenshot: ScreenshotMetadata,
) -> dict[str, Any]:
    """Represent screenshot metadata as a runtime evidence item without acceptance."""

    return {
        "type": "screenshot",
        "source": screenshot.source,
        "locator": screenshot.file_path,
        "supports_acceptance": [],
        "confidence": 0.0,
        "raw_excerpt": screenshot.caption,
        "screenshot_id": screenshot.screenshot_id,
    }


def _caption_status(*, caption: str | None, caption_status: str | None) -> str:
    if caption_status is None:
        return "supplied" if caption else "missing"
    allowed = {"missing", "supplied", "generated", "low_confidence", "failed"}
    if caption_status not in allowed:
        raise ScreenshotRegistryError(
            f"Unsupported caption_status: {caption_status}"
        )
    if caption_status == "missing" and caption:
        raise ScreenshotRegistryError("caption_status cannot be missing when caption exists")
    if caption_status != "missing" and not caption:
        raise ScreenshotRegistryError(
            "caption_status requires caption unless the status is missing"
        )
    return caption_status
