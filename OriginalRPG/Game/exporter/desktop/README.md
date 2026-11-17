# Viper desktop launcher

Turns a web export into a desktop app: one `.exe` on Windows, one executable on Linux.

```
python3 exporter/viper_package.py --html Exports/MyGame-web/index.html --icon icon.png \
    --target windows --output Exports/MyGame-windows-app [--name "My Game"] [--fullscreen] [--fixed-size]
```

In the editor: File → Export Game → "Windows app (from web export)" or "Linux app (from web export)".

## How it works

- `viper_package.py` copies a prebuilt launcher from `bin/`, gives the Windows one an icon,
  version info and manifest (a new `.rsrc` section), then appends every file beside the HTML
  page plus a small config. Icons: `.png` (resized to 16–256 px) or `.ico`.
- `launcher.cpp` reads that payload from its own file, serves it on `127.0.0.1` and shows it in the
  game's own window (no browser UI), the same model as pywebview-based HTML-to-EXE tools:
  - Windows: a Win32 window hosting WebView2, the Edge engine built into Windows 10 and 11. The
    launcher finds the runtime itself (EdgeUpdate registry entry, then the EdgeWebView folders) and
    declares only the COM interfaces it calls, so no WebView2Loader.dll or SDK is needed.
    `WEBVIEW2_BROWSER_EXECUTABLE_FOLDER` selects a fixed-version runtime. Only if WebView2 is
    missing does it fall back to an Edge/Chrome app window.
  - Linux: a WebKitGTK window (loaded at run time), else Chromium/Chrome/Edge/Brave in app mode,
    else Firefox. Linux executables carry no icon, so on each start the launcher writes a desktop
    entry (menu, dock, task switcher) and sets the file-manager icon on itself via GIO metadata;
    the packager sets that file-manager icon at export too.
  - The page's Fullscreen API toggles a borderless full-screen window. `--fullscreen` starts in
    full screen and `--fixed-size` stops players resizing the window.
  - The launcher exits when the game window closes.
- Each game gets a fixed local port and its own browser profile, so `localStorage` saves persist.

## Rebuilding the launchers

After editing `launcher.cpp`, run `./build_launchers.sh` (needs `g++` and `x86_64-w64-mingw32-g++`),
then copy this folder into each game's `exporter/`.

Debug switches (environment variables): `VIPER_SERVE_ONLY=1` serves without a window and prints the
URL, `VIPER_LOG=1` logs requests, `VIPER_BROWSER=1` skips WebKitGTK on Linux, `VIPER_DEVTOOLS=1`
enables the WebKit / WebView2 developer tools.
