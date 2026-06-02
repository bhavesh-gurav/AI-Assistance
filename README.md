# JARVIS — AI Desktop Assistant

A production-ready, voice-controlled AI desktop assistant for **Windows**, powered by the
**Gemini Pro API**. Say *"Hey Jarvis"* and ask it to open apps, control your system,
generate code straight into **Cursor**, manage files, search the web, and remember
things about you.

```
You:    "Hey Jarvis, open Chrome"
Jarvis: "Opening Chrome."

You:    "Hey Jarvis, write a C# API for user authentication"
Jarvis: "Here's your C# authentication API."   (code is typed into Cursor)
```

---

## ✨ Features

| Area | What it does |
| --- | --- |
| **Voice interaction** | Wake word (*"Hey Jarvis"*), local speech-to-text (faster-whisper), text-to-speech (pyttsx3) |
| **AI brain** | Gemini Pro for intent understanding, answers, code generation, with conversation memory |
| **App control** | Open/close Chrome, Edge, VS Code, Cursor, Notepad, Calculator, File Explorer, Spotify, Discord, WhatsApp; minimize all |
| **System control** | Shutdown, restart, lock, sleep, volume up/down/mute, brightness — with confirmation for dangerous actions |
| **Coding assistant** | Generates C#/.NET, Angular, TypeScript, SQL, Python, JS, HTML/CSS and writes it into Cursor / saves files / copies to clipboard |
| **Cursor integration** | Opens Cursor, creates files, injects generated code |
| **File operations** | Create/rename/move/delete/search files & folders, open Downloads etc. |
| **Web** | Google / YouTube / GitHub / Stack Overflow search, open any URL |
| **Memory** | SQLite-backed: your name, work profile, preferences, conversation history |
| **Smart routing** | `IntentEngine` classifies into ApplicationControl, SystemControl, CodingTask, GeneralQuestion, FileOperation, WebSearch, MemoryTask |

---

## 🏗 Architecture

```
project-root/
├── app/
│   ├── core/
│   │   ├── assistant.py        # orchestrator: routing → confirm → execute → speak
│   │   ├── intent_engine.py    # local fast-path rules + Gemini fallback
│   │   ├── voice_engine.py     # background wake-word + command loop
│   │   └── memory.py           # ConversationMemory + MemoryService
│   ├── ai/
│   │   ├── gemini_service.py   # Gemini REST client
│   │   └── prompt_manager.py   # system prompt + JSON contract
│   ├── automation/
│   │   ├── desktop_controller.py
│   │   ├── system_controller.py
│   │   ├── browser_controller.py
│   │   ├── cursor_controller.py
│   │   └── file_manager.py
│   ├── speech/
│   │   ├── speech_to_text.py   # faster-whisper
│   │   ├── text_to_speech.py   # pyttsx3
│   │   └── wake_word.py
│   ├── database/
│   │   └── sqlite_manager.py   # schema + CRUD
│   ├── ui/
│   │   └── tray_app.py         # CustomTkinter window
│   ├── config/
│   │   ├── settings.py         # .env-driven settings
│   │   └── logger.py
│   └── main.py                 # entry point (--ui / --voice / --text)
├── run.py
├── requirements.txt
├── .env.example
└── README.md
```

### Data flow

```
Voice → Speech-to-Text → Wake word → IntentEngine
      → (confirm if dangerous) → Execute action / Gemini answer
      → Text-to-Speech
```

### Database schema (SQLite)

- `users` — name, work profile
- `memories` — key/value facts and preferences
- `conversations` — full transcript (role, content, intent)
- `settings` — persisted app preferences

---

## 🚀 Installation (Windows)

1. **Install Python 3.12** from [python.org](https://www.python.org/downloads/) and tick *"Add Python to PATH"*.

2. **Create and activate a virtual environment** (from the project root):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

3. **Install dependencies:**

```powershell
pip install -r requirements.txt
```

> `faster-whisper` downloads its model on first use. `pyaudio` is **not** required —
> audio is captured via `sounddevice`. If `pywinauto` fails to build, the assistant
> still runs; only fine-grained window focusing is affected.

4. **Configure your API key:**

```powershell
Copy-Item .env.example .env
# then edit .env and set GEMINI_API_KEY=...
```

Get a free key at <https://aistudio.google.com/app/apikey>.

---

## ▶️ Usage

```powershell
# Graphical UI (default)
python run.py

# Continuous voice loop (headless)
python -m app.main --voice

# Type commands in the terminal (no microphone needed)
python -m app.main --text
```

### Example commands

```
"Hey Jarvis, open Cursor"
"Hey Jarvis, open file explorer"
"Hey Jarvis, volume up"
"Hey Jarvis, shutdown my laptop"          → asks for confirmation
"Hey Jarvis, create ASP.NET Core CRUD API"
"Hey Jarvis, generate an Angular login page"
"Hey Jarvis, write a SQL query for top customers"
"Hey Jarvis, search Angular dependency injection"
"Hey Jarvis, find Resume.pdf"
"Hey Jarvis, remember my company name is Rysun Labs"
"Hey Jarvis, what's my favourite language?"
```

---

## 🔐 Security

Dangerous actions require an explicit spoken/typed **confirmation** ("yes") before they run:

- Delete files/folders
- Shutdown / Restart

Set `REQUIRE_CONFIRMATION=false` in `.env` to disable (not recommended).

---

## 🔭 Future upgrades

The architecture is intentionally modular so you can add: screen understanding & OCR,
vision/webcam analysis, multi-agent workflows, email & WhatsApp automation, calendar
management, meeting summaries, a stock-market assistant, and home automation — each as
a new controller registered in `Assistant._actions` plus a matching action in
`PromptManager.ACTION_REFERENCE`.

---

## 🛠 Troubleshooting

| Symptom | Fix |
| --- | --- |
| *"GEMINI_API_KEY is not set"* | Add the key to `.env` |
| No microphone input | Check Windows mic permissions; verify the default input device |
| `customtkinter` import error | `pip install customtkinter`, or run with `--text` / `--voice` |
| Brightness not changing | `pip install screen-brightness-control` (some external monitors don't support it) |
| Code didn't appear in Cursor | Ensure the `cursor` CLI is on PATH; otherwise the code is saved to `generated_files/` and copied to the clipboard |
```
