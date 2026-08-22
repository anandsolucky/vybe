"""Load persona specs from avatars/<lang>/<id>.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import ROOT


@dataclass
class Avatar:
    id: str
    name: str
    description: str
    language: str
    status: str
    engine: str
    engine_config: dict
    style: dict
    approved_sample: str
    speaking_rate_wps: float = 3.0
    raw: dict = field(default_factory=dict)

    @property
    def voice_id(self) -> str:
        cfg = self.engine_config
        return cfg.get("voice_id")

    @property
    def voice_settings(self) -> dict:
        return self.engine_config.get("voice_settings", {})


def load_avatar(language: str, avatar_id: str, root: Path = ROOT) -> Avatar:
    path = root / "avatars" / language / f"{avatar_id}.yaml"
    if not path.exists():
        # Custom VYBES the viewer made live here. They work in every
        # language, so they sit outside the language folders.
        path = root / "avatars" / "custom" / f"{avatar_id}.yaml"
    data = yaml.safe_load(path.read_text())
    return Avatar(
        id=data["id"],
        name=data["name"],
        description=data["description"],
        language=data["language"],
        status=data["status"],
        engine=data["engine"],
        engine_config=data.get("engine_config", {}),
        style=data.get("style", {}),
        approved_sample=data.get("approved_sample", ""),
        speaking_rate_wps=data.get("speaking_rate_wps", 3.0),
        raw=data,
    )


def list_avatars(language: str, root: Path = ROOT) -> list[str]:
    """Shipped personas first, then whatever the viewer has created."""
    lang_dir = root / "avatars" / language
    shipped = sorted(p.stem for p in lang_dir.glob("*.yaml"))
    custom_dir = root / "avatars" / "custom"
    custom = sorted(p.stem for p in custom_dir.glob("*.yaml")) \
        if custom_dir.exists() else []
    return shipped + [c for c in custom if c not in shipped]
