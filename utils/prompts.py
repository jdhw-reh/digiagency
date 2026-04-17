"""
Prompt loader — reads agent prompts from YAML config files.

All YAML files live under prompts/<team>/<agent>.yaml relative to the project
root. Each file is read from disk once per app startup and cached in memory —
subsequent calls return the cached dict without touching the filesystem.
"""

from pathlib import Path
from typing import Any

import yaml

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"

# Module-level in-memory cache: agent_path -> parsed YAML dict.
# Populated lazily on first access; persists for the lifetime of the process.
_cache: dict[str, dict[str, Any]] = {}


def load_prompt(agent_path: str) -> dict[str, Any]:
    """
    Load and cache the prompt config for the given agent path.

    agent_path: slash-separated path relative to prompts/, without the .yaml
                extension — e.g. "content/researcher", "social/scout".

    Returns the full parsed YAML dict. Raises FileNotFoundError if the file
    does not exist, or ValueError if the file does not contain a YAML mapping.
    """
    if agent_path in _cache:
        return _cache[agent_path]

    yaml_path = _PROMPTS_DIR / f"{agent_path}.yaml"
    if not yaml_path.exists():
        raise FileNotFoundError(
            f"Prompt file not found: {yaml_path}. "
            f"Expected a YAML file at prompts/{agent_path}.yaml"
        )

    with yaml_path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh)

    if not isinstance(data, dict):
        raise ValueError(
            f"Invalid prompt file (expected a YAML mapping, got {type(data).__name__}): "
            f"{yaml_path}"
        )

    _cache[agent_path] = data
    return data


def get_system_prompt(agent_path: str) -> str:
    """
    Return the system_prompt string for the given agent.

    Raises KeyError if the YAML file does not contain a 'system_prompt' key.
    """
    data = load_prompt(agent_path)
    prompt = data.get("system_prompt")
    if prompt is None:
        raise KeyError(
            f"'system_prompt' key not found in prompts/{agent_path}.yaml"
        )
    return prompt


def get_user_prompt(agent_path: str, **kwargs: Any) -> str:
    """
    Return the user_prompt_template for the given agent, formatted with kwargs.

    Calls str.format(**kwargs) on the 'user_prompt_template' value.
    Raises KeyError if the YAML file does not contain a 'user_prompt_template' key.
    """
    data = load_prompt(agent_path)
    template = data.get("user_prompt_template")
    if template is None:
        raise KeyError(
            f"'user_prompt_template' key not found in prompts/{agent_path}.yaml"
        )
    return template.format(**kwargs)
