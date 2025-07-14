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
        # resolve relative to caller directory
        path = (Path(__file__).parent / path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Preset file not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    if isinstance(data, dict):
        parts = []
        # 1) collect system-level entries from prompts list
        if isinstance(data.get("prompts"), list):
            for item in data["prompts"]:
                if isinstance(item, dict) and item.get("role") == "system":
                    parts.append(_flatten(item.get("content", "")))
        # 2) single 'system' or 'input' fields (common in persona yaml)
        if "system" in data:
            parts.append(_flatten(data["system"]))
        if "input" in data:
            parts.append(_flatten(data["input"]))
        # 3) explicit 'prompt' key (fallback)
        if "prompt" in data:
            parts.append(_flatten(data["prompt"]))
        # join all collected parts
        return "\n".join(p for p in parts if p)

    # Fallback: treat entire YAML as a plain string or list
    return _flatten(data) 