from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import psutil

try:
    import win32gui
    import win32process
except Exception:
    win32gui = None
    win32process = None


@dataclass(frozen=True)
class RunningGame:
    pid: int
    exe_path: str
    exe_name: str
    window_title: str


def iter_running_processes() -> Iterable[tuple[int, str, str]]:
    for proc in psutil.process_iter(["pid", "name", "exe"]):
        try:
            pid = int(proc.info.get("pid") or 0)
            name = (proc.info.get("name") or "").lower()
            exe = proc.info.get("exe") or ""
            if not pid:
                continue
            yield pid, exe, name
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue


def _get_window_title_for_pid(pid: int) -> str:
    if win32gui is None or win32process is None:
        return ""

    titles: list[str] = []

    def callback(hwnd: int, _: int) -> bool:
        if not win32gui.IsWindowVisible(hwnd):
            return True
        try:
            _, window_pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        if int(window_pid) != int(pid):
            return True
        try:
            title = win32gui.GetWindowText(hwnd) or ""
        except Exception:
            title = ""
        title = title.strip()
        if title:
            titles.append(title)
        return True

    try:
        win32gui.EnumWindows(callback, 0)
    except Exception:
        return ""

    if not titles:
        return ""
    titles.sort(key=len, reverse=True)
    return titles[0]


def find_running_game(exe_names: set[str], exe_paths: set[str]) -> RunningGame | None:
    exe_paths_lower = {p.lower() for p in exe_paths if p}

    for pid, exe_path, exe_name in iter_running_processes():
        if exe_name and exe_name in exe_names:
            title = _get_window_title_for_pid(pid)
            return RunningGame(pid=pid, exe_path=exe_path or "", exe_name=exe_name, window_title=title)

        if exe_path and exe_path.lower() in exe_paths_lower:
            title = _get_window_title_for_pid(pid)
            return RunningGame(pid=pid, exe_path=exe_path or "", exe_name=exe_name, window_title=title)

    return None
