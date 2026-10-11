from pathlib import Path

import pytest

import src.mod_agent.local_entry as local_entry_module
from src.mod_agent.artifacts import ArtifactRef, ArtifactStoreError
from src.mod_agent.local_entry import LocalEntryError
from src.mod_agent.workflow import (
    ResumeDecision,
    ResumePayload,
    StubNodeRunner,
    WorkflowCheckpointStore,
    create_initial_state,
)


def test_stub_state_copy_preserves_edit_authority_review_result() -> None:
    state = create_initial_state(
        run_id="run_state_copy",
        request_id="request_state_copy",
        user_request="Preserve the exact review projection.",
    )
    state["edit_authority_review_result"] = {
        "platform_status": "completed",
        "details": {"review_outcome": "approved"},
    }

    copied = StubNodeRunner._copy_state(state)

    assert copied["edit_authority_review_result"] == state[
        "edit_authority_review_result"
    ]
    assert copied["edit_authority_review_result"] is not state[
        "edit_authority_review_result"
    ]
    assert copied["edit_authority_review_result"] is not None
    copied["edit_authority_review_result"]["details"]["review_outcome"] = (
        "rejected"
    )
    assert state["edit_authority_review_result"]["details"][
        "review_outcome"
    ] == "approved"


def test_resume_consumes_checkpoint_only_after_report_write_succeeds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkpoint_ref = ArtifactRef(
        feature_id="feature_resume",
        artifact_type="workflow_checkpoint",
        path="workflow_checkpoint.json",
        artifact_hash="a" * 64,
    )
    report_ref = ArtifactRef(
        feature_id="feature_resume",
        artifact_type="resume_report",
        path="resume_report.json",
        artifact_hash="b" * 64,
    )
    checkpoint = {"checkpoint_id": "checkpoint_resume"}
    decision = ResumeDecision(
        status="accepted",
        allowed=True,
        reason="Resume payload accepted.",
        applied_updates={},
    )
    payload = ResumePayload(
        resume_id="resume_once",
        run_id="run_resume",
        stage="build",
        decision="approve",
        approved_by="user",
        approved_at="2026-09-23T00:00:00+08:00",
        artifact_refs=(),
    )

    class Store:
        root = tmp_path
        write_count = 0

        def write(self, **_kwargs):
            self.write_count += 1
            if self.write_count == 1:
                raise ArtifactStoreError("resume report write failed")
            return report_ref

    checkpoint_store = WorkflowCheckpointStore(Store())
    monkeypatch.setattr(
        checkpoint_store,
        "_resume_write_arguments",
        lambda *_args, **_kwargs: (checkpoint, decision, {}),
    )

    with pytest.raises(ArtifactStoreError, match="resume report write failed"):
        checkpoint_store.resume(checkpoint_ref, payload)
    assert checkpoint_store._seen_resume_ids == set()
    assert checkpoint_store._consumed_checkpoint_ids == set()

    retried_decision, retried_ref = checkpoint_store.resume(checkpoint_ref, payload)

    assert retried_decision is decision
    assert retried_ref == report_ref
    assert checkpoint_store._seen_resume_ids == {payload.resume_id}
    assert checkpoint_store._consumed_checkpoint_ids == {
        checkpoint["checkpoint_id"]
    }


def test_project_text_property_helpers_preserve_optional_and_required_contracts(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "Example.csproj"
    project_file.write_text(
        "<Project><PropertyGroup><AssemblyName>Example</AssemblyName>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    assert local_entry_module._optional_project_text_property(
        project_file,
        property_name="TargetFramework",
    ) is None
    assert local_entry_module._project_text_property(
        project_file,
        property_name="AssemblyName",
    ) == "Example"
    with pytest.raises(
        LocalEntryError,
        match="Project file does not define TargetFramework",
    ):
        local_entry_module._project_text_property(
            project_file,
            property_name="TargetFramework",
        )


def test_optional_project_text_property_preserves_duplicate_value_error(
    tmp_path: Path,
) -> None:
    project_file = tmp_path / "Duplicate.csproj"
    project_file.write_text(
        "<Project><PropertyGroup><TargetFramework>net6.0</TargetFramework>"
        "</PropertyGroup><PropertyGroup><TargetFramework>net8.0</TargetFramework>"
        "</PropertyGroup></Project>",
        encoding="utf-8",
    )

    with pytest.raises(
        LocalEntryError,
        match="Project file must define at most one non-empty TargetFramework",
    ):
        local_entry_module._optional_project_text_property(
            project_file,
            property_name="TargetFramework",
        )
