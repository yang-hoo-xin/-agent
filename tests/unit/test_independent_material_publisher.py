"""Public identity-location and controlled-error tests for the sealed publisher."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from uuid import uuid4

import pytest

from scripts import publish_independent_task_materials as publisher
from scripts.prepare_patch_sft_data import execute_version, toolchain


def test_exact_recorded_toolchain_path_is_preferred(tmp_path):
    raw = b'{"dotnet":{},"compiler":{},"references":[]}'
    direct = tmp_path / "toolchain.json"
    direct.write_bytes(raw)
    assert publisher._find_exact(tmp_path, "toolchain.json", hashlib.sha256(raw).hexdigest()) == direct


def test_exact_hash_fallback_does_not_guess_filename(tmp_path):
    raw = b'{"identity":"public-fixture"}'
    nested = tmp_path / "nested"
    nested.mkdir()
    recorded = nested / "recorded-environment.json"
    recorded.write_bytes(raw)
    assert publisher._find_exact(tmp_path, "toolchain.json", hashlib.sha256(raw).hexdigest()) == recorded


def test_missing_identity_has_stable_code_and_stage(tmp_path):
    with pytest.raises(publisher.PublisherError) as caught:
        publisher._find_exact(tmp_path, "toolchain.json", "0" * 64)
    assert caught.value.code == "PUBLISH_REQUIRED_EXACT_FILE_MISSING"
    assert caught.value.stage == "sealed_identity"


def test_identity_hashes_come_from_bound_public_documents():
    protocol = {"sealed_manifest_sha256": "1" * 64,
                "model": {"profile_sha256": "2" * 64}}
    metadata = {"toolchain_metadata_sha256": "3" * 64}
    assert publisher._authority_hashes(protocol, metadata) == {
        "manifest": "1" * 64, "profile": "2" * 64, "toolchain": "3" * 64}
    with pytest.raises(publisher.PublisherError) as caught:
        publisher._authority_hashes(protocol, {})
    assert (caught.value.code, caught.value.stage) == (
        "PUBLISH_PUBLIC_IDENTITY_INCOMPLETE", "public_identity")


def test_recorded_source_root_precedes_archived_fallback(tmp_path):
    recorded = tmp_path / "recorded" / "OwnedTraining"
    recorded.mkdir(parents=True)
    (recorded / "Subject.cs").write_text("recorded")
    archived = tmp_path / "sealed" / "tasks" / "case-one" / "source" / "OwnedTraining"
    archived.mkdir(parents=True)
    (archived / "Subject.cs").write_text("archived")
    task = {"case_id": "case-one", "source_root": str(recorded.parent)}
    assert publisher._source(task, tmp_path / "sealed" / "manifest.json").read_text() == "recorded"


def test_archived_source_is_used_only_when_recorded_root_is_missing(tmp_path):
    archived = tmp_path / "sealed" / "tasks" / "case-one" / "source" / "OwnedTraining"
    archived.mkdir(parents=True)
    subject = archived / "Subject.cs"
    subject.write_text("archived")
    task = {"case_id": "case-one", "source_root": str(tmp_path / "missing")}
    assert publisher._source(task, tmp_path / "sealed" / "manifest.json") == subject.resolve()


def test_cli_emits_only_controlled_publisher_error(monkeypatch, capsys):
    def blocked(**_):
        raise publisher.PublisherError("PUBLISH_B0_IDENTITY_CHANGED", "source_identity")

    monkeypatch.setattr(publisher, "publish", blocked)
    result = publisher.main(["--independent-root", "public-root", "--output-root", "public-output",
                             "--repository-root", "public-repository"])
    assert result == 2
    assert json.loads(capsys.readouterr().out) == {
        "status": "blocked", "code": "PUBLISH_B0_IDENTITY_CHANGED", "stage": "source_identity"}


def test_private_short_root_is_archived_before_cleanup(tmp_path):
    private = tmp_path / "short"
    (private / "evaluation_1" / "execution").mkdir(parents=True)
    raw = private / "evaluation_1" / "execution" / "report.json"
    raw.write_text('{"private":"not_public"}')
    destination = tmp_path / "protected" / "case-one.zip"
    reference = publisher._archive_private_tree(private, destination)
    assert reference["sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    with zipfile.ZipFile(destination) as archive:
        assert archive.namelist() == ["evaluation_1/execution/report.json"]


@pytest.mark.skipif(os.name != "nt", reason="Reproduces the observed Windows path boundary")
def test_public_long_judge_path_fails_after_compilation_while_short_root_executes():
    base = Path(tempfile.gettempdir()) / ("ipl-" + uuid4().hex[:8])
    root = base
    target = 254
    while len(str(root / "compilation.json")) + 22 < target:
        root /= "x" * 20
    remaining = target - len(str(root / "compilation.json")) - 1
    if remaining > 0:
        root /= "x" * remaining
    source = "public static class Subject { public static int Apply(int value) => value; }\n"
    program = ('using System; public static class Program { public static int Main() {'
               'Console.Write("[{\\"check\\":\\"public\\",\\"group\\":\\"preservation\\",'
               '\\"expected\\":1,\\"observed\\":1,\\"passed\\":true}]"); return 0; } }')
    short = Path(tempfile.gettempdir()) / ("ips-" + uuid4().hex[:8])
    try:
        with pytest.raises(FileNotFoundError):
            execute_version(root, source, program, toolchain())
        assert (root / "compilation.json").is_file()
        assert json.loads((root / "compilation.json").read_text())["exit_code"] == 0
        result = execute_version(short, source, program, toolchain())
        assert result["status"] == "passed" and result["execution_origin"] == "actual_csharp_process"
    finally:
        shutil.rmtree(base, ignore_errors=True)
        shutil.rmtree(short, ignore_errors=True)
