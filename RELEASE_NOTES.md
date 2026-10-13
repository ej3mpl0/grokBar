# GrokBar v0.3.0

Windows system-tray monitor for **Grok Build** usage.

## Download

- **`GrokBar.exe`** — portable, double-click to run (~18 MB)

## Requirements

1. Windows 10 or 11  
2. Signed in with Grok Build CLI once:

   ```powershell
   grok login
   ```

## What’s new

- Compact popup: weekly used, weekly left, and the reset — no ring, no empty cards
- Product rows come from the API. Bot (and any new product) shows up; Chat / Imagine / API are not invented when the account doesn’t use them
- Tray icon and alerts follow the weekly pool, not only Grok Build
- Plan name in the header. On-demand and monthly dollars appear only when they are non-zero
- **Start with Windows** via Startup-folder shortcut (no registry Run key)
- Settings panel + link to [@ej3mplo](https://x.com/ej3mplo)

## Notes / SmartScreen

This build is **unsigned** open-source software (PyInstaller). Windows may show:

> Windows protected your PC

→ **More info** → **Run anyway**

That’s expected for community-built unsigned executables. Prefer building from source if your org blocks them.

## Privacy

- Reads local `~/.grok/auth.json` only  
- No telemetry  
- Calls xAI billing endpoints to show your own quota  

## Source

https://github.com/JairoMS27/grokBar

MIT License · created by [@ej3mplo](https://x.com/ej3mplo)
