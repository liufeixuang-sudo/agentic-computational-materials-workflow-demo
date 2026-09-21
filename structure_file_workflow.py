"""Read a project-local structure, run the workflow, and save JSON/Markdown reports.

python structure_file_workflow.py pt.xyz --allow-demo
This offline entry point does not read .env or call external APIs.

Materials Project structures must first be saved under the project report
directory by the controlled acquisition layer.
"""

import argparse
import json
import tempfile
from pathlib import Path

from integrated_workflow import run_workflow


PROJECT_DIR = Path(__file__).resolve().parent


def run_from_structure(request: dict, path: Path, *,
                       allow_mock: bool = False, allow_demo: bool = False) -> dict:
    path = path.resolve()
    if not path.is_relative_to(PROJECT_DIR):
        raise ValueError("Structure files must be located inside the project directory")
    try:
        # Reuse the same non-periodic Molecule and periodic Structure branches.
        from structure_molecule_summary import summarize_structure
        structure = summarize_structure(str(path))
    except ImportError:
        raise  # Report a missing dependency explicitly rather than as a structure error.
    except (OSError, ValueError, TypeError, IndexError, KeyError) as exc:
        return {
            "request": request, "structure_path": str(path),
            "status": "blocked_structure", "error_type": type(exc).__name__,
            "trace": ["structure_read"], "execution": None, "review": None,
        }
    report = run_workflow(request, structure,
                          allow_mock=allow_mock, allow_demo=allow_demo)
    report["structure"] = structure
    report["trace"].insert(0, "structure_read")
    return report


def to_markdown(report: dict) -> str:
    execution = report.get("execution") or {}
    review = report.get("review") or {}
    structure = report.get("structure") or {}
    lines = [
        "# Catalytic Barrier Screening Report", "",
        f"- Workflow status: {report['status']}",
        f"- Structure file: {structure.get('source', report.get('structure_path', 'not read'))}",
        f"- Structure type: {structure.get('structure_type', 'unknown')}",
        f"- Number of sites: {structure.get('num_sites', 'unknown')}",
        f"- Execution result type: {execution.get('result_type', 'not executed')}",
        f"- Barrier provenance: {execution.get('source', 'none')}",
        f"- Barrier (eV): {execution.get('energy_barrier_ev', 'none')}",
        f"- Screening decision: {review.get('decision', 'not reviewed')}",
        "", "## Execution Trace", "",
        " -> ".join(report["trace"]), "",
    ]

    acquisition = report.get("structure_acquisition") or {}
    if acquisition:
        query = acquisition.get("query") or {}
        lines.extend([
            "## Materials Project Structure Acquisition", "",
            f"- Acquisition mode: {acquisition.get('mode', 'unknown')}",
            f"- Formula query: {query.get('formula', 'unknown')}",
            f"- Space-group symbol: {query.get('spacegroup_symbol') or 'not constrained'}",
            f"- Space-group number: {query.get('spacegroup_number') or 'not constrained'}",
            f"- Crystal system: {query.get('crystal_system') or 'not constrained'}",
            f"- Candidate limit: {query.get('max_structures', 'unknown')}",
            f"- Selected MP ID: {acquisition.get('selected_material_id', 'not selected')}",
            "", "| MP ID | Formula | Space group | Energy Above Hull (eV/atom) | Band Gap (eV) | CIF |",
            "|---|---|---|---:|---:|---|",
        ])
        for candidate in acquisition.get("candidates", []):
            symbol = candidate.get("space_group_symbol") or "unknown"
            number = candidate.get("space_group_number")
            if number is not None:
                symbol += f" ({number})"
            hull = candidate.get("energy_above_hull_ev_atom")
            gap = candidate.get("band_gap_ev")
            lines.append(
                f"| {candidate.get('material_id', 'unknown')} | "
                f"{candidate.get('formula', 'unknown')} | {symbol} | "
                f"{hull if hull is not None else 'unknown'} | "
                f"{gap if gap is not None else 'unknown'} | "
                f"{candidate.get('structure_file', 'not saved')} |"
            )
        lines.extend([""])
        lines.extend(
            f"- Structure-acquisition limitation: {item}"
            for item in acquisition.get("limitations", [])
        )
        lines.append("")
    lines.extend(["## Validation and Limitations", ""])
    for key in ("input_validation", "output_validation"):
        validation = report.get(key) or {}
        lines.extend(f"- Error: {item}" for item in validation.get("errors", []))
        lines.extend(f"- Warning: {item}" for item in validation.get("warnings", []))
    if report.get("error_type"):
        lines.append(f"- Exception type: {report['error_type']}")
    if report.get("error_message"):
        lines.append(f"- Exception: {report['error_message']}")
    lines.extend(f"- {item}" for item in review.get("limitations", []))
    lines.extend([
        "- Structure parsing validates input only; it does not link the barrier to that structure.",
        "- Fixture and mock values are synthetic; no real VASP or LAMMPS calculation was run.",
        (
            "- The Agent supplies constrained tool parameters and a review; Python controls execution."
            if report.get("agent")
            else "- The offline entry has no model planner; the human-review flag is not an approval gate."
        ),
        "",
    ])
    return "\n".join(lines)


def create_report_directory() -> Path:
    base = PROJECT_DIR / "outputs" / "reports"
    base.mkdir(parents=True, exist_ok=True)
    # Create a unique directory for every run to preserve provenance.
    return Path(tempfile.mkdtemp(prefix="structure_run_", dir=base)).resolve()


def write_reports(report: dict, output_dir: Path) -> None:
    output_dir = output_dir.resolve()
    if not output_dir.is_relative_to(PROJECT_DIR):
        raise ValueError("Reports must be written inside the project directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "report.md").write_text(to_markdown(report), encoding="utf-8")


def save_reports(report: dict, output_dir: Path | None = None) -> Path:
    output_dir = output_dir.resolve() if output_dir else create_report_directory()
    write_reports(report, output_dir)
    return output_dir


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("structure", nargs="?", default="pt.xyz")
    parser.add_argument("--task-id", default="co2_hydrogenation_001")
    parser.add_argument("--catalyst", default="Pt")
    parser.add_argument("--threshold-ev", type=float, default=1.0)
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--allow-demo", action="store_true")
    args = parser.parse_args()
    request = {"task_id": args.task_id, "catalyst": args.catalyst,
               "threshold_ev": args.threshold_ev}
    path = Path(args.structure)
    if not path.is_absolute():
        path = PROJECT_DIR / path
    report = run_from_structure(request, path,
                                allow_mock=args.allow_mock, allow_demo=args.allow_demo)
    output_dir = save_reports(report)
    print("Status:", report["status"])
    print("Trace:", " -> ".join(report["trace"]))
    print("Report directory:", output_dir)


if __name__ == "__main__":
    main()
