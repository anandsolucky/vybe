"""Load .env and config.yaml from the project root."""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def load_env(root: Path = ROOT) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def load_config(root: Path = ROOT) -> dict:
    return yaml.safe_load((root / "config.yaml").read_text())
