# Security

## What GrokBar stores

- **Does not** store API keys, passwords, or billing credentials of its own.
- **Reads** the local Grok CLI session at `~/.grok/auth.json` (created by `grok login`).
- Settings live in `%LOCALAPPDATA%\GrokBar\settings.json` (preferences only).
- Optional startup uses a **user Startup-folder shortcut** (not admin rights).

## Network

GrokBar only calls xAI / Grok endpoints needed for usage display, for example:

- `https://cli-chat-proxy.grok.com/v1/billing?format=credits`
- `https://cli-chat-proxy.grok.com/v1/billing`

using your existing CLI session token. Tokens never leave your machine except in those authenticated requests to xAI.

## Reporting issues

Open a GitHub issue or contact [@ej3mplo](https://x.com/ej3mplo).

Please **do not** paste access tokens, `auth.json`, or full session cookies in issues.
