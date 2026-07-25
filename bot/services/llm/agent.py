import asyncio
import json
import logging
import re

import httpx

from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ("complaints", "anamnesis", "objective", "diagnosis_reason", "treatment_plan")
MAX_ATTEMPTS = 3
BASE_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT_SECONDS = 120

_THINK_BLOCK_RE = re.compile(r"<think>.*?</think>", re.DOTALL)


class ChatLLM:
    """Stateless client for the Ollama chat completion endpoint.

    Each call to generate() is independent: no conversation history is kept
    between calls, since medical record generation for one appointment must
    never leak context from a previously processed patient.
    """

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url
        self.model = model

    async def generate(self, prompt: str) -> dict:
        """Send a single-turn prompt and return the parsed JSON response.

        Retries up to MAX_ATTEMPTS times with exponential backoff on network
        errors, non-2xx responses, invalid JSON, or a JSON payload missing
        any of REQUIRED_KEYS. Raises MedicalRecordGenerationError once every
        attempt is exhausted, never leaking the underlying httpx/JSON error.
        """
        last_error: Exception | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                return await self._request_once(prompt)
            except Exception as exc:
                last_error = exc
                logger.warning("Ollama request attempt %s/%s failed: %s", attempt, MAX_ATTEMPTS, exc)
                if attempt < MAX_ATTEMPTS:
                    await asyncio.sleep(BASE_BACKOFF_SECONDS * (2 ** (attempt - 1)))

        raise MedicalRecordGenerationError(
            f"Не удалось получить ответ от Ollama после {MAX_ATTEMPTS} попыток."
        ) from last_error

    async def _request_once(self, prompt: str) -> dict:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [{"role": "user", "content": prompt}],
                    "stream": False,
                    "format": "json",
                },
            )

        response.raise_for_status()

        content = response.json()["message"]["content"]
        content = _THINK_BLOCK_RE.sub("", content).strip()

        data = json.loads(content)

        missing_keys = [key for key in REQUIRED_KEYS if key not in data]
        if missing_keys:
            raise ValueError(f"Ollama response is missing required keys: {missing_keys}")

        return data
