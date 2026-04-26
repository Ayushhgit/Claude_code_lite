import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from core.verify import check_compile, check_imports


def test_compile_respects_simple_gitignore_directory(tmp_path):
    (tmp_path / ".gitignore").write_text("ignored_artifacts/\n", encoding="utf-8")
    (tmp_path / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

    ignored_dir = tmp_path / "ignored_artifacts"
    ignored_dir.mkdir()
    (ignored_dir / "broken.py").write_text("def nope(:\n", encoding="utf-8")

    result = check_compile(str(tmp_path))

    assert result["failed"] == []
    assert result["passed"] == ["app.py"]


def test_import_check_uses_ast_not_regex_over_strings(tmp_path):
    src = tmp_path / "src"
    package = src / "pkg"
    package.mkdir(parents=True)
    (src / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    (src / "main.py").write_text(
        '"""from imaginary.module import nope"""\nfrom pkg import helper\n',
        encoding="utf-8",
    )

    cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        result = check_imports(".")
    finally:
        os.chdir(cwd)

    assert result["warnings"] == []
    assert any("pkg" in passed for passed in result["passed"])
