"""Parse structure requests with an LLM and query Materials Project through Python.

Security boundaries:
- The model supplies only formula, symmetry, and candidate-limit parameters.
- Only Python calls mp-api, and only after explicit local authorization.
- Downloaded files are restricted to a caller-supplied project report directory.
- Materials Project candidates are bulk starting structures, not surfaces,
  adsorbates, or transition-state models.
"""

from __future__ import annotations

import json
import math
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from pymatgen.core import Composition
from pymatgen.io.cif import CifWriter


TOOL_NAME = "search_materials_project_structures"
MAX_STRUCTURES_LIMIT = 10
DEFAULT_EXACT_SYMMETRY_LIMIT = 5
CRYSTAL_SYSTEMS = {
    "triclinic", "monoclinic", "orthorhombic", "tetragonal",
    "trigonal", "hexagonal", "cubic",
}
AMBIGUOUS_SPACEGROUP_TERMS = {
    "fcc", "bcc", "hcp", "cubic", "hexagonal", "trigonal",
    "tetragonal", "orthorhombic", "monoclinic", "triclinic",
}

STRUCTURE_QUERY_TOOL = {
    "type": "function",
    "name": TOOL_NAME,
    "description": (
        "Search Materials Project for crystals matching a user request. "
        "Retrieve structures only; never invent Materials Project data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "formula": {
                "type": "string",
                "description": "Normalized formula, for example Pt, SiO2, or Fe2O3",
            },
            "spacegroup_symbol": {
                "type": "string",
                "description": "Optional international short space-group symbol, e.g. Fm-3m",
            },
            "spacegroup_number": {
                "type": "integer", "minimum": 1, "maximum": 230,
                "description": "Optional space-group number from 1 to 230",
            },
            "crystal_system": {
                "type": "string",
                "enum": sorted(CRYSTAL_SYSTEMS),
                "description": "Optional crystal system for broad symmetry descriptions",
            },
            "max_structures": {
                "type": "integer", "minimum": 1, "maximum": MAX_STRUCTURES_LIMIT,
                "description": "Maximum number of candidate structures to download",
            },
        },
        "required": ["formula"],
        "additionalProperties": False,
    },
}


class StructureRequestError(ValueError):
    """The model-produced structure request is incomplete or invalid."""


class MaterialsProjectLookupError(RuntimeError):
    """Materials Project lookup or structure serialization failed."""


@dataclass(frozen=True)
class StructureQuery:
    formula: str
    spacegroup_symbol: str | None = None
    spacegroup_number: int | None = None
    crystal_system: str | None = None
    max_structures: int | None = None

    @property
    def has_symmetry_constraint(self) -> bool:
        return any((self.spacegroup_symbol, self.spacegroup_number, self.crystal_system))

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class MaterialsProjectCandidate:
    material_id: str
    formula: str
    space_group_symbol: str | None
    space_group_number: int | None
    crystal_system: str | None
    energy_above_hull_ev_atom: float | None
    band_gap_ev: float | None
    structure: object
    structure_file: str | None = None

    def to_metadata(self) -> dict:
        data = asdict(self)
        data.pop("structure", None)
        return data


