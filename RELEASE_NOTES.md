# GrokBar v0.2.2

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

- Dark xAI-style rounded dashboard (vertical product bars)
- Tray ring with usage %
- **Start with Windows** via Startup-folder shortcut (no registry Run key — fewer AV false positives)
- Settings panel + link to [@ej3mplo](https://x.com/ej3mplo)
- Custom app icon

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
