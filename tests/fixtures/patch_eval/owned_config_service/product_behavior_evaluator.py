"""Adapt the unchanged owned oracle to run-request's generated_mods layout.

Patch identity is checked in the real product workspace before relocating the
verified bytes for the original compiler/process matrix. No Plan paths or
reported materialization hashes are rewritten.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from types import ModuleType

from src.mod_agent.artifacts import ArtifactRef, ArtifactStore
from src.mod_agent.model_qualification import canonical_hash
from src.mod_agent.proposal.patch_agent_loop import PatchAgentLoopPolicy, PlanBoundSourceInspector


def make_product_behavior_evaluator(*, workspace_root, output_root, expected_check_ids,
                                    oracle_sha256):
    oracle_path = Path(__file__).resolve().with_name("behavior_evaluator.py")
    raw = oracle_path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != oracle_sha256:
        raise ValueError("OWNED_CONFIG_ORACLE_SOURCE_CHANGED")
    legacy = ModuleType("_owned_config_product_bound_oracle")
    legacy.__file__ = str(oracle_path)
    exec(compile(raw, str(oracle_path), "exec"), legacy.__dict__)

    class ProductOwnedConfigOracle(legacy.OwnedConfigOracle):
        def __init__(self):
            self.workspace = Path(workspace_root).resolve(strict=True)
            source_root = self.workspace / "generated_mods"
            if not source_root.resolve(strict=True).is_relative_to(self.workspace):
                raise ValueError("OWNED_CONFIG_PRODUCT_SOURCE_ESCAPE")
            self._oracle = legacy.OwnedConfigOracle(workspace_root=source_root,
                output_root=output_root, expected_check_ids=expected_check_ids)
            self.output_root = self._oracle.output_root
            self.evaluations = 0

        def verification_identity(self):
            if legacy.reference(oracle_path)["sha256"] != oracle_sha256:
                raise ValueError("OWNED_CONFIG_ORACLE_SOURCE_CHANGED")
            identity = self._oracle.verification_identity()
            return {**identity, "validator_sha256": canonical_hash({
                "adapter": legacy.reference(__file__), "oracle": legacy.reference(oracle_path)}),
                "inputs_sha256": canonical_hash({"oracle_inputs": identity["inputs_sha256"],
                    "source_subdirectory": "generated_mods"})}

        def __call__(self, context):
            identity = self.verification_identity()
            if (context.get("verification_identity") is not None
                    and context["verification_identity"] != identity):
                raise ValueError("OWNED_CONFIG_VERIFICATION_IDENTITY_MISMATCH")
            if canonical_hash(context["generated_changes"]) != context["generated_changes_sha256"]:
                raise ValueError("OWNED_CONFIG_GENERATED_CHANGES_MISMATCH")
            plan = context["implementation_plan"]
            if context.get("implementation_plan_ref") is not None:
                reference = ArtifactRef(**context["implementation_plan_ref"])
                if (reference.artifact_type != "implementation_plan"
                        or ArtifactStore(self.workspace).read(reference)["data"] != plan):
                    raise ValueError("OWNED_CONFIG_PLAN_CONTEXT_MISMATCH")
            inspector = PlanBoundSourceInspector(workspace_root=self.workspace,
                implementation_plan=plan, policy=PatchAgentLoopPolicy())
            if inspector.source_snapshot_sha256 != context["source_snapshot_sha256"]:
                raise ValueError("OWNED_CONFIG_SOURCE_SNAPSHOT_MISMATCH")
            return super().__call__(context)

        def _evaluate_files(self, run, replacements):
            relocated = {}
            for relative, content in replacements.items():
                prefix = "generated_mods/"
                if not relative.startswith(prefix):
                    raise ValueError("OWNED_CONFIG_PRODUCT_MATERIALIZATION_ESCAPE")
                relocated[relative[len(prefix):]] = content
            return self._oracle._evaluate_files(run, relocated)

    return ProductOwnedConfigOracle()
