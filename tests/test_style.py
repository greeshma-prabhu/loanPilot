"""Static checks for shared LoanPilot page conventions."""

import ast
import re

from loanpilot.config import PROJECT_ROOT

PAGES_DIR = PROJECT_ROOT / "loanpilot" / "pages"
_ABSOLUTE_PATH = re.compile(r"(?<![\w])(?:[A-Za-z]:[\\/]|/(?:Users|home|tmp|var|etc|opt)/)")


def _page_files():
    """Return Python source files for all Streamlit pages."""
    return sorted(PAGES_DIR.glob("*.py"))


def test_pages_do_not_use_deprecated_container_width() -> None:
    """Use Streamlit's current width API throughout every page."""
    for path in _page_files():
        assert "use_container_width" not in path.read_text(encoding="utf-8")


def test_pages_do_not_contain_hard_coded_absolute_paths() -> None:
    """Keep local paths rooted in configuration rather than machine-specific."""
    for path in _page_files():
        source = path.read_text(encoding="utf-8")
        assert _ABSOLUTE_PATH.search(source) is None, path.name


def test_pages_do_not_write_raw_mapping_or_sequence_values() -> None:
    """Require dictionaries and collections to be rendered as readable fields."""
    for path in _page_files():
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        collection_names = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                value = node.value
                if isinstance(value, (ast.Dict, ast.List, ast.Set)):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    collection_names.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )
                elif isinstance(value, ast.Call) and (
                    ast.unparse(value.func) in {"dict", "list", "set", "json.loads"}
                ):
                    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                    collection_names.update(
                        target.id for target in targets if isinstance(target, ast.Name)
                    )
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or ast.unparse(node.func) != "st.write":
                continue
            if not node.args:
                continue
            value = node.args[0]
            assert not isinstance(value, (ast.Dict, ast.List, ast.Set)), path.name
            assert not (
                isinstance(value, ast.Name) and value.id in collection_names
            ), path.name
