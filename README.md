# Ren'Py Discord RPC

A lightweight Windows tray app that shows Discord Rich Presence for whitelisted Ren'Py visual novels.

## Setup

- Install Python 3.10+
- Create and activate a venv
- Install dependencies:

```powershell
pip install -r requirements.txt
```

## Configuration

- Copy `config.example.json` to `config.json`
- Set:
  - `client_id` (your Discord Application ID)
  - `games` (use the tray menu to add games)

`config.json` is user-local and should remain uncommitted.

## Run

```powershell
py .\main.py
```

This starts the tray app.

### Debug CLI (optional)

```powershell
py .\main.py --cli
```

## Icons

- Game icons are extracted from the game executable and uploaded to Litterbox.
- On startup, the app checks that configured `icon_url` links still work.
- If a game is running and its `icon_url` is missing/broken, the app will re-upload the icon and update `config.json`.
- If icon extraction or upload fails, the app will fall back to `fallback_large_image`.

## Build (PyInstaller)

Install PyInstaller:

```powershell
pip install pyinstaller
```

Build a no-console, onefile EXE using the included spec:

```powershell
pyinstaller .\renpy-discord-rpc.spec
```

The output will be in `dist\renpy-discord-rpc.exe`.

## Disclaimer

- This project is not affiliated with Discord, Ren'Py, Catbox, or Litterbox.
- You are responsible for complying with Discord ToS and any relevant content policies.
- Do not upload content you do not have the right to distribute. If your game content is NSFW, ensure you comply with the hosting provider and Discord policies.
