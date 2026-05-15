import json
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path


def load_json(filepath: Path) -> Any:
    with open(filepath, encoding="utf-8") as file:
        return json.load(file)


def write_json(filepath: Path, data: Any) -> None:
    with open(filepath, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
