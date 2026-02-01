from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

from config import add_game_to_config, load_config
from detection import find_running_game
from presence import DiscordRPC
from utils import looks_like_path, sanitize_title


def _safe_format(template: str, values: dict[str, str]) -> str:
    try:
        return template.format(**values)
    except Exception:
        return values.get("game") or values.get("title") or "Ren'Py Visual Novel"


@dataclass
class LoopState:
    paused: bool = False


class TrayApp:
    def __init__(self, config_path: Path) -> None:
        self.config_path = config_path
        self.state = LoopState()
        self._stop_event = threading.Event()
        self._worker: threading.Thread | None = None
        self._rpc: DiscordRPC | None = None
        self._last_mtime: float | None = None
        self._cfg_lock = threading.Lock()
        self._cfg = load_config(self.config_path)

        self._icon = None
        self._img_running = None
        self._img_paused = None

    def _reload_config_if_changed(self) -> None:
        try:
            mtime = self.config_path.stat().st_mtime
        except Exception:
            return

        if self._last_mtime is None or mtime != self._last_mtime:
            with self._cfg_lock:
                self._cfg = load_config(self.config_path)
                self._last_mtime = mtime

    def _compute_presence(self) -> tuple[str, str, str | None, str | None] | None:
        cfg = self._cfg

        exe_names = {g.exe_name.lower() for g in cfg.games if g.exe_name}
        exe_paths = {g.exe_path for g in cfg.games if g.exe_path}

        found = find_running_game(exe_names, exe_paths)
        if found is None:
            return None

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

        if not large_image:
            return details, state, None, None

        return details, state, large_image, large_text

    def _ensure_rpc(self) -> DiscordRPC | None:
        self._reload_config_if_changed()
        cfg = self._cfg
        if not cfg.client_id:
            return None

        if self._rpc is None:
            self._rpc = DiscordRPC(cfg.client_id, min_update_interval_seconds=cfg.min_update_interval_seconds)

        try:
            self._rpc.connect()
            return self._rpc
        except Exception:
            return None

    def _worker_loop(self) -> None:
        last_presence: tuple[str, str, str | None, str | None] | None = None
        was_paused = False

        while not self._stop_event.is_set():
            self._reload_config_if_changed()
            cfg = self._cfg

            if self.state.paused:
                if not was_paused:
                    rpc = self._ensure_rpc()
                    if rpc is not None:
                        try:
                            rpc.clear(force=True)
                        except Exception:
                            pass
                    was_paused = True
                time.sleep(max(0.25, cfg.scan_interval_seconds))
                continue

            was_paused = False

            rpc = self._ensure_rpc()
            if rpc is None:
                time.sleep(2.0)
                continue

            presence = self._compute_presence()
            if presence is None:
                if last_presence is not None:
                    try:
                        rpc.clear()
                    except Exception:
                        pass
                last_presence = None
                time.sleep(cfg.scan_interval_seconds)
                continue

            details, state, large_image, large_text = presence

            try:
                rpc.update(details=details, state=state, large_image=large_image, large_text=large_text)
                last_presence = presence
            except Exception:
                try:
                    rpc.update(details=details, state=state)
                    last_presence = (details, state, None, None)
                except Exception:
                    pass

            time.sleep(cfg.scan_interval_seconds)

        rpc = self._rpc
        if rpc is not None:
            try:
                rpc.clear(force=True)
            except Exception:
                pass
            try:
                rpc.close()
            except Exception:
                pass

    def _build_images(self):
        try:
            from PIL import Image, ImageDraw

            def make(color: tuple[int, int, int]) -> Image.Image:
                img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
                draw = ImageDraw.Draw(img)
                draw.ellipse((10, 10, 54, 54), fill=color + (255,))
                draw.ellipse((18, 18, 46, 46), fill=(0, 0, 0, 0))
                return img

            self._img_running = make((0, 200, 0))
            self._img_paused = make((140, 140, 140))
        except Exception:
            self._img_running = None
            self._img_paused = None

    def _set_icon_image(self) -> None:
        if self._icon is None:
            return
        img = self._img_paused if self.state.paused else self._img_running
        if img is None:
            return
        self._icon.icon = img

    def start(self) -> None:
        self._build_images()

        self._worker = threading.Thread(target=self._worker_loop, name="rpc-loop", daemon=False)
        self._worker.start()

        from pystray import Icon, Menu, MenuItem

        def on_toggle_pause(_: Icon, __):
            self.state.paused = not self.state.paused
            if self.state.paused:
                rpc = self._ensure_rpc()
                if rpc is not None:
                    try:
                        rpc.clear(force=True)
                    except Exception:
                        pass
            self._set_icon_image()

        def on_add_game(_: Icon, __):
            exe = _pick_exe_path()
            if not exe:
                return
            try:
                add_game_to_config(self.config_path, exe)
            except Exception:
                return

        def on_quit(icon: Icon, __):
            self._stop_event.set()
            try:
                icon.stop()
            except Exception:
                pass

        menu = Menu(
            MenuItem(
                lambda item: "Resume RPC" if self.state.paused else "Pause RPC",
                on_toggle_pause,
                default=True,
            ),
            MenuItem("Add Game", on_add_game),
            MenuItem("Quit", on_quit),
        )

        self._icon = Icon("renpy-discord-rpc", self._img_running, "Ren'Py Discord RPC", menu)
        self._set_icon_image()
        self._icon.run()

        self._stop_event.set()
        if self._worker is not None:
            try:
                self._worker.join(timeout=10)
            except Exception:
                pass


def _pick_exe_path() -> str:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select game executable",
            filetypes=[("Windows Executable", "*.exe"), ("All files", "*")],
        )
        try:
            root.destroy()
        except Exception:
            pass
        return str(path or "")
    except Exception:
        return ""


def main() -> int:
    app = TrayApp(Path("config.json"))
    app.start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
