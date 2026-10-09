# AGENTS.md — AI Usage

Context for coding agents (Claude Code, Codex) and contributors working on this repo.
Reply in the language the user writes in.

## Working method

Any non-trivial change, code or docs, follows [docs/PROCESS.md](docs/PROCESS.md):

```
1. Investigation (status quo + simplest strategy) → 2. /grill-me → 3. Plan Mode
→ 4. Implementation (local commits) → 5. Independent audit until SAFE → 6. Push + PR
```

- The owner signs off at each gate; nothing is pushed before the audit is SAFE and the owner
  says go. Merge only on the owner's say. Small changes skip steps 1–3, never the audit.
- Audit protocol: [docs/PROCESS_AUDIT.md](docs/PROCESS_AUDIT.md), skill `independent-audit`;
  grill: skill `grill-me` (both in `.claude/skills/`, linked for Codex in `.agents/skills/`).
- Pre-flight, before every commit and in every audit: `tools/check.sh` → must end with
  `check: OK`. It runs the offline tests in `tests/` (`unittest`, Python 3.9): `cx`/`ccx` are
  loaded with a temp `HOME`, a fake `security`, faked APIs, and a guard that fails any test
  reaching a real process, network or socket; the status line runs for real with a temp `HOME`.
  New behavior in `bin/` or `claude/` comes with a test.
- Engineering preferences: explicit over clever; engineered enough (neither fragile nor
  over-abstracted); handle edge cases; flag repetition; keep existing behavior unless the change
  is about it — no rewrite as a side effect; docs updated in the same commit as the change.

## What this is

macOS tooling to watch Claude and Codex usage limits and to switch between several accounts of each.

| Part | Path | Installed as |
|---|---|---|
| Menu bar app (SwiftUI, single file) | `app/AIUsage.swift`, `app/build.sh` | `~/Applications/AI Usage.app` (built, ad-hoc signed) |
| Codex account switcher (Python 3.9, stdlib only) | `bin/cx` | symlink `~/.local/bin/cx` |
| Claude Code account switcher (Python 3.9, stdlib only) | `bin/ccx` | symlink `~/.local/bin/ccx` |
| Claude Code status line (POSIX sh + jq) | `claude/statusline.sh` | symlink `~/.claude/statusline-cache.sh` |
| Installer | `install.sh` | — |

Edits in the repo are live for `cx`, `ccx` and the status line (symlinks). The app must be rebuilt:
`app/build.sh && pkill -x AIUsage; open ~/Applications/AI\ Usage.app`.

## Menu bar app (`app/AIUsage.swift`)

- `MenuBarExtra` with `.menuBarExtraStyle(.window)`, `LSUIElement` app, macOS 14+, compiled with
  `swiftc -parse-as-library -swift-version 5` (Swift 5 mode on purpose: avoids Swift 6 strict
  concurrency noise). No Xcode project.
- Menu bar label is an `ImageRenderer` image: Claude logo + %, OpenAI logo + % (worst window of
  the active Claude and Codex accounts). One color per logo: neutral < 50, orange ≥ 50, red ≥ 80.
  All neutral → template image (follows the menu bar by itself). Any color → non-template image
  whose neutral color is picked from the menu bar's own appearance (status item window
  `effectiveAppearance`, observed via KVO).
- Logos are the monochrome tray templates shipped inside `/Applications/Claude.app`
  (`TrayIconTemplate@3x.png`) and `/Applications/ChatGPT.app` (`chatgptTemplate@2x.png`), copied
  into the bundle by `build.sh`; SF Symbol fallback if missing. Don't commit those images.
- Panel: header "Usage" with `+` menu (Claude account… / Codex account…, each opens Terminal on
  `ccx add` / `cx add`) and refresh; card "Claude" (bars per limit with one saved account, account
  rows like Codex with two or more); card "Codex" (one row per account, click to switch,
  checkmark on active, free resets line). Rows share `AccountRow` / `AccountList` (`Account`
  model with a `brand`). Footer: gear menu (Open at Login via `SMAppService.mainApp`, Appearance,
  Language) and Quit.
