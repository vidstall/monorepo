import unittest
from pathlib import Path


class StructureTests(unittest.TestCase):
    def test_python_files_do_not_exceed_200_lines(self) -> None:
        project_root = Path(__file__).resolve().parents[1]
        oversized = {
            str(path.relative_to(project_root)): len(path.read_text(encoding="utf-8").splitlines())
            for path in project_root.rglob("*.py")
            if ".venv" not in path.parts
            and len(path.read_text(encoding="utf-8").splitlines()) > 200
        }
        self.assertEqual(oversized, {})


if __name__ == "__main__":
    unittest.main()
