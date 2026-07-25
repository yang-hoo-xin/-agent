"""Runtime evidence contracts for controlled workflow verification."""

from .evidence import (
    RuntimeEvidenceError,
    RuntimeEvidenceItem,
    build_fake_runtime_evidence_payload,
    build_manual_runtime_evidence_payload,
    build_real_runtime_evidence_payload,
    build_supplied_runtime_evidence_payload,
    bind_runtime_evidence_context,
)
from .deployment import (
    RuntimePluginDeploymentError,
    RuntimePluginDeploymentRecord,
    bind_plugin_deployment_to_runtime_payload,
    temporarily_deploy_verified_plugin,
)
from .gtfo_automation import (
    GTFOLogSnapshot,
    GTFOProcessHandle,
    GTFORealRuntimeAutomationRunner,
    GTFORealRuntimeProfile,
    GTFORuntimeAutomationError,
    build_gtfo_runtime_capability_report,
    make_gtfo_runtime_evidence_factory,
    make_gtfo_runtime_evidence_factory_from_settings,
    profile_from_settings,
)
from .probe import (
    RuntimeProbeCommandResult,
    RuntimeProbeError,
    RuntimeProbeProfile,
    RuntimeProbeRunner,
    make_runtime_probe_evidence_factory,
)
from .screenshots import (
    ScreenshotMetadata,
    ScreenshotRegistryError,
    build_screenshot_metadata,
    build_screenshot_registry_payload,
    screenshot_registry_to_runtime_item,
)

__all__ = [
    "RuntimeEvidenceError",
    "RuntimeEvidenceItem",
    "RuntimePluginDeploymentError",
    "RuntimePluginDeploymentRecord",
    "GTFOLogSnapshot",
    "GTFOProcessHandle",
    "GTFORealRuntimeAutomationRunner",
    "GTFORealRuntimeProfile",
    "GTFORuntimeAutomationError",
    "RuntimeProbeCommandResult",
    "RuntimeProbeError",
    "RuntimeProbeProfile",
    "RuntimeProbeRunner",
    "ScreenshotMetadata",
    "ScreenshotRegistryError",
    "build_fake_runtime_evidence_payload",
    "build_gtfo_runtime_capability_report",
    "build_manual_runtime_evidence_payload",
    "build_real_runtime_evidence_payload",
    "build_screenshot_metadata",
    "build_screenshot_registry_payload",
    "build_supplied_runtime_evidence_payload",
    "bind_runtime_evidence_context",
    "bind_plugin_deployment_to_runtime_payload",
    "make_gtfo_runtime_evidence_factory",
    "make_gtfo_runtime_evidence_factory_from_settings",
    "make_runtime_probe_evidence_factory",
    "profile_from_settings",
    "screenshot_registry_to_runtime_item",
    "temporarily_deploy_verified_plugin",
]
