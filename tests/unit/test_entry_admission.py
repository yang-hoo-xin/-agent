from __future__ import annotations

import hashlib
import inspect
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

import src.mod_agent.entry_admission as entry_module
import src.mod_agent.git.admission as git_admission_module
from src.mod_agent.entry_admission import (
    EntryAdmissionDependenciesV1,
    EntryAdmissionRequestV1,
    EntryAdmissionResultV1,
    admit_sealed_entry,
    verify_entry_admission_receipt,
)
from src.mod_agent.git.admission import GitExecutableIdentityV1, StrictGitAdmission
from src.mod_agent.model_admission import ModelAdmissionError
from src.mod_agent.product_executor import source_snapshot, source_snapshot_sha256


def _git_executable() -> Path:
    selected = shutil.which("git")
    assert selected is not None
    return Path(selected).resolve()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        (str(_git_executable()), "-C", str(root), *args),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout.rstrip("\r\n")


def _initialize_repository(root: Path) -> None:
    root.mkdir(parents=True)
    _git(root.parent, "init", str(root))
    _git(root, "config", "user.email", "test@example.invalid")
    _git(root, "config", "user.name", "Test")
    _git(root, "config", "core.autocrlf", "false")


def _fixture(tmp_path: Path) -> tuple[
    EntryAdmissionRequestV1, EntryAdmissionDependenciesV1
]:
    platform = tmp_path / "platform"
    _initialize_repository(platform)
    (platform / "README.md").write_text("platform\n", encoding="utf-8")
    _git(platform, "add", ".")
    _git(platform, "commit", "-m", "platform")

    source_root = tmp_path / "source"
    _initialize_repository(source_root)
    project = source_root / "NeutralProject"
    project.mkdir()
    (project / "NeutralProject.csproj").write_text("<Project />\n", encoding="utf-8")
    (project / "Entry.cs").write_text("sealed class Entry {}\n", encoding="utf-8")
    _git(source_root, "add", ".")
    _git(source_root, "commit", "-m", "source")
    snapshot = source_snapshot(project)
    binding = {
        "binding_version": "product_source_revision_binding_v2",
        "complete_snapshot_sha256": source_snapshot_sha256(snapshot),
        "repository_head": _git(source_root, "rev-parse", "HEAD"),
        "repository_tree": _git(source_root, "rev-parse", "HEAD^{tree}"),
        "project_root": "NeutralProject",
        "project_file": "NeutralProject/NeutralProject.csproj",
        "project_tree": _git(source_root, "rev-parse", "HEAD:NeutralProject"),
        "primary_sources": [
            {
                "path": "NeutralProject/Entry.cs",
                "sha256": hashlib.sha256((project / "Entry.cs").read_bytes()).hexdigest(),
            }
        ],
    }

    packet_root = tmp_path / "packet"
    packet_root.mkdir()
    output_canonical = packet_root / "fresh_preflight_root"
    output_text = str(output_canonical).replace("/", "\\")
    identity = GitExecutableIdentityV1.read(_git_executable())
    request = EntryAdmissionRequestV1(
        contract_version="1",
        outer_run_id="outer_001",
        attempt_id="attempt_1",
        payload_manifest_sha256="a" * 64,
        packet_root_text=str(packet_root).replace("/", "\\"),
        packet_root_canonical_text=packet_root.resolve().as_posix(),
        output_root_text=output_text,
        output_root_canonical_text=output_canonical.as_posix(),
        platform_root=str(platform),
        platform_checkpoint=_git(platform, "rev-parse", "HEAD"),
        platform_branch=_git(platform, "branch", "--show-current"),
        allowed_dirty_paths=(),
        source_declared_root=source_root.as_posix(),
        source_canonical_root=source_root.resolve().as_posix(),
        target_project=str(project),
        source_revision_binding=binding,
        git_executable_identity=identity,
        ollama_base_url="http://127.0.0.1:11434",
        ollama_model="local-neutral-model",
        ollama_digest="b" * 64,
        ollama_server_version="1.2.3",
        ollama_context_window=32768,
        ollama_output_budget=4096,
    )
    git_admission = request.strict_git_admission()
    dependencies = EntryAdmissionDependenciesV1(
        git_admission=git_admission,
        model_identity_reader=lambda base_url, model: {
            "name": model,
            "model": model,
            "digest": "b" * 64,
            "base_url": base_url,
            "details": {"context_length": 65536},
            "capabilities": ["completion"],
        },
        server_version_reader=lambda _base_url: "1.2.3",
        context_validator=lambda identity, requested_context_window: identity[
            "details"
        ]["context_length"],
    )
    return request, dependencies


