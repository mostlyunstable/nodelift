# 0005 — Tauri shell with a bundled Python runtime, not a frozen executable

**Status:** accepted and built (macOS, ad-hoc signed)

**Decision.** `Nodecraft.app` is a small Tauri shell that starts the Python backend on a random loopback port with a
random per-launch token, waits for `/health`, restarts the backend if it crashes, and stops it on quit. The backend
ships as a relocatable CPython (python-build-standalone) plus its dependencies under `Contents/Resources/runtime`.

**Why not PyInstaller.** User code must be able to `import` the whole standard library (and, later, installed
packages). A frozen executable contains only what the backend itself imported, and would need a self-re-exec hack for
workers. A full runtime keeps `python -I worker_entry.py` unchanged.

**Why Tauri over Electron.** The shell only manages processes and windows; the web UI worked in WebKit. ~10 MB shell vs
~120 MB.

**Not done.** Developer ID signing, notarization and auto-update need a paid Apple Developer account. Windows and Linux
need Job Objects / platform paths for the worker limits.
