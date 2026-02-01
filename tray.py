from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
import tempfile

import requests

from config import add_game_to_config, load_config, set_game_icon_url
from detection import find_running_game
from icons import extract_icon, upload_to_litterbox
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

        self._icon_urls_validated = False
        self._broken_icon_keys: set[str] = set()
        self._icon_retry_after_monotonic: dict[str, float] = {}
        self._icon_check_after_monotonic: dict[str, float] = {}

    def _icon_url_works(self, url: str) -> bool:
        url = (url or "").strip()
        if not url.startswith("http"):
            return False
        try:
            response = requests.get(url, stream=True, timeout=10)
            try:
                return bool(response.ok)
            finally:
                try:
                    response.close()
                except Exception:
                    pass
        except Exception:
            return False

    def _is_litterbox_url(self, url: str) -> bool:
        url = (url or "").strip().lower()
        return url.startswith("https://litter.catbox.moe/") or url.startswith("https://litterbox.catbox.moe/")

    def _game_key(self, *, exe_path: str = "", exe_name: str = "") -> str:
        exe_path = (exe_path or "").strip()
        exe_name = (exe_name or "").strip()
        if exe_path:
            return exe_path.lower()
        if exe_name:
            return exe_name.lower()
        return ""

    def _validate_icon_urls_now(self) -> None:
        cfg = self._cfg

        broken: set[str] = set()
        for g in cfg.games:
            if self._stop_event.is_set():
                return

            key = self._game_key(exe_path=g.exe_path, exe_name=g.exe_name)
            if not key:
                continue

            url = (g.icon_url or "").strip()
            if not url:
                broken.add(key)
                continue

            if url.startswith("http"):
                if not self._icon_url_works(url):
                    broken.add(key)

        self._broken_icon_keys = broken
        self._icon_urls_validated = True

    def _ensure_icon_url_for_running_game(self, exe_path: str, exe_name: str) -> str | None:
        key = self._game_key(exe_path=exe_path, exe_name=exe_name)
        if not key:
            return None

        cfg = self._cfg
        g = None
        for candidate in cfg.games:
            if exe_path and candidate.exe_path and str(Path(candidate.exe_path)).lower() == str(Path(exe_path)).lower():
                g = candidate
                break
            if exe_name and candidate.exe_name and candidate.exe_name.lower() == exe_name.lower():
                g = candidate
                break

        if g is None:
            return None

        existing_url = (g.icon_url or "").strip() or None

        if existing_url is not None and not existing_url.startswith("http"):
            self._broken_icon_keys.discard(key)
            return existing_url

        now = time.monotonic()
        check_after = float(self._icon_check_after_monotonic.get(key, 0.0))
        if now >= check_after and existing_url is not None:
            self._icon_check_after_monotonic[key] = now + 60.0
            if not self._icon_url_works(existing_url):
                self._broken_icon_keys.add(key)
            else:
                self._broken_icon_keys.discard(key)

        if key not in self._broken_icon_keys:
            return existing_url

        if not g.exe_path:
            return existing_url

        retry_after = float(self._icon_retry_after_monotonic.get(key, 0.0))
        if now < retry_after:
            return existing_url

        try:
            stem = Path(g.exe_path).stem or "icon"
            png_path = Path(tempfile.gettempdir()) / f"renpy-discord-rpc-{stem}.png"
            extract_icon(g.exe_path, png_path, size=256)
            new_url = upload_to_litterbox(png_path, time_to_live="72h", timeout_seconds=30.0)
            set_game_icon_url(self.config_path, exe_path=g.exe_path, exe_name=g.exe_name, icon_url=new_url)
            self._last_mtime = None
            self._reload_config_if_changed()
            self._broken_icon_keys.discard(key)
            return new_url
        except Exception:
            self._icon_retry_after_monotonic[key] = now + 60.0
            return existing_url

    def _reload_config_if_changed(self) -> None:
        try:
            mtime = self.config_path.stat().st_mtime
        except Exception:
            return

        if self._last_mtime is None or mtime != self._last_mtime:
            with self._cfg_lock:
                self._cfg = load_config(self.config_path)
                self._last_mtime = mtime
                self._icon_urls_validated = False
                self._broken_icon_keys = set()
                self._icon_retry_after_monotonic = {}
                self._icon_check_after_monotonic = {}

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

        repaired_icon_url: str | None = None
        if matched is not None:
            repaired_icon_url = self._ensure_icon_url_for_running_game(matched.exe_path, matched.exe_name)

        large_image = (
            (repaired_icon_url if repaired_icon_url else (matched.icon_url if matched and matched.icon_url else None))
            or cfg.fallback_large_image
        )
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

        self._reload_config_if_changed()
        if not self._icon_urls_validated:
            self._validate_icon_urls_now()

        while not self._stop_event.is_set():
            self._reload_config_if_changed()
            cfg = self._cfg

            if not self._icon_urls_validated:
                self._validate_icon_urls_now()

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
        self._icon.run_detached()

        try:
            while not self._stop_event.is_set():
                time.sleep(0.25)
        except KeyboardInterrupt:
            self._stop_event.set()
        finally:
            try:
                self._icon.stop()
            except Exception:
                pass

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
