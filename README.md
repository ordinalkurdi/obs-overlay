# 🎮 OBS Overlay

### ⚡ Your OBS controls. Right at your fingertips.

A slide-out, always-on-top control panel for **OBS Studio**, inspired by the in-game overlays from GPU software. Dock it to the edge of your monitor, pop it open with a hotkey while gaming, and control OBS without ever leaving your game. 🚀

> 🧪 **Status: Early Alpha**
>
> 🪟 Developed primarily for Windows. Expect some rough edges — bug reports and contributions are welcome!

---

## ✨ Features

### 🎥 Capture & Recording

- 🔴 **Record / Stop** — Start or stop recordings with a live timer and file size.
- ⏸️ **Pause / Resume** — Control your recording instantly.
- 🔁 **Instant Replay** — Use the OBS Replay Buffer to capture unexpected moments.
- 💾 **Save Replay** — Save your latest gameplay highlights.
- 📸 **Screenshot** — Capture the current OBS scene output.
- 📡 **Streaming Controls** — Start or stop streams and monitor duration, bitrate, and dropped frames.
- 🎦 **Virtual Camera** — Toggle your OBS virtual camera on or off.

### 🎛️ Production Controls

- 🎬 **Scene Switching** — Change scenes while staying synchronized with OBS.
- 👁️ **Source Visibility** — Show or hide sources in your current scene.
- 🔒 **Source Locking** — Lock or unlock individual sources.
- 🎙️ **Audio Controls** — Mute your microphone or desktop audio.
- 🔊 **Volume Mixer** — Adjust volume across your audio sources.
- 🖼️ **Scene Preview** — View a snapshot of your scene, refreshed about once per second.

### 🗂️ Gallery & Video Player

- 🕹️ **Recent Captures** — Quickly access your latest recordings and screenshots.
- 🖼️ **Full Gallery** — Scan your capture folder recursively, including game-specific and replay subfolders.
- 🔎 **Search & Filter** — Find recordings, clips, screenshots, or favorites.
- ↕️ **Sort & Browse** — Sort files and load thumbnails as needed.
- 🖱️ **Right-Click Actions** — Open files, show them in File Explorer, copy paths, favorite, rename, or delete files to the Recycle Bin.
- ▶️ **Built-in Video Player** — Play videos in a separate window with speed controls, looping, frame stepping, and fullscreen mode.

### 🪟 Overlay Customization

- ↔️ **Edge Docking** — Dock to the left or right edge of any monitor.
- ⌨️ **Global Hotkeys** — Open or close the overlay while playing.
- 🖱️ **Edge Hover** — Reveal the panel by hovering near the screen edge.
- 📐 **Flexible Resizing** — Drag edges and corners to resize the panel.
- ↕️ **Move Freely** — Drag the header to reposition the overlay vertically.
- 📌 **Pin Mode** — Keep the panel open and lock its size and position.
- 🫥 **Adjustable Appearance** — Customize opacity, width, height, edge gap, font size, corner radius, and row spacing.
- 📊 **Statistics Panel** — Optionally display recording and streaming status, bitrate, dropped frames, resolution, FPS, system CPU/RAM usage, and Replay Buffer status.
- 🧭 **One Window, Multiple Pages** — Switch between Home, Gallery, and Settings.

### 🔐 Privacy & Other Features

- 🧪 **Demo Mode** — Explore the interface without connecting to OBS.
- ⚙️ **Searchable Settings** — Find options quickly.
- 🎹 **Rebindable Hotkeys** — Customize shortcuts and detect conflicts.
- 🔑 **Secure Password Storage** — OBS passwords are stored in the Windows Credential Manager, never in the settings file or exported.
- 🚫 **No Telemetry** — Everything stays local.

---

## 📦 Installation

### ✅ Requirements

- 🪟 Windows 10/11 (other platforms are untested)
- 🐍 Python 3.10+
- 🎥 OBS Studio 28 or newer

### 🚀 Get Started

1. Clone or download this repository.
2. Open a terminal in the project folder.
3. Install the dependencies:

   ```bash
   pip install -r requirements.txt
   ```

