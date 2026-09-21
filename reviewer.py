"""Review validated results while preserving provenance and scientific limits.

Run: python reviewer.py
The standalone examples use synthetic data and do not call an LLM or simulator.
"""

import json

from validator import ValidationReport, is_finite_number, validate_output


def review_result(request: dict, output: dict, validation: ValidationReport) -> dict:
    if not validation.can_continue:
        return {
            "decision": "blocked",
            "reason": "The output failed validation; numerical screening was not performed",
            "errors": validation.errors,
            "requires_human_review": True,
        }

    barrier = output["energy_barrier_ev"]
    threshold = request["threshold_ev"]
    passes = barrier <= threshold
    review = {
        "threshold_passed": passes,
        "reason": f"Barrier {barrier} eV {'<=' if passes else '>'} threshold {threshold} eV",
        "source": output["source"],
        "result_type": output["result_type"],
        "warnings": list(validation.warnings),
        "limitations": [],
        "requires_human_review": True,
    }
    if output["result_type"] in ("mock", "synthetic_demo_fixture"):
        review["decision"] = "demo_candidate" if passes else "demo_deprioritize"
        review["limitations"].append(
            "Demonstration data validate workflow behavior, not catalytic activity"
        )
    else:
        print("Checking scientific context for a non-demonstration result")
        temperature = output.get("temperature_k")
        context_ok = (
            output.get("energy_kind") == "free_energy_barrier"
            and output.get("energy_unit") == "eV"
            and is_finite_number(temperature)
            and temperature > 0
        )
        if not context_ok:
            review["decision"] = "manual_review"
            review["limitations"].append(
                "Confirm the free-energy barrier definition, units, and temperature before scientific screening"
            )
        else:
            review["decision"] = "candidate" if passes else "deprioritize"
            review["limitations"].append(
                "Single-metric preliminary screening; verify settings, stability, selectivity, and mechanism"
            )
    review["limitations"].append(
        "No numerical uncertainty was supplied, so no confidence or error interval is reported"
    )
    return review


def main() -> None:
    request = {"task_id": "reaction_001", "catalyst": "Pt", "threshold_ev": 1.0}
    demo = {
        "task_id": "reaction_001", "status": "completed",
        "energy_barrier_ev": 0.82, "source": "synthetic_demo_fixture_001",
        "result_type": "synthetic_demo_fixture",
    }
    # The real_calculation label below exercises a branch; it is not real scientific data.
    real_label_example = {**demo, "result_type": "real_calculation", "source": "hypothetical_calculation_record"}
    cases = {
        "low_barrier_demo": demo,
        "high_barrier_demo": {**demo, "energy_barrier_ev": 1.18},
        "non_demo_label_without_context": real_label_example,
        "hypothetical_case_with_context": {
            **real_label_example, "energy_barrier_ev": 1.18, "energy_kind": "free_energy_barrier",
            "energy_unit": "eV", "temperature_k": 298.15,"task_id": "reaction_wrong",
        },
    }
    for name, output in cases.items():
        validation = validate_output(request, output, allow_demo=True)
        print(f"\nCase: {name}")
        print(json.dumps(review_result(request, output, validation), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
