"""Offline tests for structure acquisition; no credentials or network are used."""

import json
from types import SimpleNamespace

import pytest
from pymatgen.core import Lattice, Structure

from materials_project_structure_agent import (
    MaterialsProjectLookupError,
    StructureRequestError,
    acquire_structure_with_agent,
    fetch_materials_project_candidates,
    parse_structure_request,
    save_candidate_structures,
    select_candidate,
    validate_structure_query,
)


def fake_structure(a: float = 3.9) -> Structure:
    return Structure(Lattice.cubic(a), ["Pt"], [[0, 0, 0]])


class FakeMPRester:
    def __init__(self, documents):
        self.documents = documents
        self.criteria = None
        self.materials = SimpleNamespace(summary=self)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def search(self, **criteria):
        self.criteria = criteria
        return self.documents


def make_document(material_id, hull, band_gap, symbol="Fm-3m", number=225):
    return SimpleNamespace(
        material_id=material_id,
        formula_pretty="Pt",
        symmetry=SimpleNamespace(
            symbol=symbol, number=number, crystal_system="Cubic"
        ),
        energy_above_hull=hull,
        band_gap=band_gap,
        structure=fake_structure(),
    )


def test_query_validation_normalizes_formula_and_rejects_ambiguous_symbol():
    query = validate_structure_query({"formula": "Pt2", "max_structures": 2})
    assert query.formula == "Pt"
    assert query.max_structures == 2
    with pytest.raises(StructureRequestError):
        validate_structure_query({"formula": "Pt", "spacegroup_symbol": "fcc"})


def test_fetch_sorts_candidates_and_saves_cif(tmp_path):
    fake = FakeMPRester([
        make_document("mp-high", 0.08, 0.1),
        make_document("mp-low", 0.0, 0.0),
    ])
    query = validate_structure_query({"formula": "Pt", "max_structures": 2})
    candidates = fetch_materials_project_candidates(
        query,
        cache_dir=tmp_path / "cache",
        api_key="test-key-not-a-real-secret",
        client_factory=lambda _key, _cache: fake,
    )
    assert [item.material_id for item in candidates] == ["mp-low", "mp-high"]
    assert "structure" in fake.criteria["fields"]
    assert fake.criteria["include_gnome"] is False
    assert fake.criteria["num_chunks"] == 1
    assert fake.criteria["chunk_size"] == 2
    save_candidate_structures(candidates, tmp_path)
    assert all((tmp_path / item.structure_file).is_file() for item in candidates)


def test_formula_only_requires_maximum_before_lookup(tmp_path):
    query = validate_structure_query({"formula": "SiO2"})
    assert query.max_structures is None
    with pytest.raises(StructureRequestError):
        fetch_materials_project_candidates(
            query, cache_dir=tmp_path, api_key="test-key",
            client_factory=lambda _key, _cache: FakeMPRester([]),
        )


def test_empty_lookup_is_stopped_during_selection():
    with pytest.raises(MaterialsProjectLookupError):
        select_candidate([])


def test_selection_accepts_index_or_material_id():
    candidates = [
        SimpleNamespace(material_id="mp-1"),
        SimpleNamespace(material_id="mp-2"),
    ]
    assert select_candidate(candidates, selected_material_id="2").material_id == "mp-2"
    assert select_candidate(candidates, selected_material_id="mp-1").material_id == "mp-1"


class FakeResponses:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return next(self.responses)


def fake_response(*, call_arguments=None, text=""):
    output = []
    if call_arguments is not None:
        output.append(SimpleNamespace(
            type="function_call",
            name="search_materials_project_structures",
            arguments=json.dumps(call_arguments),
        ))
    return SimpleNamespace(output=output, output_text=text, usage=None)


def test_llm_clarifies_count_then_calls_tool():
    client = SimpleNamespace(responses=FakeResponses([
        fake_response(text="How many SiO2 candidate structures should be downloaded (1-10)?"),
        fake_response(call_arguments={"formula": "SiO2", "max_structures": 3}),
    ]))
    query, usages = parse_structure_request(
        client, "deepseek-v4-flash", "I need a SiO2 crystal structure",
        input_fn=lambda _question: "3",
    )
    assert query.formula == "SiO2"
    assert query.max_structures == 3
    assert len(client.responses.calls) == 2
    assert len(usages) == 2


def test_report_metadata_does_not_contain_api_key(tmp_path):
    fake = FakeMPRester([make_document("mp-test", 0.0, 0.0)])
    query = validate_structure_query({"formula": "Pt", "max_structures": 1})
    candidates = fetch_materials_project_candidates(
        query,
        cache_dir=tmp_path / "cache",
        api_key="sensitive-test-marker",
        client_factory=lambda _key, _cache: fake,
    )
    metadata = json.dumps([item.to_metadata() for item in candidates])
    assert "sensitive-test-marker" not in metadata


def test_full_acquisition_uses_fake_services_and_writes_selected_cif(tmp_path):
    llm = SimpleNamespace(responses=FakeResponses([
        fake_response(call_arguments={
            "formula": "Pt", "spacegroup_symbol": "Fm-3m",
            "max_structures": 1,
        }),
    ]))
    fake_mp = FakeMPRester([make_document("mp-test", 0.0, 0.0)])
    path, acquisition, usages = acquire_structure_with_agent(
        llm,
        "deepseek-v4-flash",
        "Retrieve a Pt crystal structure in space group Fm-3m",
        tmp_path,
        api_key="test-key-not-a-real-secret",
        mp_client_factory=lambda _key, _cache: fake_mp,
    )
    assert path.is_file()
    assert acquisition["selected_material_id"] == "mp-test"
    assert acquisition["requires_human_review"] is True
    assert "test-key-not-a-real-secret" not in json.dumps(acquisition)
    assert len(usages) == 1
