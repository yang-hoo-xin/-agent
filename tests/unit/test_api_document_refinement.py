from types import SimpleNamespace
from src.libs.llm import ChatResponse

from src.ingestion.transform.chunk_refiner import ChunkRefiner


def test_real_api_xml_identifiers_and_cross_references_survive_rule_cleaning():
    refiner = ChunkRefiner(SimpleNamespace(ingestion=SimpleNamespace(chunk_refiner={"use_llm": False})))
    source = '<member name="M:BepInEx.Logging.ManualLogSource.LogInfo(System.Object)">\n<summary>Logs at <see cref="F:BepInEx.Logging.LogLevel.Info" /> level.</summary></member>'
    result = refiner._rule_based_refine(source)
    assert 'name="M:BepInEx.Logging.ManualLogSource.LogInfo(System.Object)"' in result
    assert 'cref="F:BepInEx.Logging.LogLevel.Info"' in result
    assert '<summary>' in result
    assert refiner._rule_based_refine('<p>List<T> and x < y && y > z</p>') == 'List<T> and x < y && y > z'


def test_source_implementation_change_invalidates_ingestion_identity(monkeypatch, tmp_path):
    from src.core.settings import load_settings
    from src.ingestion import identity
    original = identity.resolve_path
    changed = tmp_path / "refiner.py"
    changed.write_text("revision one", encoding="utf-8")
    monkeypatch.setattr(identity, "resolve_path", lambda path: changed if path == "src/ingestion/transform/chunk_refiner.py" else original(path))
    settings = load_settings("config/settings.yaml")
    first = identity.ingestion_identity(settings)[1]
    changed.write_text("revision two", encoding="utf-8")
    assert identity.ingestion_identity(settings)[1] != first


def test_real_refinement_identifier_corruption_is_rejected():
    source = '<member name="E:BepInEx.Configuration.ConfigFile.ConfigReloaded">Fired every reload.</member>'
    model = SimpleNamespace(chat=lambda *args, **kwargs: ChatResponse(
        content=source.replace("BepInEx", "BepIn-Ex"), model="fake", usage={"total_tokens": 3}))
    refiner = ChunkRefiner(SimpleNamespace(ingestion=SimpleNamespace(chunk_refiner={"use_llm": True})), llm=model)
    assert refiner._llm_refine(source) is None
    assert refiner._rule_based_refine(source) == source


def test_missing_image_reference_is_rejected_before_captioning():
    model = SimpleNamespace(chat=lambda *args, **kwargs: ChatResponse(content="An image is present.", model="fake"))
    refiner = ChunkRefiner(SimpleNamespace(ingestion=SimpleNamespace(chunk_refiner={"use_llm": True})), llm=model)
    assert refiner._llm_refine("[IMAGE: original-image-identity]") is None
