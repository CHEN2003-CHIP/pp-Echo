from pathlib import Path


def test_python_multipart_is_base_dependency() -> None:
    pyproject = Path("pyproject.toml").read_text(encoding="utf-8")
    dependencies_section = pyproject.split("[project.optional-dependencies]", 1)[0]

    assert "python-multipart" in dependencies_section
