# contract-to-cash-agent
Contract-to-cash-agent


## Local operations console (Phase 3)

A React/TypeScript workspace and protected FastAPI adapter build on the existing
read-only investigation backend. See [Windows Git Bash setup, local operation,
recorded-mode import and security boundaries](docs/PHASE3.md). No genuine recording
is bundled, no paid run starts automatically, and no public deployment is configured.

Windows users can double-click **Start Ledgerline.cmd** after one-time setup. See
[the launcher, secure credentials and desktop shortcut guide](docs/WINDOWS_LAUNCHER.md).

Normal local startup now opens directly into the dashboard without a password.
Loopback-only sessions, CSRF, explicit paid-run confirmation and human authorization
remain required; public/network deployment requires proper authentication first.

The [Phase 3.1 human + AI workflow guide](docs/PHASE31.md) covers the four-scene
workspace, administrator pricing setup, Windows updates and labeled test screenshots.

[Phase 3.2 human resolution and scoped agent continuation](docs/PHASE32.md) adds
evidence-supported decisions, explicit paid continuation and a persisted before/after
summary, with Windows instructions and labeled test screenshots.
