from __future__ import annotations

import asyncio
import json
from typing import Any

from config import Settings
from services.ai_service import GeminiService
from services.command_executor import CommandExecutor
from services.speech_service import SpeechService
from utils.file_manager import FileManager
from utils.logger import get_logger


logger = get_logger(__name__)


class DesktopAssistant:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.speech = SpeechService(settings)
        self.ai = GeminiService(settings)
        self.file_manager = FileManager(settings.output_dir)
        self.executor = CommandExecutor(self.file_manager)

    async def run(self) -> None:
        self._print_startup()
        while True:
            try:
                user_text = await self.speech.listen()
                if not user_text:
                    continue

                if user_text.lower() in {"exit", "quit", "stop assistant"}:
                    await self.speech.speak("Assistant stopped.")
                    break

                print(f"\nYou: {user_text}")
                response = await self.ai.get_response(user_text)
                result = await self.handle_response(response)
                print(json.dumps(result, indent=2))

                if result.get("message"):
                    await self.speech.speak(str(result["message"]))

                if not self.settings.listen_forever:
                    break
            except KeyboardInterrupt:
                print("\nAssistant stopped.")
                break
            except Exception as exc:
                logger.exception("Unexpected assistant error")
                print(json.dumps({"status": "error", "message": str(exc)}, indent=2))
                await self.speech.speak("I hit an error. Check the console for details.")

    async def handle_response(self, response: dict[str, Any]) -> dict[str, Any]:
        mode = response.get("mode")

        if mode == "chat":
            message = str(response.get("response", ""))
            return {"status": "ok", "mode": "chat", "message": message}

        if mode == "code":
            filename = str(response.get("filename", "generated_code.txt"))
            content = str(response.get("content", ""))
            path = self.file_manager.write_file(filename, content)
            return {
                "status": "ok",
                "mode": "code",
                "message": f"Saved code file: {path}",
                "path": str(path),
            }

        if mode == "command":
            action = str(response.get("action", ""))
            parameters = response.get("parameters") or {}
            if not isinstance(parameters, dict):
                raise ValueError("Command parameters must be a JSON object.")
            return await self.executor.execute(action, parameters)

        raise ValueError(f"Unsupported AI response mode: {mode}")

    def _print_startup(self) -> None:
        print("Python Voice-Controlled AI Desktop Assistant")
        print("Say 'exit', 'quit', or 'stop assistant' to close.")
        print("Listening...\n")


async def main() -> None:
    settings = Settings.from_env()
    assistant = DesktopAssistant(settings)
    await assistant.run()


if __name__ == "__main__":
    asyncio.run(main())