- Settings, saved in UserDefaults: `theme` (`Theme`: system/light/dark, applied with
  `NSApp.appearance` to the panel and its menus; the menu bar label keeps following the menu bar)
  and `language` (`Language`: English/French, defaults to the Mac's preferred language). Strings
  go through `tr(en, fr)`, limit names through `windowName`, English messages printed by cx/ccx
  through `localized` (regex table — add new CLI messages there). The panel is rebuilt with
  `.id(language)` when it changes. Dates use the language's locale (en_GB / fr_FR).
  CLI output stays English.
- Refresh: every 10 min (timer tolerance 60 s, energy), and when the panel window becomes key if data is older than 30 s.
- Design: Apple look, discreet, sober. Colors by percentage only:
  green < 50, orange ≥ 50, red ≥ 80. Reset line = "Resets in 3h 26m" left (secondary) + exact
  date right (tertiary, "today 19:30" / "Thu 8 Oct, 06:00", en_GB format).

## Data sources (all read-only)

| Data | Endpoint / file | Auth |
|---|---|---|
| Claude limits (5h, weekly, per-model weekly e.g. Fable) | `GET https://api.anthropic.com/api/oauth/usage` → `limits[]` (`kind`: `session`, `weekly_all`, `weekly_scoped` + `scope.model.display_name`) | Claude Code's OAuth token from Keychain item `Claude Code-credentials` (`claudeAiOauth.accessToken`, check `expiresAt` ms), header `anthropic-beta: oauth-2025-04-20` |
| Claude fallback | `~/.claude/usage-cache.json` written by the status line | — |
| Claude account identity | `GET https://api.anthropic.com/api/oauth/profile` → `account.{uuid,email}` | same OAuth token |
| Codex usage per account | `GET https://chatgpt.com/backend-api/wham/usage` (`rate_limit.primary_window/secondary_window`: `used_percent`, `limit_window_seconds`, `reset_at`) | `Authorization: Bearer <access_token>`, `ChatGPT-Account-Id: <account_id>` from each stored `auth.json` |
| Codex free "Full reset" credits | `GET https://chatgpt.com/backend-api/wham/rate-limit-reset-credits` (`credits[]` with `status`, `expires_at`) | same |

**Never call** `.../rate-limit-reset-credits/consume` (or the app-server `account/rateLimitResetCredit/consume`):
it spends a reset. Claude's free reset (shown on claude.ai → Settings → Usage) is NOT exposed by
`/api/oauth/usage`; its endpoint is unknown (claude.ai web API, cookie auth).

`/api/oauth/usage` is **rate limited** (HTTP 429 with `retry-after`, ~5 min) when polled often:
`ccx` re-reads it at most every 2 minutes per account, caches identities per token, and the app
does not call it itself when ccx has accounts.

Plans seen: Codex Pro has only a weekly window (no 5h); `prolite` = "Pro Lite"; Claude `max`.

## `cx` — Codex accounts

Commands: `cx` (list + usage), `cx save <name>`, `cx add [name]`, `cx use <name>` / `cx <name>`,
`cx rm <name>`, `cx json` (machine output consumed by the app).

- Stored credentials: `~/.codex-accounts/<name>.json` (0600, dir 0700). Files starting with `_`
  are backups and ignored. **Never commit or print tokens.**
- `cx add` logs in inside a throwaway `CODEX_HOME` (temp dir) so the active login is untouched;
  name defaults to the email local part.
- Before any switch, `sync_active()` copies the live `~/.codex/auth.json` back to its stored
  account (Codex refreshes/rotates tokens; stale copies would break).
- Account identity = (`chatgpt_user_id` from id_token claims, `tokens.account_id`).

### Critical finding: the daemon caches auth

Verified in Codex source (`codex-rs/login/src/auth/manager.rs`, `codex-rs/tui/src/lib.rs`) and
empirically:
- Every Codex process loads auth once and caches it; it does not watch `auth.json`. It only
  re-reads it on token refresh ("guarded reload"); if the account changed it fails with
  "signed in to another account".
- The `codex` TUI attaches to the shared app-server daemon
  (`~/.codex/app-server-control/app-server-control.sock`) when it runs. So replacing `auth.json`
  alone does NOT switch new `codex` sessions.
- Fix in `cx use`: write `auth.json`, `codex app-server daemon restart`, then verify with
  `daemon_email()` — a tiny WebSocket JSON-RPC client over the unix socket calling
  `initialize` → `initialized` → `account/read`. (`codex app-server proxy` over stdio did not
  answer; the socket speaks WebSocket.)
- The ChatGPT desktop app (embedded Codex) and the Cursor extension run their own app-servers:
  they need a restart. `cx use` prints `NOTE: Restart ChatGPT and Cursor…`; the app shows that
  line under the Codex card.
- Restarting the daemon may interrupt running `codex` CLI sessions.

## `ccx` — Claude Code accounts

Commands: `ccx` (list + usage), `ccx save [name]`, `ccx add [name]`, `ccx use <name>` / `ccx <name>`,
`ccx rm <name>`, `ccx json` (consumed by the app).

- Claude Code keeps its token in the Keychain item `Claude Code-credentials` (account = macOS user,
  JSON `claudeAiOauth.{accessToken, refreshToken, expiresAt(ms), subscriptionType, …}`; access
  token lives ~8 h, Claude Code refreshes and rotates it) and the profile in `~/.claude.json` →
  `oauthAccount`. A different `CLAUDE_CONFIG_DIR` uses a different Keychain item (verified: an empty
  config dir reports `loggedIn: false`), which is how `ccx add` logs in without touching the
  active account (temp config dir, then the new item is read and deleted).
- Each saved account: Keychain item `ai-usage-claude:<name>` (account `ai-usage`), value
  `pack({credentials, oauthAccount})` = `z:` + base64(zlib(json)). Metadata without secrets
  (email, uuid, plan, last usage, `usage_at`) in `~/.config/ai-usage/claude-accounts.json`;
  identity cache (token hash → uuid/email) in `claude-identity-cache.json`.
- Keychain writes go through `security -i` on stdin with `-X <hex>` so secrets never hit argv.
  **`security -i` truncates lines around 4 KB** — hence compression for our entries; the active
  item is written as plain JSON (≈1.2 KB → 2.5 KB hex), the format Claude Code expects.
- Identity of an account = `/api/oauth/profile` uuid (falls back to `oauthAccount.accountUuid`).
- `sync_active()` copies the live (rotated) credentials back to the active account's entry before
  any switch, only when they changed.
- `ccx use`: write `Claude Code-credentials` + replace only `oauthAccount` in `~/.claude.json`
  (atomic, keeps file mode), verify via profile, print `NOTE: Restart open Claude Code sessions (N
  running)…` (helpers `daemon run`, `--bg-pty-host`, `--bg-spare` are not counted).
- Inactive accounts: their tokens are **never refreshed by ccx** (by design); usage shown is
  the last known one, flagged `last_seen`, reset to 0 once its window has passed.
- Open Claude Code sessions keep the old token in memory and, when they refresh it, may write the
  old account back. The app remembers the account chosen in the panel and shows a note if the
  active account changes back.
- The Claude desktop app has its own login and is not affected.

## Claude Code status line (`claude/statusline.sh`)

Output: `Opus 5.5 │ cache 47m │ session: 3h29 5% │ weekly: 5d 2%` (colors by %). `refreshInterval: 60` in `~/.claude/settings.json`.

- Reads the stdin JSON: `model.display_name`, `prompt_cache.{warm,expires_at}`,
  `rate_limits.{five_hour,seven_day}.{used_percentage,resets_at}`.
- Prompt cache TTL comes from the payload (1h on subscriptions, 5 min in overage); every request
  refreshes it, so it sits at ~59–60m during active chatting.
- Chaining: if another tool owned the status line, `install.sh` saves its command to
  `~/.config/ai-usage/statusline-chain`, and the script feeds it every payload in the background
  so that integration keeps working.
- Writes `~/.claude/usage-cache.json` by **merging per window**, not overwriting: every Claude
  Code session reports its own last-seen snapshot and idle sessions report stale ones (e.g. a
  snapshot without `five_hour`). Rule: later `resets_at` wins; same window → higher % wins.

## Screenshots

`tools/screenshots/render.sh` renders `docs/screenshots/` from the real SwiftUI views
(`PanelView`, `MenuBarLabel`) with fictional data, on a reconstructed desktop (mesh gradient
wallpaper, menu bar). It compiles `app/AIUsage.swift` with `-D SCREENSHOTS`, which drops the
app's `@main` and uses `UsageModel(live: false)`; the UI is forced to English. Never commit
screenshots of real accounts.

## Ideas / not done

- Claude free reset credit (endpoint unknown, see above).
