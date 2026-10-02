# AI Usage

Suivi de l'usage Claude et Codex sur macOS, et bascule entre plusieurs comptes Codex.

- **App de la barre de menus** (`app/`) — panneau SwiftUI : limites Claude (5h, weekly, par modèle),
  limites et resets gratuits de chaque compte Codex, bascule de compte en un clic.
- **`cx`** (`bin/cx`) — gestion des comptes Codex en ligne de commande.
- **Status line Claude Code** (`claude/statusline.sh`) — `Opus 5.5 │ cache 47m │ session: 3h29 5% │ weekly: 5d 2%`.

## Installation

```sh
./install.sh
```

Prérequis : macOS 14+, Xcode Command Line Tools (`xcode-select --install`), `jq`, Codex CLI.
Les logos sont copiés depuis les apps Claude et ChatGPT si elles sont installées.

## `cx` — comptes Codex

```sh
cx                 # liste les comptes avec leur usage (● = actif)
cx save <nom>      # enregistre le compte actuellement connecté
cx add [nom]       # connecte un autre compte (navigateur), sans toucher au compte actif
cx use <nom>       # bascule (ou simplement : cx <nom>)
cx rm <nom>        # retire un compte de la liste
```

Les identifiants sont stockés dans `~/.codex-accounts/` (droits 600), **jamais dans ce dépôt**.

### Comment marche la bascule

Codex lit `~/.codex/auth.json`, mais chaque processus Codex garde le compte en mémoire.
La commande `codex` se rattache au daemon app-server partagé : `cx use` remplace donc
`auth.json` (après y avoir resynchronisé les jetons à jour du compte actif), redémarre le
daemon, puis lui demande (`account/read` via sa socket) quel compte il a chargé.

L'app ChatGPT (Codex) et l'extension Cursor ont leur propre serveur : il faut les relancer.

## Sources de données

| Donnée | Source |
|---|---|
| Usage Claude | `GET api.anthropic.com/api/oauth/usage` avec le jeton de Claude Code (Trousseau), sinon `~/.claude/usage-cache.json` écrit par la status line |
| Usage Codex | `GET chatgpt.com/backend-api/wham/usage` par compte |
| Resets gratuits Codex | `GET chatgpt.com/backend-api/wham/rate-limit-reset-credits` (lecture seule) |

## Développement

```sh
app/build.sh && pkill -x AIUsage; open ~/Applications/AI\ Usage.app
```
