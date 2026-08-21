from __future__ import annotations

import ast
from pathlib import Path
import unittest

from state_and_persistence import (
    STATE_OWNERSHIP_MATRIX,
    canonical_capability_access,
    validate_ownership_matrix,
)


ROOT = Path(__file__).parents[2]
FEATURE_MODULES = (
    "assessment_evidence", "interaction_control", "perception", "pedagogy",
    "retrieval", "response_planning", "response_generation", "presentation",
)


class OwnershipRegistryTests(unittest.TestCase):
    def test_matrix_has_one_owner_for_each_field(self) -> None:
        validate_ownership_matrix()
        fields = {(field.scope, field.path) for field in STATE_OWNERSHIP_MATRIX}
        self.assertEqual(len(fields), len(STATE_OWNERSHIP_MATRIX))
        access = canonical_capability_access()
        self.assertIn("assessment_evidence", access)
        self.assertIn("interaction_control", access)

    def test_feature_modules_do_not_import_other_implementations(self) -> None:
        for module in FEATURE_MODULES:
            for path in (ROOT / module).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                type_checking_nodes: set[int] = set()
                for parent in ast.walk(tree):
                    if isinstance(parent, ast.If) and isinstance(parent.test, ast.Name) and parent.test.id == "TYPE_CHECKING":
                        type_checking_nodes.update(id(child) for child in ast.walk(parent))
                for node in ast.walk(tree):
                    imported = None
                    if isinstance(node, ast.Import):
                        imported = [alias.name.split(".")[0] for alias in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        imported = [node.module.split(".")[0]]
                    if imported and id(node) not in type_checking_nodes:
                        forbidden = set(imported) & set(FEATURE_MODULES) - {module}
                        self.assertFalse(
                            forbidden,
                            f"{path} imports Feature Module implementation {sorted(forbidden)}",
                        )

    def test_feature_modules_do_not_write_shared_state_directly(self) -> None:
        for module in FEATURE_MODULES:
            for path in (ROOT / module).glob("*.py"):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                for node in ast.walk(tree):
                    if isinstance(node, ast.Assign):
                        for target in node.targets:
                            if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Attribute) and target.value.attr == "data":
                                self.fail(f"{path} directly writes shared state")


if __name__ == "__main__":
    unittest.main()