def test_ready_entry_writes_strict_receipt_and_roundtrips(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "ready"
    assert run.result.attempt_consumed is False
    assert run.result.model_calls == 0
    assert run.result.ProductExecution_runs == 0
    assert run.result.Builds == 0
    assert run.result.execution_root_created is False
    assert run.result.actual_authorized is False
    assert EntryAdmissionRequestV1.from_dict(request.to_dict()) == request
    assert EntryAdmissionResultV1.from_dict(run.result.to_dict()) == run.result
    assert run.receipt_path is not None and run.receipt_sha256 is not None
    assert verify_entry_admission_receipt(
        request,
        receipt_path=Path(run.receipt_path).as_posix(),
        expected_sha256=run.receipt_sha256,
    ) == run.result


def test_slash_and_backslash_output_paths_share_physical_identity(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "ready"
    assert Path(run.receipt_path).parent == Path(
        request.output_root_canonical_text
    ).resolve()


def test_windows_case_equivalent_output_leaf_is_accepted(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)
    request = replace(
        request,
        output_root_text=str(Path(request.packet_root_text) / "FRESH_PREFLIGHT_ROOT"),
    )

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "ready"


def test_different_output_leaf_is_rejected_without_receipt(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)
    request = replace(
        request,
        output_root_text=str(Path(request.packet_root_text) / "different_leaf"),
    )

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "blocked"
    assert run.result.first_failure_code == "ENTRY_OUTPUT_ROOT_LEAF_DRIFT"
    assert run.receipt_path is None


def test_symlink_packet_parent_is_rejected_without_receipt(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)
    link = tmp_path / "packet_link"
    try:
        link.symlink_to(Path(request.packet_root_canonical_text), target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are not available in this Windows context")
    request = replace(
        request,
        packet_root_text=str(link),
        output_root_text=str(link / "fresh_preflight_root"),
    )

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "blocked"
    assert run.result.first_failure_code == "ENTRY_OUTPUT_ROOT_SYMLINK_FORBIDDEN"
    assert run.receipt_path is None


@pytest.mark.parametrize(
    "output",
    ["relative/output", "../escape", "different_parent/output"],
)
def test_invalid_output_root_blocks_without_receipt(
    tmp_path: Path, output: str
) -> None:
    request, dependencies = _fixture(tmp_path)
    if output == "different_parent/output":
        value = (tmp_path / "different" / "output").as_posix()
        (tmp_path / "different").mkdir()
    else:
        value = output
    request = replace(
        request,
        output_root_text=value,
        output_root_canonical_text=value,
    )

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "blocked"
    assert run.result.first_failure_stage == "output_root"
    assert run.receipt_path is None
    assert not Path(value).exists() if Path(value).is_absolute() else True


def test_later_gate_failure_writes_bounded_receipt(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)

    def fail_model(_base_url: str, _model: str):
        raise ModelAdmissionError("OLLAMA_MODEL_CATALOG_UNAVAILABLE:Injected")

    dependencies = replace(dependencies, model_identity_reader=fail_model)
    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "blocked"
    assert run.result.first_failure_stage == "model_admission"
    assert run.receipt_path is not None
    assert Path(run.receipt_path).is_file()
    assert run.result.model_calls == 0
    assert EntryAdmissionResultV1.from_dict(run.result.to_dict()) == run.result


def test_receipt_write_failure_returns_total_blocked_outcome(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request, dependencies = _fixture(tmp_path)
    monkeypatch.setattr(
        entry_module,
        "_write_receipt",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(PermissionError("denied")),
    )

    run = admit_sealed_entry(request, dependencies=dependencies)

    assert run.result.status == "blocked"
    assert run.result.first_failure_stage == "receipt"
    assert run.receipt_path is None
    assert run.result.attempt_consumed is False


def test_receipt_hash_and_physical_path_are_strict(tmp_path: Path) -> None:
    request, dependencies = _fixture(tmp_path)
    run = admit_sealed_entry(request, dependencies=dependencies)
    assert run.receipt_path and run.receipt_sha256

    with pytest.raises(ValueError, match="identity"):
        verify_entry_admission_receipt(
            request,
            receipt_path=run.receipt_path,
            expected_sha256="0" * 64,
        )
    other = tmp_path / "other"
    other.mkdir()
    copied = other / Path(run.receipt_path).name
    shutil.copyfile(run.receipt_path, copied)
    with pytest.raises(ValueError, match="physical path"):
        verify_entry_admission_receipt(
            request,
            receipt_path=copied,
            expected_sha256=hashlib.sha256(copied.read_bytes()).hexdigest(),
        )


def test_entry_and_git_production_are_domain_and_model_neutral() -> None:
    entry_source = inspect.getsource(entry_module)
    git_source = inspect.getsource(git_admission_module)

    for forbidden in ("AccurateCrosshair", "qwen3.context_length", "qwen3"):
        assert forbidden not in entry_source
        assert forbidden not in git_source
