[English](README.md) | [简体中文](README_zh.md)

# Wermes Client

> A local web client for [Hermes Agent](https://github.com/nousresearch/hermes-agent) — three-panel layout, SSE streaming tool calls, session management, and dangerous command confirmation.

## Screenshot

![screenshot](screenshots/main.png)

## Features

- **Three-panel Web UI** — session list / chat / skills & memory, Linear dark theme
- **SSE streaming tool calls** — real-time display of every tool the agent runs (`🔍 search_files → 📖 read_file → 💻 terminal`)
- **Session management** — browse history, delete, right-click details (tokens / cost / model), non-blocking switching
- **Session continuation** — based on `hermes chat -q --resume`, multi-turn conversations stay in one session
- **Dangerous command confirmation** — detects blocked dangerous commands, modal approval → `--yolo` retry
- **i18n (Chinese / English)** — switch UI language in settings with one click
- **Zero frontend dependencies** — single-file SPA, no npm / webpack

## Quick Start

For those use hermes, just tell CLI to use /run.py.Remember to tell it save this process as a skill.

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

## License

MIT
