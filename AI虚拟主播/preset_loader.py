import yaml
from pathlib import Path
from typing import List, Union

__all__ = ["load_preset"]

def _flatten(data: Union[str, List[str]]) -> str:
    if isinstance(data, str):
        return data.strip()
    if isinstance(data, list):
        return "\n".join(str(x).strip() for x in data if str(x).strip())
    return str(data)

def load_preset(preset_path: str | Path) -> str:
    """Load a YAML preset file and return a prompt string.
    Supports:
    - Plain string
    - List of strings (joined with newline)
    - Mapping with key 'prompt'
    """
    path = Path(preset_path)
    if not path.is_absolute():
        path = (Path(__file__).parent / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Preset file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict):
        parts = []
        if isinstance(data.get("prompts"), list):
            for item in data["prompts"]:
                if isinstance(item, dict) and item.get("role") == "system":
                    parts.append(_flatten(item.get("content", "")))
        if "prompt" in data:
            parts.append(_flatten(data["prompt"]))
        return "\n".join(p for p in parts if p)

    return _flatten(data) 