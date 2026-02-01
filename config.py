import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class GameConfig:
    name: str
    exe_name: str
    exe_path: str
    icon_url: str
    state: str
    details_template: str


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    scan_interval_seconds: float
    min_update_interval_seconds: float
    default_state: str
    default_large_text: str
    fallback_large_image: str
    games: list[GameConfig]


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def load_config(path: str | Path) -> AppConfig:
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))

    games: list[GameConfig] = []
    for raw in data.get("games", []) or []:
        games.append(
            GameConfig(
                name=_as_str(raw.get("name")),
                exe_name=_as_str(raw.get("exe_name")).lower(),
                exe_path=_as_str(raw.get("exe_path")),
                icon_url=_as_str(raw.get("icon_url")),
                state=_as_str(raw.get("state")),
                details_template=_as_str(raw.get("details_template")) or "{title}",
            )
        )

    return AppConfig(
        client_id=_as_str(data.get("client_id")),
        scan_interval_seconds=_as_float(data.get("scan_interval_seconds"), 5.0),
        min_update_interval_seconds=_as_float(data.get("min_update_interval_seconds"), 15.0),
        default_state=_as_str(data.get("default_state")) or "Reading visual novel",
        default_large_text=_as_str(data.get("default_large_text")) or "Ren'Py Visual Novel",
        fallback_large_image=_as_str(data.get("fallback_large_image")) or "renpy",
        games=games,
    )
