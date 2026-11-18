"""Check the IDOS distributable without installing or extracting its contents."""
import argparse
import json
from pathlib import Path
from zipfile import ZipFile


def validate_wheel(path: Path) -> dict:
    with ZipFile(path) as archive:
        names = archive.namelist()
    allowed_metadata = path.name.split("-", 2)
    metadata_root = f"{allowed_metadata[0]}-{allowed_metadata[1]}.dist-info/"
    invalid = [name for name in names if not name.startswith(("idos/", metadata_root))]
    required = {"idos/__init__.py", "idos/cli/main.py", metadata_root + "METADATA", metadata_root + "WHEEL"}
    missing = required.difference(names)
    if invalid or missing:
        raise ValueError(f"Invalid wheel contents: unexpected={invalid[:5]}, missing={sorted(missing)}")
    return {"wheel": path.name, "files": len(names), "python_modules": sum(name.endswith(".py") for name in names)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_wheel(args.wheel), sort_keys=True))


if __name__ == "__main__":
    main()
