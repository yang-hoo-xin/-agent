"""The same source window may be rediscovered using a different lexical query."""
from dataclasses import replace

import pytest

from src.mod_agent.evidence.reassessment import merge_reobserved_source_item
from src.mod_agent.evidence.rg_live import materialize_source_location


@pytest.fixture
def observations(tmp_path):
    raw = (b"using BepInEx;\nusing BepInEx.Unity.IL2CPP;\n\nnamespace GeneratedMod_Test\n{\n"
           b'    [BepInPlugin("local.modagent.test", "Neutral", "0.1.0")]\n'
           b"    public sealed class Plugin : BasePlugin\n    {\n"
           b"        public override void Load()\n        {\n        }\n    }\n}\n")
    path = tmp_path / "Plugin.cs"
    path.write_bytes(raw)
    def observation(tokens):
        return materialize_source_location(workspace_root=tmp_path, selected_path=path,
                                           selected_line=6, source_bytes=raw, tokens=tokens)
    return observation(["modagent"]), observation(["mod"])


def test_same_identity_different_lexical_labels_preserves_canonical_bytes(observations):
    old, new = observations
    assert old.evidence_id == new.evidence_id
    assert old.symbol != new.symbol
    assert {k for k in old.to_dict() if old.to_dict()[k] != new.to_dict()[k]} == {
        "symbol", "claim_supported"}
    assert merge_reobserved_source_item(old, new) is old


@pytest.mark.parametrize("change", [
    {"excerpt": "changed source bytes"}, {"source_hash": "f" * 64},
    {"span": {"start_line": 2, "end_line": 13}}, {"source_path": "Other.cs"},
    {"source_ref": "other source"}, {"authority": "changed"},
    {"claim_supported": "Different semantic claim"},
    {"method_name": "Load", "method_kind": "method"},
])
def test_reobservation_still_rejects_physical_semantic_and_declaration_conflicts(observations, change):
    old, new = observations
    with pytest.raises(ValueError, match="PATCH_REASSESSMENT_EVIDENCE_ID_CONFLICT"):
        merge_reobserved_source_item(old, replace(new, **change))