def _clean_optional_string(value) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def validate_structure_query(arguments: dict, *, max_override: int | None = None) -> StructureQuery:
    """Validate model arguments and normalize the formula without network access."""
    allowed = {
        "formula", "spacegroup_symbol", "spacegroup_number",
        "crystal_system", "max_structures",
    }
    unknown = set(arguments) - allowed
    if unknown:
        raise StructureRequestError(f"The structure tool contains unauthorized fields: {sorted(unknown)}")

    raw_formula = _clean_optional_string(arguments.get("formula"))
    if not raw_formula:
        raise StructureRequestError("The structure request is missing a formula")
    try:
        composition = Composition(raw_formula)
    except (ValueError, TypeError) as exc:
        raise StructureRequestError("The formula could not be parsed") from exc
    if not composition.elements or any(amount <= 0 for amount in composition.values()):
        raise StructureRequestError("The formula must contain positive stoichiometric amounts")
    formula = composition.reduced_formula

    symbol = _clean_optional_string(arguments.get("spacegroup_symbol"))
    if symbol and symbol.lower() in AMBIGUOUS_SPACEGROUP_TERMS:
        raise StructureRequestError(
            "fcc, bcc, hcp, and crystal systems are not strict space-group symbols; "
            "use crystal_system or request clarification"
        )

    number = arguments.get("spacegroup_number")
    if number is not None:
        if isinstance(number, bool) or not isinstance(number, int) or not 1 <= number <= 230:
            raise StructureRequestError("spacegroup_number must be an integer from 1 to 230")

    crystal_system = _clean_optional_string(arguments.get("crystal_system"))
    if crystal_system:
        crystal_system = crystal_system.lower()
        if crystal_system not in CRYSTAL_SYSTEMS:
            raise StructureRequestError("crystal_system must be one of the seven supported systems")

    max_structures = max_override if max_override is not None else arguments.get("max_structures")
    if max_structures is not None:
        if (
            isinstance(max_structures, bool)
            or not isinstance(max_structures, int)
            or not 1 <= max_structures <= MAX_STRUCTURES_LIMIT
        ):
            raise StructureRequestError(
                f"max_structures must be an integer from 1 to {MAX_STRUCTURES_LIMIT}"
            )

    query = StructureQuery(
        formula=formula,
        spacegroup_symbol=symbol,
        spacegroup_number=number,
        crystal_system=crystal_system,
        max_structures=max_structures,
    )
    if query.max_structures is None and query.has_symmetry_constraint:
        query = StructureQuery(
            formula=query.formula,
            spacegroup_symbol=query.spacegroup_symbol,
            spacegroup_number=query.spacegroup_number,
            crystal_system=query.crystal_system,
            max_structures=DEFAULT_EXACT_SYMMETRY_LIMIT,
        )
    return query


def _usage_snapshot(response) -> dict:
    usage = getattr(response, "usage", None)
    if usage is None:
        return {}
    details = getattr(usage, "input_tokens_details", None)
    return {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        "cached_tokens": getattr(details, "cached_tokens", None),
    }


def _function_calls(response) -> list:
    return [item for item in getattr(response, "output", []) if item.type == "function_call"]


def parse_structure_request(
    client,
    model: str,
    user_prompt: str,
    *,
    max_override: int | None = None,
    input_fn: Callable[[str], str] = input,
) -> tuple[StructureQuery, list[dict]]:
    """Parse a structure request and ask for a candidate limit when necessary."""
    prompt = user_prompt.strip()
    if max_override is not None:
        prompt += f"\nThe user set a local command-line limit of {max_override} structures."

    instructions = (
        "You parse crystal-structure requests. Never invent Materials Project IDs, "
        "energies, or band gaps. If the user supplies only a formula without a strict "
        f"space group, crystal system, or candidate limit, first ask in plain text how "
        f"many candidates to download (1-{MAX_STRUCTURES_LIMIT}); do not call the tool. "
        "Once sufficient information is available, call only "
        "search_materials_project_structures. Fm-3m or 225 is a strict space group; "
        "fcc, bcc, and hcp are broad descriptions and may require clarification."
    )
    usages: list[dict] = []
    for round_index in range(2):
        response = client.responses.create(
            model=model,
            instructions=instructions,
            input=prompt,
            tools=[STRUCTURE_QUERY_TOOL],
        )
        usages.append(_usage_snapshot(response))
        calls = _function_calls(response)
        if calls:
            if len(calls) != 1 or calls[0].name != TOOL_NAME:
                raise StructureRequestError("The model did not produce one supported structure tool call")
            try:
                arguments = json.loads(calls[0].arguments)
            except (json.JSONDecodeError, TypeError) as exc:
                raise StructureRequestError("The model structure arguments are not valid JSON") from exc
            query = validate_structure_query(arguments, max_override=max_override)
            if query.max_structures is not None:
                return query, usages

            # Do not query if the model skipped the required clarification.
            question_response = client.responses.create(
                model=model,
                instructions=(
                    f"Ask one short question: for {query.formula}, how many candidate "
                    f"structures should be downloaded (1-{MAX_STRUCTURES_LIMIT})?"
                ),
                input="Ask the clarification question.",
            )
            usages.append(_usage_snapshot(question_response))
            question = question_response.output_text.strip()
        else:
            question = response.output_text.strip()

        if round_index == 1 or not question:
            raise StructureRequestError("Complete structure arguments were not obtained after two rounds")
        answer = input_fn(f"Model clarification: {question}\nAnswer: ").strip()
        if not answer:
            raise StructureRequestError("The candidate-limit clarification was not answered")
        prompt += f"\nClarification question: {question}\nUser answer: {answer}"

    raise StructureRequestError("No complete structure query was obtained")


