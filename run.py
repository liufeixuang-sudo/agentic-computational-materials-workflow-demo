"""One-command offline demo; does not read credentials or call external APIs."""

import sys

from structure_file_workflow import main


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print(
            "Running the offline demonstration with synthetic data. "
            "This does not constitute a scientific result or human approval."
        )
        sys.argv.extend(["pt.xyz", "--allow-demo"])
    main()
