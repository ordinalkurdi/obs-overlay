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
- Floating stat widgets: add as many as you like (statistics with selectable metrics, recording timer, stream status, current scene, mic/desktop mute). Each one can be moved, resized (text scales), made transparent, pinned and made click-through; manage them from the overlay or by right-click

**Web docks**
- Floating, resizable docks that show any web page: Twitch chat (just enter a channel), the Twitch Stream Manager, or a custom address
- Same options as the stat widgets (move, resize, opacity, pin, click-through), plus back / reload / zoom / open in browser
- Logins are kept between runs in `%APPDATA%\ObsOverlay\web` (local only); "Clear web login data" removes them
- Only http(s) pages are allowed; web docks load the sites you choose, so they do use the network (the rest of the app does not)

**Other**
- Demo mode that works without OBS
- Searchable settings, rebindable hotkeys with conflict detection
- OBS password stored in the Windows credential store, never in the settings file and never exported
- No telemetry; media and settings stay local

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
| Show / hide floating widgets | Alt+R |
| Toggle click-through for all widgets | Alt+Shift+W |

Hotkeys are global and passive, so they are not blocked from the game. Some games with anti-cheat, or programs running as administrator, may prevent global hotkeys from being detected.

## Build a Windows executable

Web docks use QtWebEngine (Chromium), so the built app and installer are roughly 150 MB larger than without it.

```
build.bat
```

The program is created at `dist\ObsOverlay\ObsOverlay.exe`; keep the whole folder together. To start with Windows, put a shortcut to the exe in the folder opened by `shell:startup` (Win+R).

To build the installer locally, install [Inno Setup 6](https://jrsoftware.org/isdl.php), run `build.bat`, then `iscc installer.iss`. The result is `installer_output\ObsOverlay-Setup-<version>.exe`.

Pushing a tag such as `v0.1.0` makes GitHub Actions build the exe and attach both `ObsOverlay-Setup-0.1.0.exe` (installer) and `ObsOverlay-windows.zip` (portable) to a release.

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