def _get_value(obj, name: str, default=None):
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _float_or_none(value) -> float | None:
    if value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _default_client_factory(api_key: str, cache_dir: Path):
    try:
        from mp_api.client import MPRester
    except ImportError as exc:
        raise MaterialsProjectLookupError(
            "mp-api is missing; install requirements-agent.txt in the Agent environment"
        ) from exc
    return MPRester(
        api_key=api_key,
        mute_progress_bars=True,
        notify_db_version=False,
        local_dataset_cache=cache_dir,
    )


def fetch_materials_project_candidates(
    query: StructureQuery,
    *,
    cache_dir: Path,
    api_key: str | None = None,
    client_factory=None,
) -> list[MaterialsProjectCandidate]:
    """Run a Materials Project query after the caller has authorized network use."""
    if query.max_structures is None:
        raise StructureRequestError("max_structures must be defined before lookup")
    key = api_key or os.getenv("MP_API_KEY")
    if not key:
        raise MaterialsProjectLookupError("MP_API_KEY is not configured; anonymous lookup is disabled")

    cache_dir = cache_dir.resolve()
    cache_dir.mkdir(parents=True, exist_ok=True)
    factory = client_factory or _default_client_factory
    criteria = {
        "formula": query.formula,
        "deprecated": False,
        "include_gnome": False,
        "num_chunks": 1,
        "chunk_size": query.max_structures,
        "fields": [
            "material_id", "formula_pretty", "symmetry", "energy_above_hull",
            "band_gap", "structure",
        ],
        "_sort_fields": "energy_above_hull",
    }
    if query.spacegroup_symbol:
        criteria["spacegroup_symbol"] = query.spacegroup_symbol
    if query.spacegroup_number:
        criteria["spacegroup_number"] = query.spacegroup_number
    if query.crystal_system:
        criteria["crystal_system"] = query.crystal_system

    try:
        with factory(key, cache_dir) as mpr:
            documents = mpr.materials.summary.search(**criteria)
    except MaterialsProjectLookupError:
        raise
    except Exception as exc:
        raise MaterialsProjectLookupError(
            f"Materials Project lookup failed: {type(exc).__name__}"
        ) from exc

    candidates: list[MaterialsProjectCandidate] = []
    for document in documents:
        symmetry = _get_value(document, "symmetry")
        crystal_system = _clean_optional_string(_get_value(symmetry, "crystal_system"))
        if crystal_system:
            crystal_system = crystal_system.lower()
        if query.crystal_system and crystal_system != query.crystal_system:
            continue
        structure = _get_value(document, "structure")
        if structure is None:
            continue
        candidate = MaterialsProjectCandidate(
            material_id=str(_get_value(document, "material_id")),
            formula=str(_get_value(document, "formula_pretty", query.formula)),
            space_group_symbol=_clean_optional_string(_get_value(symmetry, "symbol")),
            space_group_number=_get_value(symmetry, "number"),
            crystal_system=crystal_system,
            energy_above_hull_ev_atom=_float_or_none(
                _get_value(document, "energy_above_hull")
            ),
            band_gap_ev=_float_or_none(_get_value(document, "band_gap")),
            structure=structure,
        )
        candidates.append(candidate)

    candidates.sort(
        key=lambda item: (
            item.energy_above_hull_ev_atom is None,
            item.energy_above_hull_ev_atom
            if item.energy_above_hull_ev_atom is not None else math.inf,
            item.material_id,
        )
    )
    return candidates[: query.max_structures]


def _safe_filename_part(value: str | None) -> str:
    clean = re.sub(r"[^A-Za-z0-9._+-]+", "_", value or "unknown")
    return clean.strip("._") or "unknown"


