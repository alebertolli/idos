import importlib.util
from pathlib import Path
from zipfile import ZipFile

import pytest


spec = importlib.util.spec_from_file_location("check_wheel_contents", Path(__file__).resolve().parents[3] / "scripts/check_wheel_contents.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


@pytest.mark.parametrize("extra", [None, "tests/test_example.py", "build/lib/idos/__init__.py"])
def test_distributable_contains_only_runtime_package_and_metadata(tmp_path, extra):
    wheel = tmp_path / "idos_core-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        for name in ("idos/__init__.py", "idos/cli/main.py", "idos_core-0.1.0.dist-info/METADATA", "idos_core-0.1.0.dist-info/WHEEL"):
            archive.writestr(name, "")
        if extra:
            archive.writestr(extra, "")
    if extra:
        with pytest.raises(ValueError, match="unexpected"):
            checker.validate_wheel(wheel)
    else:
        assert checker.validate_wheel(wheel)["python_modules"] == 2


def test_missing_runtime_entrypoint_is_rejected(tmp_path):
    wheel = tmp_path / "idos_core-0.1.0-py3-none-any.whl"
    with ZipFile(wheel, "w") as archive:
        archive.writestr("idos/__init__.py", "")
    with pytest.raises(ValueError, match="idos/cli/main.py"):
        checker.validate_wheel(wheel)
