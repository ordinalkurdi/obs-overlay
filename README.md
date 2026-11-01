# OBS Overlay Panel (plugin)

A slide-out, always-on-top control panel that runs **inside** OBS Studio as a normal plugin.
No WebSocket, no second app: it calls OBS directly through `obs-frontend-api`.
Works with an already-installed OBS Studio 28+ on Windows (Qt6).

## Status: step 2 of the port

| Feature | State |
| --- | --- |
| Edge-docked frameless panel, slide animation, pin, opacity, width | done |
| Show/hide hotkey (default Alt+Z, rebindable in OBS Settings > Hotkeys) | done |
| Hover-edge reveal (off by default, toggle in the panel menu) | done |
| Modular docks (drag, stack, tab, hide; layout is saved) | done |
| Capture: record, pause, instant replay, save replay, stream, virtual cam, screenshot | done |
| Scenes: click to switch | done |
| Gallery: recordings / replays / screenshots / favorites, search, thumbnails, open, show in folder, copy path, rename, delete to Recycle Bin | done (no built-in player yet) |
| All OBS settings | opens OBS's own Settings dialog from the panel menu |
| Widgets, mini preview, volume mixer, source visibility/lock, built-in video player | next |

## Build (easiest: let GitHub build it for you)

1. Create a new repo from the template https://github.com/obsproject/obs-plugintemplate
   ("Use this template"), then clone it.
2. In the clone:
   - Delete `src/plugin-main.c` (and any other file in `src/`).
   - Copy this project's `src/` folder and `CMakeLists.txt` over the template's
     (if the template's CMakeLists has changed, just keep its structure and replace the
     `target_sources(...)` list with the five `.cpp` files here).
   - In `buildspec.json`, set `"name": "obs-overlay-panel"` (and the author/website fields).
3. Push to GitHub. The template's Actions workflow builds Windows x64 and uploads a zip.
   Or build locally: `cmake --preset windows-x64` then `cmake --build --preset windows-x64`
   (needs Visual Studio 2022 with the C++ workload).

## Install on your existing OBS (no OBS rebuild)

Close OBS, then copy the built DLL to either location:

- No admin needed:
  `C:\ProgramData\obs-studio\plugins\obs-overlay-panel\bin\64bit\obs-overlay-panel.dll`
- Or: `C:\Program Files\obs-studio\obs-plugins\64bit\obs-overlay-panel.dll`

Start OBS. Use **Tools > Overlay Panel** or press **Alt+Z**.

## Notes and known limits

- Settings: from a plugin, "all settings" means opening OBS's real Settings dialog
  (panel menu > Open OBS Settings). Embedding those pages inside the panel requires
  patching OBS itself (the fork route).
- Gallery: double-click opens the file in your default player. A built-in player needs Qt Multimedia,
  which OBS does not ship, so it would have to come from libobs instead (planned).
- Gallery thumbnails for videos use the Windows shell; formats Windows can't thumbnail (often .mkv without a codec pack)
  keep the grey placeholder. Screenshots always get real thumbnails.
- Exclusive-fullscreen games hide any overlay; use borderless/windowed fullscreen.
- Recording/stream timers count from when the plugin saw the output start.
- The plugin must be built against an OBS/Qt6 version compatible with your installed OBS.
  Using the template's pinned dependencies normally does that.
