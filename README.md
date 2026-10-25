# 🎮 OBS Overlay — OBS Control Without Leaving Your Game

**Your OBS control panel. On your screen. Out of your way.** 🗿

A slide-out, always-on-top control panel for **OBS Studio**, inspired by slick GPU vendor in-game overlays. Dock it to your monitor's edge, pop it open with a hotkey, and control OBS without alt-tabbing like it's 2009. 💀

> 🚧 **Status: Early Alpha**
>
> Windows is the main target. Expect rough edges, weird bugs, and occasional skill issues. Bug reports and contributions are welcome!

---

## ✨ Features

### 🎥 Capture — Get That Content

- 🔴 **Recording controls** — Start, stop, pause, and resume recordings, with a live timer and file size.
- 🔁 **Instant Replay** — Capture unexpected W moments with the OBS Replay Buffer.
- 💾 **Save Replay** — Save recent gameplay without recording everything permanently.
- 📸 **Screenshot** — Capture the current OBS scene output.
- 📡 **Streaming controls** — Check stream duration, bitrate, and dropped frames. Your stream key stays private.
- 📷 **Virtual Camera** — Toggle the OBS virtual camera.

### 🎬 Production — Director Mode

- 🎞️ **Scene switching** — Switch scenes without leaving your game.
- 👁️ **Source visibility** — Show or hide individual sources.
- 🔐 **Source locking** — Lock sources to prevent accidental changes.
- 🎙️ **Audio controls** — Mute your microphone and desktop audio.
- 🎚️ **Volume mixer** — Adjust volume across audio sources.
- 🖼️ **Scene preview** — A snapshot refreshed about once per second.

### 🗂️ Gallery — The Clip Vault

- 🔎 Search and filter recordings, clips, screenshots, and favorites.
- 🖼️ Lazy-loaded thumbnails.
- ⭐ Mark your best captures as favorites.
- 📂 Open files or show them in File Explorer.
- 📋 Copy file paths, rename files, or delete them to the Recycle Bin.
- 🎬 Built-in video player with playback speed, looping, frame stepping, and fullscreen.

### 🧲 Overlay — Always Within Reach

- ↔️ Dock to the left or right edge of any monitor.
- 🪄 Smooth slide-in and slide-out animations.
- ⌨️ Global hotkeys for controlling OBS while gaming.
- 🖱️ Reveal the panel by hovering over the screen edge.
- 📌 Pin the overlay in place.
- 📐 Resize and reposition the panel.
- 🫥 Tray-only mode with no taskbar entry.
- 🎨 Customize opacity, dimensions, font size, corner radius, and spacing.

### 📊 Floating Widgets — Your HUD, Your Rules

Add as many widgets as you want:

- 📈 System and OBS statistics
- ⏱️ Recording timer
- 📡 Stream status
- 🎬 Current scene
- 🎙️ Microphone mute status
- 🔊 Desktop audio mute status

Move, resize, pin, fade, or make widgets click-through.

### 🌐 Web Docks — Chat Without the Alt-Tab Arc

- 💬 Twitch chat
- 🎛️ Twitch Stream Manager
- 🔗 Custom HTTP and HTTPS websites
- ↩️ Back, reload, zoom, and open in browser
- 🔐 Locally persisted web logins
- 🫥 Click-through and pin options

Web login data is stored locally in `%APPDATA%\ObsOverlay\web`.

### ⚙️ Quality-of-Life Features

- 🧪 Demo mode — Works without OBS.
- 🔍 Searchable settings.
- ⌨️ Rebindable hotkeys with conflict detection.
- 🔑 OBS password stored in Windows Credential Manager.
- 🚫 No telemetry.
- 🏠 Local-first media and settings.

---

## 🛠️ Installation

### Requirements

- 🪟 Windows 10 or Windows 11
- 🐍 Python 3.10+
- 🎥 OBS Studio 28+
- 🔌 OBS WebSocket v5

### 1. Clone the Repository

```bash
git clone <your-repository-url>
cd <your-repository-folder>
```

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure OBS

In OBS Studio, open:

