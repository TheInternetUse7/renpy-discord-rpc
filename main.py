from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from config import AppConfig, ensure_config, load_config
from detection import find_running_game
from presence import DiscordRPC
from utils import looks_like_path, sanitize_title
from tray import TrayApp


def _log(msg: str) -> None:
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {msg}", flush=True)


def _build_match_sets(cfg: AppConfig) -> tuple[set[str], set[str]]:
    exe_names: set[str] = set()
    exe_paths: set[str] = set()

    for g in cfg.games:
        if g.exe_name:
            exe_names.add(g.exe_name.lower())
        if g.exe_path:
            exe_paths.add(str(Path(g.exe_path)))

    return exe_names, exe_paths


def _safe_format(template: str, values: dict[str, str]) -> str:
    try:
        return template.format(**values)
    except Exception:
        return values.get("game") or values.get("title") or "Ren'Py Visual Novel"


def run(cfg_path: Path, once: bool) -> int:
    cfg = load_config(cfg_path)
    exe_names, exe_paths = _build_match_sets(cfg)

    if not cfg.client_id:
        _log("Set client_id in config.json")
        return 2

    if not exe_names and not exe_paths:
        _log("No games configured (set exe_name or exe_path in config.json)")

    rpc = DiscordRPC(cfg.client_id, min_update_interval_seconds=cfg.min_update_interval_seconds)

    try:
        rpc.connect()
        _log("Connected to Discord RPC")

        _log(f"Configured exe_names: {sorted(exe_names) if exe_names else '[]'}")
        _log(f"Configured exe_paths: {sorted(exe_paths) if exe_paths else '[]'}")

        while True:
            found = find_running_game(exe_names, exe_paths)
            if found is None:
                _log("No matching process found")
                rpc.clear()
                if once:
                    return 0
                time.sleep(cfg.scan_interval_seconds)
                continue

            _log(f"Matched pid={found.pid} exe_name={found.exe_name} exe_path={found.exe_path}")

            title = sanitize_title(found.window_title)

            matched = None
            for g in cfg.games:
                if g.exe_name and g.exe_name.lower() == found.exe_name.lower():
                    matched = g
                    break
                if g.exe_path and str(Path(g.exe_path)).lower() == (found.exe_path or "").lower():
                    matched = g
                    break

            game_name = ""
            if matched and matched.name:
                game_name = matched.name
            else:
                game_name = Path(found.exe_name).stem if found.exe_name else ""
            if not game_name:
                game_name = "Ren'Py Visual Novel"

            if not title or looks_like_path(title):
                title = game_name

            details_template = matched.details_template if matched else "{game}"
            details = _safe_format(details_template, {"title": title, "game": game_name})
            if looks_like_path(details):
                details = game_name
            state = (matched.state if matched and matched.state else cfg.default_state) or cfg.default_state
            large_image = (matched.icon_url if matched and matched.icon_url else cfg.fallback_large_image) or cfg.fallback_large_image
            large_text = cfg.default_large_text

            activity_type = (
                matched.activity_type
                if matched is not None and matched.activity_type is not None
                else cfg.activity_type
            )
            status_display_type = (
                matched.status_display_type
                if matched is not None and matched.status_display_type is not None
                else cfg.status_display_type
            )

            try:
                if large_image:
                    rpc.update(
                        details=details,
                        state=state,
                        name=game_name,
                        activity_type=activity_type,
                        status_display_type=status_display_type,
                        large_image=large_image,
                        large_text=large_text,
                    )
                else:
                    rpc.update(
                        details=details,
                        state=state,
                        name=game_name,
                        activity_type=activity_type,
                        status_display_type=status_display_type,
                    )
                _log(
                    f"RPC update sent: details={details!r} state={state!r} "
                    f"large_image={'set' if large_image else 'unset'}"
                )
            except Exception as e:
                _log(f"RPC update failed: {e}")
                try:
                    rpc.update(
                        details=details,
                        state=state,
                        name=game_name,
                        activity_type=activity_type,
                        status_display_type=status_display_type,
                    )
                    _log("RPC update retried without images")
                except Exception as e2:
                    _log(f"RPC update retry failed: {e2}")

            if once:
                return 0

            time.sleep(cfg.scan_interval_seconds)

    except KeyboardInterrupt:
        return 0
    except Exception as e:
        _log(f"Error: {e}")
        return 1
    finally:
        try:
            rpc.clear(force=True)
        except Exception:
            pass
        try:
            rpc.close()
        except Exception:
            pass


def _resolve_config_path(arg: str) -> Path:
    p = Path(arg)
    if not p.is_absolute():
        if getattr(sys, "frozen", False):
            base_dir = Path(sys.executable).resolve().parent
        else:
            base_dir = Path.cwd()
        p = base_dir / p

    try:
        return ensure_config(p)
    except OSError:
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else (Path.home() / "AppData" / "Roaming")
        fallback = base / "renpy-discord-rpc" / "config.json"
        return ensure_config(fallback)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="renpy-discord-rpc")
    parser.add_argument("--config", default="config.json")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--cli", action="store_true")
    args = parser.parse_args(argv)

    cfg_path = _resolve_config_path(str(args.config))

    if args.cli or args.once:
        return run(cfg_path, once=bool(args.once))

    TrayApp(cfg_path).start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