def save_candidate_structures(
    candidates: list[MaterialsProjectCandidate], output_dir: Path
) -> list[MaterialsProjectCandidate]:
    """Write candidates as CIF files and record relative names in metadata."""
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for candidate in candidates:
        filename = "_".join(
            (
                _safe_filename_part(candidate.material_id),
                _safe_filename_part(candidate.formula),
                _safe_filename_part(candidate.space_group_symbol),
            )
        ) + ".cif"
        path = output_dir / filename
        try:
            CifWriter(candidate.structure, symprec=0.01).write_file(path)
        except (OSError, ValueError, TypeError) as exc:
            raise MaterialsProjectLookupError(
                f"Could not save candidate {candidate.material_id}: {type(exc).__name__}"
            ) from exc
        candidate.structure_file = filename
    return candidates


def print_candidate_table(candidates: list[MaterialsProjectCandidate]) -> None:
    print("\nMaterials Project candidate structures:")
    print("Index | MP ID | Formula | Space group | E hull (eV/atom) | Band gap (eV)")
    for index, item in enumerate(candidates, start=1):
        symmetry = item.space_group_symbol or "unknown"
        if item.space_group_number is not None:
            symmetry += f" ({item.space_group_number})"
        hull = "unknown" if item.energy_above_hull_ev_atom is None else f"{item.energy_above_hull_ev_atom:.6f}"
        gap = "unknown" if item.band_gap_ev is None else f"{item.band_gap_ev:.6f}"
        print(f"{index} | {item.material_id} | {item.formula} | {symmetry} | {hull} | {gap}")


def select_candidate(
    candidates: list[MaterialsProjectCandidate],
    *,
    selected_material_id: str | None = None,
    input_fn: Callable[[str], str] = input,
) -> MaterialsProjectCandidate:
    if not candidates:
        raise MaterialsProjectLookupError("Materials Project returned no matching structures")
    if len(candidates) == 1 and selected_material_id is None:
        return candidates[0]

    selection = selected_material_id
    if selection is None:
        selection = input_fn("Select a candidate by index or MP ID: ").strip()
    if selection.isdigit():
        index = int(selection)
        if 1 <= index <= len(candidates):
            return candidates[index - 1]
    for candidate in candidates:
        if candidate.material_id == selection:
            return candidate
    raise StructureRequestError("The selected index or MP ID is not in the candidate set")


def acquire_structure_with_agent(
    client,
    model: str,
    user_prompt: str,
    output_dir: Path,
    *,
    max_override: int | None = None,
    selected_material_id: str | None = None,
    input_fn: Callable[[str], str] = input,
    api_key: str | None = None,
    mp_client_factory=None,
) -> tuple[Path, dict, list[dict]]:
    """Parse, query, save, display, and select a Materials Project candidate."""
    query, usages = parse_structure_request(
        client, model, user_prompt,
        max_override=max_override,
        input_fn=input_fn,
    )
    candidates = fetch_materials_project_candidates(
        query,
        cache_dir=output_dir / "mp_cache",
        api_key=api_key,
        client_factory=mp_client_factory,
    )
    save_candidate_structures(candidates, output_dir)
    print_candidate_table(candidates)
    selected = select_candidate(
        candidates,
        selected_material_id=selected_material_id,
        input_fn=input_fn,
    )
    selected_path = (output_dir / str(selected.structure_file)).resolve()
    acquisition = {
        "mode": "materials_project",
        "query": query.to_dict(),
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "api_endpoint": "https://api.materialsproject.org",
        "include_gnome": False,
        "candidates": [candidate.to_metadata() for candidate in candidates],
        "selected_material_id": selected.material_id,
        "selected_structure_file": selected.structure_file,
        "llm_model": model,
        "requires_human_review": True,
        "limitations": [
            "A Materials Project bulk structure is a starting candidate, not a surface, adsorbate, or transition state",
            "Low energy_above_hull does not imply higher catalytic activity",
            "Entering the demonstration barrier workflow does not link its barrier to the downloaded structure",
        ],
    }
    return selected_path, acquisition, usages