**Tools → WebSocket Server Settings**

1. Enable the WebSocket server.
2. Check the port (usually `4455`).
3. Configure your password.
4. Apply the settings.

### 4. Launch the Overlay

Connect to OBS:

```bash
python main.py
```

Or try Demo Mode:

```bash
python main.py --demo
```

### 5. Connect

Open **Settings → OBS connection**, enter your host, port, and password, then click **Test connection**.

### 6. Enable Instant Replay

In OBS, open **Settings → Output → Replay Buffer** and enable the buffer.

---

## ⌨️ Default Hotkeys

| Action | Shortcut |
|---|---|
| Show / hide overlay | `Alt + Z` |
| Start / stop recording | `Alt + F9` |
| Toggle Instant Replay | `Alt + Shift + F10` |
| Save replay | `Alt + F10` |
| Screenshot | `Alt + F1` |
| Mute microphone | `Ctrl + Alt + M` |
| Mute desktop audio | `Ctrl + Alt + D` |
| Show / hide widgets | `Alt + R` |
| Toggle widget click-through | `Alt + Shift + W` |

All shortcuts are rebindable. Some anti-cheat systems and elevated applications may interfere with global hotkeys.

---

## 📦 Build for Windows

Run:

```bat
build.bat
```

The executable is created at:

```text
dist\ObsOverlay\ObsOverlay.exe
```

Keep the entire output folder together.

To build the installer, install [Inno Setup 6](https://jrsoftware.org/isdl.php), run `build.bat`, then:

```bat
iscc installer.iss
```

The installer is created in `installer_output\`.

To launch on Windows startup, press `Win + R`, enter `shell:startup`, and add a shortcut to `ObsOverlay.exe`.

> 💡 Web docks use QtWebEngine, adding roughly 150 MB to the build.

---

## ⚠️ Known Limitations

- Exclusive-fullscreen games are not supported; use borderless or windowed fullscreen.
- Screenshots capture the OBS scene output, not the desktop directly.
- Scene previews refresh approximately once per second.
- Audio level meters are not implemented.
- Recording format and encoder settings remain in OBS.
- Replay duration is configured through the OBS Simple-output profile.
- Windows is the primary supported platform.

### 🚧 Not Implemented Yet

- 📸 Photo Mode
- ✨ Automatic highlights
- 🎨 Filter editor
- 🎬 Creating or renaming scenes
- 📊 GPU statistics
- ☀️ Light theme

---

## 🗂️ Project Structure

```text
ObsOverlay/
├── main.py
├── core/
│   ├── backends.py
│   ├── service.py
│   ├── gallery.py
│   ├── hotkeys.py
│   └── config.py
├── ui/
├── requirements.txt
├── build.bat
├── installer.iss
└── README.md
```

- `main.py` — Entry point, tray icon, and hotkey wiring.
- `core/backends.py` — OBS WebSocket and demo backends.
- `core/service.py` — State, worker thread, events, and reconnect logic.
- `core/gallery.py` — Media scanning, thumbnails, and file operations.
- `core/hotkeys.py` — Global hotkeys and conflict detection.
- `core/config.py` — Settings and credential storage.
- `ui/` — Overlay, gallery, player, settings, and widgets.

---

## 🔒 Privacy & Security

- 🔑 OBS passwords are stored in Windows Credential Manager.
- 🚫 Passwords are not saved in the regular settings file or exported.
- 🏠 Media and settings remain local.
- 🚫 No telemetry.
- 🌐 Web docks connect to the websites you choose.

---

## 🐛 Bugs & Contributions

Found a bug or have an idea? Open a GitHub Issue or submit a pull request.

When reporting bugs, include your Windows, Python, and OBS versions, reproduction steps, and relevant error messages.

**Never share your OBS password or stream key in issue reports.** 🔒

---

## 📜 License

Licensed under the **MIT License**. See [`LICENSE`](LICENSE) for details.

---

## 💜 Play the Game. Control OBS. Catch the W. 🎮🔥

⭐ If you find this project useful, consider giving it a star on GitHub.
