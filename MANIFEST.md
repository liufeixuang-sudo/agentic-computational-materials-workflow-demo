# Release Manifest

## Core Python Modules

1. `run.py`
2. `agent_workflow.py`
3. `materials_project_structure_agent.py`
4. `structure_file_workflow.py`
5. `structure_molecule_summary.py`
6. `integrated_workflow.py`
7. `planner_fixture_lookup.py`
8. `planner_router.py`
9. `validator.py`
10. `simulation_adapter.py`
11. `fixture_adapter.py`
12. `reviewer.py`

## Data and Examples

- `pt.xyz`
- `pt_bulk.cif`
- `data/fixtures/catalysis_results.json`

## Documentation and Environment Templates

- `README.md`
- `docs/architecture.md`
- `docs/architecture.png`
- `docs/architecture.svg`
- `docs/code-walkthrough.md`
- `.env.example`
- `.gitignore`
- `.gitattributes`
- `requirements-demo.txt`
- `requirements-agent.txt`
- `requirements-dev.txt`
- `CITATION.cff`

## Excluded from Release

The release must not contain `.env`, credentials, `material_project.md`, virtual
environments, caches, IDE settings, generated outputs, or private research data.
