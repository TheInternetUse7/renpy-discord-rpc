import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
import tempfile
from typing import Any


@dataclass(frozen=True)
class GameConfig:
    name: str
    exe_name: str
    exe_path: str
    icon_url: str
    state: str
    details_template: str
    activity_type: int | None
    status_display_type: int | None


@dataclass(frozen=True)
class AppConfig:
    client_id: str
    scan_interval_seconds: float
    min_update_interval_seconds: float
    default_state: str
    default_large_text: str
    fallback_large_image: str
    activity_type: int | None
    status_display_type: int | None
    games: list[GameConfig]


def _as_str(value: Any) -> str:
    return "" if value is None else str(value)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _parse_activity_type(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        v = int(value)
        return v if v in {0, 2, 3, 5} else None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"playing", "play", "0"}:
        return 0
    if s in {"listening", "listen", "2"}:
        return 2
    if s in {"watching", "watch", "3"}:
        return 3
    if s in {"competing", "compete", "5"}:
        return 5
    try:
        v = int(s)
        return v if v in {0, 2, 3, 5} else None
    except Exception:
        return None


def _parse_status_display_type(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        v = int(value)
        return v if v in {0, 1, 2} else None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in {"name", "app", "0"}:
        return 0
    if s in {"state", "1"}:
        return 1
    if s in {"details", "detail", "2"}:
        return 2
    try:
        v = int(s)
        return v if v in {0, 1, 2} else None
    except Exception:
        return None


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
                activity_type=_parse_activity_type(raw.get("activity_type")),
                status_display_type=_parse_status_display_type(raw.get("status_display_type")),
            )
        )

    return AppConfig(
        client_id=_as_str(data.get("client_id")),
        scan_interval_seconds=_as_float(data.get("scan_interval_seconds"), 5.0),
        min_update_interval_seconds=_as_float(data.get("min_update_interval_seconds"), 15.0),
        default_state=_as_str(data.get("default_state")) or "Reading visual novel",
        default_large_text=_as_str(data.get("default_large_text")) or "Ren'Py Visual Novel",
        fallback_large_image=_as_str(data.get("fallback_large_image")) or "renpy",
        activity_type=_parse_activity_type(data.get("activity_type")),
        status_display_type=_parse_status_display_type(data.get("status_display_type")),
        games=games,
    )


def load_config_raw(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    return json.loads(path.read_text(encoding="utf-8"))


def save_config_raw(path: str | Path, data: dict[str, Any]) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, ensure_ascii=False)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent), prefix=path.name, suffix=".tmp") as f:
        f.write(payload)
        f.flush()
        os.fsync(f.fileno())
        tmp_name = f.name
    os.replace(tmp_name, path)


def ensure_config(path: str | Path) -> Path:
    path = Path(path)
    if path.exists():
        return path

    base_dir = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    example = base_dir / "config.example.json"
    if example.exists():
        data = json.loads(example.read_text(encoding="utf-8"))
    else:
        data = {
            "client_id": "1467506650771619982",
            "scan_interval_seconds": 5,
            "min_update_interval_seconds": 15,
            "default_state": "Reading visual novel",
            "default_large_text": "Ren'Py Visual Novel",
            "fallback_large_image": "renpy",
            "games": [],
        }

    save_config_raw(path, data)
    return path


def add_game_to_config(path: str | Path, exe_path: str) -> None:
    path = Path(path)
    data = load_config_raw(path)
    games = data.get("games")
    if not isinstance(games, list):
        games = []
        data["games"] = games

    exe_path_norm = str(Path(exe_path))
    exe_name = Path(exe_path_norm).name
    stem = Path(exe_path_norm).stem

    for g in games:
        if not isinstance(g, dict):
            continue
        existing_path = str(g.get("exe_path") or "")
        existing_name = str(g.get("exe_name") or "")
        if existing_path.lower() == exe_path_norm.lower() or existing_name.lower() == exe_name.lower():
            g["exe_path"] = exe_path_norm
            g["exe_name"] = exe_name
            if not g.get("name"):
                g["name"] = stem
            save_config_raw(path, data)
            return

    games.append(
        {
            "name": stem,
            "exe_name": exe_name,
            "exe_path": exe_path_norm,
            "icon_url": "",
            "state": "",
            "details_template": "{game}",
        }
    )
    save_config_raw(path, data)


def set_game_icon_url(path: str | Path, *, exe_path: str = "", exe_name: str = "", icon_url: str) -> bool:
    path = Path(path)
    data = load_config_raw(path)
    games = data.get("games")
    if not isinstance(games, list):
        return False

    exe_path_norm = str(Path(exe_path)) if exe_path else ""
    exe_name_norm = str(exe_name) if exe_name else ""

    for g in games:
        if not isinstance(g, dict):
            continue
        existing_path = str(g.get("exe_path") or "")
        existing_name = str(g.get("exe_name") or "")
        if exe_path_norm and existing_path.lower() == exe_path_norm.lower():
            g["icon_url"] = str(icon_url)
            save_config_raw(path, data)
            return True
        if exe_name_norm and existing_name.lower() == exe_name_norm.lower():
            g["icon_url"] = str(icon_url)
            save_config_raw(path, data)
            return True

    return False
