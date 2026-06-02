# Python Voice-Controlled AI Desktop Assistant

## Architecture

- `main.py`: Runs the voice loop and routes AI JSON responses.
- `config.py`: Loads environment settings and the assistant system prompt.
- `services/speech_service.py`: Captures microphone input and speaks responses.
- `services/ai_service.py`: Calls Gemini `generateContent` and parses JSON.
- `services/command_executor.py`: Executes supported desktop actions.
- `utils/file_manager.py`: Safely writes generated files.
- `utils/logger.py`: Console and file logging.

## Setup

```powershell
cd assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:GEMINI_API_KEY="your-api-key"
python main.py
```

## Notes

- Generated code files are saved into `generated_files` by default.
- File deletion, shutdown, restart, sleep, and risky shell commands require a `confirmed=true` parameter in the AI JSON.
- The Gemini REST client uses the official `generateContent` endpoint:
  `https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent`.
