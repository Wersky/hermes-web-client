[English](README.md) | [简体中文](README_zh.md)

# Wermes Client

> A local web client for [Hermes Agent](https://github.com/nousresearch/hermes-agent) — three-panel layout, SSE streaming tool calls, session management, and dangerous command confirmation.

## Screenshot

![screenshot](screenshots/main.png)

## Why

Every day I'd open hermes CLI, start a new session, and say "hey deepseek, take me back to yesterday's conversation" — then it'd pull up the one from the day before (ˉ▽ˉ；)... Even manually listing sessions meant: mouse → copy → `hermes --resume xxxxxx`. Come on, man!

## Features

- **Three-panel Web UI** — session list / chat / skills & memory, Linear dark theme
- **SSE streaming tool calls** — real-time display of every tool the agent runs (`🔍 search_files → 📖 read_file → 💻 terminal`)
- **Session management** — browse history, delete, right-click details (tokens / cost / model), non-blocking switching
- **Session continuation** — based on `hermes chat -q --resume`, multi-turn conversations stay in one session
- **Dangerous command confirmation** — detects blocked dangerous commands, modal approval → `--yolo` retry (still fixing this TT)
- **i18n (Chinese / English)** — switch UI language in settings with one click
- **Zero frontend dependencies** — single-file SPA, no npm / webpack
- **Low overhead** — SQLite-based storage, at most ~10% slower than raw hermes CLI

## Quick Start

You can also just tell hermes: "hey, run run.py for me" and save it as a skill.

```bash
# 1. Install dependencies
pip install fastapi uvicorn pydantic

# 2. Run
python run.py
# → http://127.0.0.1:7861
```

> Requires [Hermes Agent](https://github.com/nousresearch/hermes-agent) installed and configured.

## Project Structure

```
wermes-client/
├── run.py              # One-click launcher
├── server.py           # FastAPI backend (SSE + SQLite polling)
├── requirements.txt    # Python dependencies
├── static/
│   ├── index.html      # Frontend SPA (single file, no framework)
│   └── starfield.html  # Easter egg: particle animation
└── .gitignore
```

## Architecture

```
Browser ──SSE──→ FastAPI ──subprocess──→ hermes -z "msg"            ← new session
                                    └──→ hermes chat -q "msg"      ← continue session
                                              --resume <sid> --quiet
```

**SSE event stream:**

| Event | When | Description |
|-------|------|-------------|
| `session` | Session ID resolved | Frontend updates current session |
| `tool` | Process running (0.3s poll) | Real-time tool call + full command |
| `danger` | Dangerous command blocked | Show confirmation dialog |
| `response` | Process finished | Final reply |
| `done` | Stream ended | Clean up state |

**Dual mode:**

| Mode | CLI Command | Description |
|------|-------------|-------------|
| New | `hermes -z "msg"` | Create new session |
| Continue | `hermes chat -q "msg" --resume <sid> --quiet` | Append to existing session |

## API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/sessions` | GET | List sessions |
| `/api/sessions/{id}` | GET / DELETE | Session messages / delete |
| `/api/sessions/{id}/info` | GET | Session metadata (model / tokens / cost) |
| `/api/chat/stream` | POST | Core: SSE streaming chat |
| `/api/chat/retry` | POST | Retry blocked command with `--yolo` |
| `/api/skills` | GET | List skills |
| `/api/skills/{name}` | GET | Skill details |
| `/api/memory` | GET | Memory data |

## Tech Stack

- **Backend**: Python / FastAPI / SSE / SQLite
- **Frontend**: Vanilla JS / Single-file SPA / CSS Variables
- **CLI Integration**: Hermes Agent subprocess + SQLite direct-read polling

## Bugs & Notes

This is v1.0 — plenty of bugs. The tool call display can't be as detailed as the CLI since we're in a browser, and the SQLite polling adds ~10% overhead. Web clients, man... they're just not as smooth TT

Also this is my first time publishing a proper GitHub repo and III honestly don't know what to write here 😰😰😰

## Future

Planning to migrate to an MCP client architecture: user input → underlying CLI → session output, with only I/O overhead for maximum performance.

## License

MIT
