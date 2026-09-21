import json
import sys

from ase.io import read
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.core import Molecule
from pymatgen.symmetry.analyzer import SpacegroupAnalyzer


def summarize_structure(path: str) -> dict:
    atoms = read(path)

    # XYZ files commonly represent non-periodic systems without a unit cell.
    if atoms.cell.volume == 0:
        molecule = Molecule(
            atoms.get_chemical_symbols(),
            atoms.get_positions(),
        )

        return {
            "source": path,
            "structure_type": "molecule",
            "formula": molecule.composition.formula,
            "num_sites": len(molecule),
            "elements": sorted(
                str(element)
                for element in molecule.composition.elements
            ),
            "status": "valid",
            "periodic": False,
        }

    # CIF, POSCAR, and related formats commonly represent periodic structures.
    structure = AseAtomsAdaptor.get_structure(atoms)
    analyzer = SpacegroupAnalyzer(structure, symprec=0.1)

    return {
        "source": path,
        "structure_type": "periodic_structure",
        "formula": structure.composition.formula,
        "num_sites": len(structure),
        "elements": sorted(
            str(element)
            for element in structure.composition.elements
        ),
        "volume_angstrom3": structure.volume,
        "lattice_abc_angstrom": list(structure.lattice.abc),
        "space_group_symbol": analyzer.get_space_group_symbol(),
        "space_group_number": analyzer.get_space_group_number(),
        "crystal_system": analyzer.get_crystal_system(),
        "status": "valid",
        "periodic": True,
    }


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python structure_molecule_summary.py <structure-file>"
        )

    result = summarize_structure(sys.argv[1])
    print(json.dumps(result, ensure_ascii=False, indent=2))