4. Start the overlay and connect to OBS:

   ```bash
   python main.py
   ```

   Or launch Demo Mode without OBS:

   ```bash
   python main.py --demo
   ```

### 🔌 Connect to OBS

1. Open OBS Studio.
2. Navigate to **Tools → WebSocket Server Settings**.
3. Enable the WebSocket server. The default port is `4455`.
4. Open the overlay's **Settings → OBS Connection**.
5. Enter your host, port, and password.
6. Click **Test Connection**. ✅

### 🔁 Enable Instant Replay

To use the Replay Buffer features, enable it in OBS under:

**Settings → Output → Replay Buffer**

---

## ⌨️ Default Hotkeys

All shortcuts can be customized in Settings.

| 🎮 Action | ⌨️ Shortcut |
|---|---|
| Show / Hide Overlay | `Alt + Z` |
| Start / Stop Recording | `Alt + F9` |
| Toggle Instant Replay | `Alt + Shift + F10` |
| Save Replay | `Alt + F10` |
| Take Screenshot | `Alt + F1` |
| Mute Microphone | `Ctrl + Alt + M` |
| Mute Desktop Audio | `Ctrl + Alt + D` |
| Toggle Statistics | `Alt + R` |

> 💡 **Gaming tip:** Hotkeys work globally and are designed not to interrupt your game. However, some anti-cheat systems and applications running as administrator may prevent them from being detected.

---

## 🏗️ Build a Windows Executable

Want to run the overlay without manually launching Python? 😎

Run:

```bat
build.bat
```

📁 The executable will be created at:

```text
dist\ObsOverlay\ObsOverlay.exe
```

> ⚠️ Keep the entire `ObsOverlay` folder together — the executable depends on the other files in that folder.

### 🚀 Launch on Windows Startup

1. Press `Win + R`.
2. Enter `shell:startup`.
3. Create or copy a shortcut to `ObsOverlay.exe` into the Startup folder.

### 📦 GitHub Releases

Pushing a version tag, such as `v0.1.0`, triggers GitHub Actions to build the Windows executable and attach `ObsOverlay-windows.zip` to the release.

---

## ⚠️ Known Limitations

- 🖥️ **Fullscreen Compatibility:** The overlay is a normal always-on-top window. It does not draw inside exclusive-fullscreen games. Use borderless or windowed-fullscreen mode.
- 📸 **Screenshots:** Capture the OBS scene output, not the desktop or game directly.
- 🖼️ **Preview:** Scene previews are snapshots refreshed about once per second, not live video.
- 🔊 **Audio Meters:** Audio level meters are not available yet, although volume and mute controls work.
- 🎚️ **Recording Settings:** Recording format, encoder, and Replay Buffer save folder are configured in OBS.
- 🔁 **Replay Duration:** Written to the OBS Simple-output profile and applied when the Replay Buffer starts.
- 🚧 **Not Implemented Yet:** Photo Mode, automatic highlights, filter editor, creating or renaming scenes, GPU statistics, and light theme.

---

## 📂 Project Structure

```text
main.py             # Entry point, tray icon, hotkey wiring
core/backends.py    # OBS WebSocket backend and demo backend
core/service.py     # State, worker thread, events, reconnect, notifications
core/gallery.py     # Media scanning, thumbnails, safe file operations
core/hotkeys.py     # Global hotkeys and conflict detection
core/config.py      # Settings and credential storage
ui/                 # Overlay, gallery, player, settings, statistics
```

---

## 🛠️ Built With

- 🐍 **Python** — Core application logic
- 🎨 **PySide6** — Desktop UI
- 🔌 **OBS WebSocket v5** — Communication with OBS Studio

---

## 📜 License

🆓 Licensed under the **MIT License**.

📄 See the [LICENSE file](https://github.com/ordinalkurdi/obs-overlay/blob/main/LICENSE).

---

### ❤️ Made for gamers, streamers, and creators.

🎮 **Play. Record. Replay. Repeat.** 🔥
