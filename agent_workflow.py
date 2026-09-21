"""DeepSeek tool planning with optional Materials Project structure retrieval.

The model proposes only whitelisted parameters. Python controls file paths and
Mock, Demo, and Materials Project permissions. This module can call external
APIs but never prints API keys.
"""

import argparse
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from materials_project_structure_agent import (
    MAX_STRUCTURES_LIMIT,
    MaterialsProjectLookupError,
    StructureRequestError,
    acquire_structure_with_agent,
)
from structure_file_workflow import (
    create_report_directory,
    run_from_structure,
    save_reports,
)


PROJECT_DIR = Path(__file__).resolve().parent
PLAN_TOOL = {
    "type": "function", "name": "run_materials_workflow",
    "description": "Plan and request a catalytic reaction barrier screening workflow.",
    "parameters": {
        "type": "object",
        "properties": {
            "task_id": {"type": "string", "description": "Task or reaction record identifier"},
            "catalyst": {"type": "string", "description": "Catalyst name"},
            "threshold_ev": {"type": "number", "description": "Barrier threshold in eV"},
        },
        "required": ["task_id", "catalyst", "threshold_ev"],
        "additionalProperties": False,
    },
}


def usage_dict(response) -> dict:
    usage = response.usage
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "cached_tokens": getattr(usage.input_tokens_details, "cached_tokens", None),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "prompt", nargs="?",
        default=(
            "Screen the local co2_hydrogenation_001 record for Pt using a "
            "2.0 eV barrier threshold."
        ),
    )
    parser.add_argument("--structure", default="pt.xyz")
    parser.add_argument("--allow-mock", action="store_true")
    parser.add_argument("--allow-demo", action="store_true")
    parser.add_argument(
        "--allow-mp", action="store_true",
        help="Explicitly allow Materials Project lookup when the local structure is missing",
    )
    parser.add_argument(
        "--structure-request",
        help="Natural-language structure request; defaults to the main task prompt",
    )
    parser.add_argument(
        "--max-structures", type=int,
        help=f"Maximum number of Materials Project candidates (1-{MAX_STRUCTURES_LIMIT})",
    )
    parser.add_argument(
        "--select-material-id",
        help="Select an MP ID non-interactively; otherwise multiple candidates require input",
    )
    args = parser.parse_args()
    if args.max_structures is not None and not 1 <= args.max_structures <= MAX_STRUCTURES_LIMIT:
        parser.error(f"--max-structures must be between 1 and {MAX_STRUCTURES_LIMIT}")

    load_dotenv()
    api_key = os.getenv("DEEPSEEK_API_KEY")
    base_url = os.getenv("DEEPSEEK_BASE_URL")
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
    if not api_key or not base_url:
        raise RuntimeError("Configure DEEPSEEK_API_KEY and DEEPSEEK_BASE_URL in local .env")

    client = OpenAI(api_key=api_key, base_url=base_url)
    first = client.responses.create(
        model=model,
        instructions=(
            "You are a computational materials task planner. You must call "
            "run_materials_workflow. Extract only an explicitly supplied task ID, "
            "catalyst, and threshold in eV. Never invent calculation results."
        ), input=args.prompt, tools=[PLAN_TOOL],
    )
    calls = [item for item in first.output if item.type == "function_call"]
    if len(calls) != 1 or calls[0].name != "run_materials_workflow":
        raise RuntimeError("The model did not produce one supported workflow tool call")
    call = calls[0]
    request = json.loads(call.arguments)
    if set(request) != {"task_id", "catalyst", "threshold_ev"}:
        raise ValueError("The model tool arguments do not match the field whitelist")

    structure_path = Path(args.structure)
    if not structure_path.is_absolute():
        structure_path = PROJECT_DIR / structure_path
    output_dir = create_report_directory()
    structure_agent_usage: list[dict] = []

    if structure_path.is_file():
        report = run_from_structure(
            request, structure_path,
            allow_mock=args.allow_mock, allow_demo=args.allow_demo,
        )
    elif not args.allow_mp:
        report = {
            "request": request,
            "structure_path": str(structure_path.resolve()),
            "status": "needs_structure",
            "error_type": "FileNotFoundError",
            "error_message": (
                "The local structure does not exist and Materials Project lookup is not authorized"
            ),
            "trace": ["structure_resolution"],
            "execution": None,
            "review": None,
        }
    else:
        try:
            structure_prompt = args.structure_request or args.prompt
            structure_path, acquisition, structure_agent_usage = acquire_structure_with_agent(
                client,
                model,
                structure_prompt,
                output_dir,
                max_override=args.max_structures,
                selected_material_id=args.select_material_id,
            )
            report = run_from_structure(
                request, structure_path,
                allow_mock=args.allow_mock, allow_demo=args.allow_demo,
            )
            report["structure_acquisition"] = acquisition
            report["trace"].insert(0, "structure_acquisition")
        except (StructureRequestError, MaterialsProjectLookupError) as exc:
            report = {
                "request": request,
                "structure_path": str(structure_path.resolve()),
                "status": "blocked_structure_lookup",
                "error_type": type(exc).__name__,
                "error_message": str(exc),
                "trace": ["structure_acquisition"],
                "execution": None,
                "review": None,
            }

    report["agent"] = {
        "model": model, "tool": call.name, "planned_request": request,
        "first_usage": usage_dict(first),
        "structure_agent_usage": structure_agent_usage,
        "permission_boundary": {
            "allow_mock": args.allow_mock, "allow_demo": args.allow_demo,
            "allow_materials_project": args.allow_mp,
            "controlled_by": "local_cli_not_model",
        },
    }
    save_reports(report, output_dir)
    tool_output = {
        "status": report["status"], "trace": report["trace"],
        "review": report.get("review"), "report_directory": str(output_dir),
        "input_validation": report.get("input_validation"),
        "output_validation": report.get("output_validation"),
        "structure_acquisition": report.get("structure_acquisition"),
        "error_type": report.get("error_type"),
        "error_message": report.get("error_message"),
    }
    final = client.responses.create(
        model=model,
        instructions=(
            "Briefly review the Python tool result. Strictly distinguish workflow status, "
            "demonstration data, and scientific conclusions. Do not describe completed "
            "as human approval or successful real-world simulation."
        ),
        input=[
            *first.output,
            {"type": "function_call_output", "call_id": call.call_id,
             "output": json.dumps(tool_output, ensure_ascii=False)},
        ],
    )
    report["agent"]["final_usage"] = usage_dict(final)
    report["agent"]["final_summary"] = final.output_text
    # Update the same report directory with final model metadata.
    save_reports(report, output_dir)
    print("Model plan:", json.dumps(request, ensure_ascii=False))
    print("Workflow status:", report["status"])
    print("Execution trace:", " -> ".join(report["trace"]))
    print("Model review:", final.output_text)
    print("Planning usage:", usage_dict(first))
    print("Review usage:", usage_dict(final))
    print("Report directory:", output_dir)


if __name__ == "__main__":
    main()
