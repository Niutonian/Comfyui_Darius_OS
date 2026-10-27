from copy import deepcopy

from darius_api.generation_identity import output_name, prepare_seeds


def test_new_generation_randomizes_template_but_preserve_keeps_explicit_seed(monkeypatch):
    graph = {"1": {"class_type": "KSampler", "inputs": {"seed": 42}}}
    source = deepcopy(graph)
    monkeypatch.setattr("darius_api.generation_identity.secrets.randbelow", lambda _: 987)
    assert prepare_seeds(graph) == {"1.seed": 987}
    assert source["1"]["inputs"]["seed"] == 42
    assert prepare_seeds(source, "preserve") == {"1.seed": 42}


def test_seed_links_are_preserved():
    graph = {"1": {"class_type": "KSampler", "inputs": {"seed": ["2", 0]}}, "2": {"class_type": "PrimitiveInt", "inputs": {"value": 42}}}
    prepare_seeds(graph)
    assert graph["1"]["inputs"]["seed"] == ["2", 0]
    assert 0 <= graph["2"]["inputs"]["value"] < 2**32


def test_names_include_subject_and_unique_output_identity():
    assert output_name("Red fox", "12345678-abc", 1, ".png") == "red-fox-12345678-01.png"
    assert output_name("Red fox", "12345678-abc", 1, ".png") != output_name("Red fox", "12345678-abc", 2, ".png")
