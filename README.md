# OBS Overlay

A slide-out, always-on-top control panel for **OBS Studio**, inspired by the in-game overlay of GPU vendor apps.
Dock it to the edge of a monitor, pop it open with a hotkey while you play, and control OBS without leaving the game.

Built with Python, PySide6 and the OBS WebSocket protocol (v5, built into OBS 28+).

> **Status: early alpha.** Developed mainly for Windows. Expect rough edges; bug reports are welcome.

## Features

**Capture**
- Record / stop, pause / resume, with live timer and file size
- Instant Replay using the OBS Replay Buffer, plus Save replay
- Screenshot of the OBS scene output
- Start / stop streaming with live duration, bitrate and dropped frames (stream key is never shown)
- Virtual camera toggle

**Production**
- Scene switching that stays in sync with OBS
- Sources list for the current scene: show / hide and lock / unlock each source
- Microphone and desktop audio mute, plus a volume mixer for all audio sources
- Scene snapshot preview (updates about once per second, not live video)

**Gallery and player**
- Recent-captures strip and a full gallery that scans your capture folder recursively (per-game and replay subfolders)
- Search, filter (recordings / clips / screenshots / favorites), sort, lazy thumbnails
- Right-click any capture: open, show in folder, copy path, favorite, rename, delete (to recycle bin)
- Built-in video player in its own window (speed, loop, frame step, fullscreen)

**Overlay behavior**
- Docks to the left or right edge of any monitor and slides in and out with an animation
- Open with a global hotkey, the tray icon, or by hovering the screen edge
- Resize by dragging edges and corners, move up and down by dragging the header
- Pin: keeps the panel open and locks its size and position
- Tray-only: no taskbar entry
- Home, Gallery and Settings are pages inside one window
- Adjustable opacity, width, height, gap to the edge, font size, corner radius and row spacing
- Optional statistics panel (recording, streaming, bitrate, dropped frames, resolution, FPS, system CPU / RAM, replay buffer)

**Other**
- Demo mode that works without OBS
- Searchable settings, rebindable hotkeys with conflict detection
- OBS password stored in the Windows credential store, never in the settings file and never exported
- No telemetry; everything stays local

## Install

Requirements: Windows 10/11 (other platforms are untested), Python 3.10+, OBS Studio 28 or newer.

```
pip install -r requirements.txt
python main.py            # connect to OBS
python main.py --demo     # simulation, no OBS needed
```

In OBS, enable the server under **Tools > WebSocket Server Settings** (default port 4455). Enter the host, port and password in the overlay under **Settings > OBS connection**, then use **Test connection**.

For the Replay Buffer features, enable it in OBS under **Settings > Output > Replay Buffer**.

## Hotkeys (defaults, all rebindable)

| Action | Shortcut |
| --- | --- |
| Show / hide overlay | Alt+Z |
| Start / stop recording | Alt+F9 |
| Toggle Instant Replay | Alt+Shift+F10 |
| Save replay | Alt+F10 |
| Screenshot | Alt+F1 |
| Mute microphone | Ctrl+Alt+M |
| Mute desktop audio | Ctrl+Alt+D |
| Toggle statistics | Alt+R |

Hotkeys are global and passive, so they are not blocked from the game. Some games with anti-cheat, or programs running as administrator, may prevent global hotkeys from being detected.

## Build a Windows executable

```
build.bat
```

The program is created at `dist\ObsOverlay\ObsOverlay.exe`; keep the whole folder together. To start with Windows, put a shortcut to the exe in the folder opened by `shell:startup` (Win+R).

Pushing a tag such as `v0.1.0` makes GitHub Actions build the exe and attach `ObsOverlay-windows.zip` to a release.

## Limitations

- The overlay is a normal always-on-top window. It does **not** draw inside exclusive-fullscreen games; use borderless or windowed-fullscreen mode.
- Screenshots capture the OBS scene output, not the desktop or the game directly.
- The preview is a snapshot refreshed about once per second, not live video.
- Audio level meters are not shown. Volume and mute controls are real.
- Recording format, encoder and replay save folder are configured in OBS, not in this app.
- Replay length is written to the OBS Simple-output profile and applies when the buffer starts.
- Not implemented: Photo Mode, automatic highlights, filter editor, creating or renaming scenes, GPU statistics, light theme.

## Project layout

```
main.py             entry point, tray icon, hotkey wiring
core/backends.py    OBS WebSocket backend and demo backend (same interface)
core/service.py     state, worker thread, events, reconnect, notifications
core/gallery.py     recursive media scan, thumbnails, safe file operations
core/hotkeys.py     global hotkeys and conflict detection
core/config.py      settings and credential storage
ui/                 overlay, gallery and player, settings, statistics panel
```

## License

MIT, see [LICENSE](LICENSE).
