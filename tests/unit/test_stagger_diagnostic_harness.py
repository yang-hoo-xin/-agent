from __future__ import annotations

import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from src.mod_agent.runtime import GTFORealRuntimeProfile
from src.mod_agent.runtime import stagger_diagnostic_harness as module


def test_isolated_diagnostic_routes_outputs_without_touching_prior_run(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    prior_run = tmp_path / "run_001"
    prior_capture = prior_run / "runtime_captures"
    prior_capture.mkdir(parents=True)
    (prior_run / "runtime_result.json").write_bytes(b"prior result")
    (prior_capture / "prior.png").write_bytes(b"prior screenshot")
    prior_bytes = {
        path.relative_to(prior_run).as_posix(): path.read_bytes()
        for path in prior_run.rglob("*")
        if path.is_file()
    }
    output_root = tmp_path / "run_003"
    output_root.mkdir()
    settings = tmp_path / "runtime.yaml"
    settings.write_text("runtime: isolated\n", encoding="utf-8")
    build_dll = tmp_path / "BetterHitFeedback.dll"
    build_dll.write_bytes(b"diagnostic dll")
    config = tmp_path / "diagnostic.cfg"
    config.write_bytes(b"diagnostic config")

    monkeypatch.setattr(module, "load_settings", lambda _: object())
    monkeypatch.setattr(
        module,
        "profile_from_settings",
        lambda *_args, **_kwargs: GTFORealRuntimeProfile(
            profile_id="base",
            game_executable=str(tmp_path / "GTFO.exe"),
            working_directory=str(tmp_path),
        ),
    )

    @contextmanager
    def deployment(**_kwargs: Any):
        yield SimpleNamespace()

    monkeypatch.setattr(
        module,
        "temporarily_deploy_verified_plugin",
        deployment,
    )
    monkeypatch.setattr(
        module,
        "temporarily_deploy_gtfo_config",
        deployment,
    )
    monkeypatch.setattr(
        module,
        "bind_stagger_attempt_restoration",
        lambda payload, **_kwargs: dict(payload),
    )

    class Runner:
        def run(self, **kwargs: Any) -> dict[str, Any]:
            screenshot_directory = Path(
                kwargs["profile"].screenshot_directory
            )
            screenshot_directory.mkdir(parents=True)
            (screenshot_directory / "capture.png").write_bytes(b"new")
            process_directory = kwargs[
                "process_diagnostic_directory"
            ]
            process_directory.mkdir(parents=True)
            (process_directory / "stdout.log").write_bytes(b"")
            current_run_log = tmp_path / "GTFO.LogOutput.log"
            current_run_log.write_bytes(
                b"CURRENT_RUN_ONLY\nPOST_MARKER_SHUTDOWN\n"
            )
            observed_prefix = b"CURRENT_RUN_ONLY\n"
            return {
                "feature_id": kwargs["feature_id"],
                "verification_status": "inconclusive",
                "raw_supplied_output": "CURRENT_RUN_ONLY\n",
                "runtime_trust_binding": {
                    "checks": {
                        "current_run_logs": {
                            "source_windows": [
                                {
                                    "generation": 2,
                                    "mode": (
                                        "created_or_truncated_after_"
                                        "prelaunch_boundary"
                                    ),
                                    "path": str(current_run_log.resolve()),
                                    "run_local_sha256": module.hashlib.sha256(
                                        observed_prefix
                                    ).hexdigest(),
                                    "run_local_size_bytes": len(
                                        observed_prefix
                                    ),
                                    "run_local_start_byte": 0,
                                    "status": "passed",
                                }
                            ]
                        }
                    }
                },
            }

    result = module.run_isolated_stagger_hud_parent_diagnostic(
        output_root=output_root.resolve(),
        run_id="run_003",
        feature_id="feature_stagger",
        settings_path=settings.resolve(),
        build_dll_path=build_dll.resolve(),
        diagnostic_config_path=config.resolve(),
        dll_destination_path=(tmp_path / "game" / "plugin.dll").resolve(),
        config_destination_path=(tmp_path / "game" / "config.cfg").resolve(),
        diagnostic_criterion="Observe the parent chain.",
        diagnostic_marker="signal=STAGGER_PARENT_CHAIN",
        allow_game_launch=False,
        allow_game_directory_write=False,
        runner=Runner(),
    )

    assert result["run_id"] == "run_003"
    assert result["diagnostic_run_identity"]["output_root"] == str(
        output_root.resolve()
    )
    assert (
        json.loads(
            (output_root / "runtime_result.json").read_text(
                encoding="utf-8"
            )
        )["run_id"]
        == "run_003"
    )
    assert (output_root / "runtime_captures" / "capture.png").is_file()
    assert (output_root / "process_diagnostics" / "stdout.log").is_file()
    assert (
        output_root / "LogOutput.current_run.log"
    ).read_text(encoding="utf-8") == "CURRENT_RUN_ONLY\n"
    assert (
        output_root / "LogOutput.post_run_full_copy.log"
    ).read_text(encoding="utf-8") == (
        "CURRENT_RUN_ONLY\nPOST_MARKER_SHUTDOWN\n"
    )
    assert result["diagnostic_run_identity"][
        "full_log_post_run_copy"
    ]["observed_prefix_verified"] is True
    assert result["diagnostic_run_identity"][
        "full_log_post_run_copy"
    ]["provenance"] == "post_run_copy_of_current_run_generation"
    assert result["diagnostic_run_identity"]["current_run_log_sha256"] == (
        module._sha256(output_root / "LogOutput.current_run.log")
    )
    assert {
        path.relative_to(prior_run).as_posix(): path.read_bytes()
        for path in prior_run.rglob("*")
        if path.is_file()
    } == prior_bytes


def test_isolated_diagnostic_rejects_nonempty_output_root(
    tmp_path: Path,
) -> None:
    output_root = tmp_path / "run_003"
    output_root.mkdir()
    (output_root / "existing.txt").write_text("occupied", encoding="utf-8")

    with pytest.raises(
        module.StaggerDiagnosticHarnessError,
        match="must be empty",
    ):
        module.run_isolated_stagger_hud_parent_diagnostic(
            output_root=output_root.resolve(),
            run_id="run_003",
            feature_id="feature_stagger",
            settings_path=(tmp_path / "missing.yaml").resolve(),
            build_dll_path=(tmp_path / "missing.dll").resolve(),
            diagnostic_config_path=(tmp_path / "missing.cfg").resolve(),
            dll_destination_path=(tmp_path / "game" / "plugin.dll").resolve(),
            config_destination_path=(tmp_path / "game" / "config.cfg").resolve(),
            diagnostic_criterion="Observe the parent chain.",
            diagnostic_marker="signal=STAGGER_PARENT_CHAIN",
            allow_game_launch=False,
            allow_game_directory_write=False,
        )
