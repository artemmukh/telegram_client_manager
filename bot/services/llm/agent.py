import asyncio
import json
import logging

from mistralai.client import Mistral
from mistralai.client.models import DocumentURLChunk, TextChunk

from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
from bot.utils import prompt_builder

logger = logging.getLogger(__name__)

REQUIRED_KEYS = ("complaints", "diseases", "examination", "treatment", "tooth_map")
MAX_ATTEMPTS = 2
MIN_COMPLETION_START_INTERVAL_SECONDS = 1.1

_reference_pdf_url: str | None = None
_reference_pdf_lock = asyncio.Lock()


def _invalidate_reference_pdf_cache() -> None:
    global _reference_pdf_url
    _reference_pdf_url = None


async def _get_reference_pdf_url(client: Mistral) -> str | None:
    global _reference_pdf_url

    if _reference_pdf_url is not None:
        return _reference_pdf_url

    async with _reference_pdf_lock:
        if _reference_pdf_url is not None:
            return _reference_pdf_url

        pdf_path = prompt_builder.get_reference_pdf_path()
        if not pdf_path.exists():
            logger.warning("Reference PDF not found at %s, skipping attachment.", pdf_path)
            return None

        content = await asyncio.to_thread(pdf_path.read_bytes)
        # "ocr" is the only Mistral FilePurpose value valid for a document upload
        # used as a document_url reference; this never invokes client.ocr.process,
        # so no per-request OCR call happens here.
        uploaded = await client.files.upload_async(
            file={"file_name": pdf_path.name, "content": content},
            purpose="ocr",
        )
        signed = await client.files.get_signed_url_async(file_id=uploaded.id)
        _reference_pdf_url = signed.url

        return _reference_pdf_url


class ChatLLM:
    """Stateless client for the Mistral chat completion endpoint.

    Each call to generate() is independent: no conversation history is kept
    between calls, since medical record generation for one appointment must
    never leak context from a previously processed patient.
    """

    def __init__(self, api_key: str, model: str, mistral_client: Mistral | None = None):
        self.model = model
        self.client = mistral_client or Mistral(api_key=api_key)
        self._completion_start_lock = asyncio.Lock()
        self._next_completion_start_monotonic = 0.0

    async def generate(self, prompt: str) -> dict:
        """Send a single-turn prompt and return the parsed JSON response.

        Retries up to MAX_ATTEMPTS times on network errors, non-2xx responses,
        invalid JSON, or a JSON payload missing any of REQUIRED_KEYS
        (complaints, diseases, examination, treatment, tooth_map). Completion
        starts are rate-limited per ChatLLM instance. Raises
        MedicalRecordGenerationError once every attempt is exhausted, never
        leaking the underlying SDK/JSON error.

        If an attempt that included the cached reference PDF fails, the
        module-level PDF URL cache is invalidated and the next attempt is
        made without the PDF, instead of repeatedly retrying against a
        possibly-expired signed URL.
        """
        last_error: Exception | None = None
        attach_pdf = True

        for attempt in range(1, MAX_ATTEMPTS + 1):
            pdf_url: str | None = None
            if attach_pdf:
                try:
                    pdf_url = await _get_reference_pdf_url(self.client)
                except Exception as exc:  # noqa: BLE001 - attachment failure must fall back to text-only completion.
                    logger.warning("Reference PDF attachment failed, continuing without it: %s", exc)
                    _invalidate_reference_pdf_cache()

            used_pdf = pdf_url is not None
            try:
                return await self._request_once(prompt, pdf_url=pdf_url)
            except Exception as exc:  # noqa: BLE001 - retry must cover SDK, JSON, and validation failures.
                last_error = exc
                logger.warning("Mistral request attempt %s/%s failed: %s", attempt, MAX_ATTEMPTS, exc)

                if used_pdf:
                    _invalidate_reference_pdf_cache()
                attach_pdf = False
                if attempt < MAX_ATTEMPTS:
                    await self._apply_retry_after_cooldown(exc)

        raise MedicalRecordGenerationError(
            f"Не удалось получить ответ от Mistral после {MAX_ATTEMPTS} попыток."
        ) from last_error

    async def _apply_retry_after_cooldown(self, exc: Exception) -> None:
        """Honor a structured 429 Retry-After value before the next request."""
        if getattr(exc, "status_code", None) != 429:
            return

        headers = getattr(exc, "headers", None)
        retry_after = headers.get("Retry-After") if headers is not None else None
        if retry_after is None:
            return

        try:
            retry_after_seconds = max(0.0, float(retry_after))
        except (TypeError, ValueError):
            logger.warning("Ignoring invalid Mistral Retry-After header: %r", retry_after)
            return

        loop = asyncio.get_running_loop()
        async with self._completion_start_lock:
            self._next_completion_start_monotonic = max(
                self._next_completion_start_monotonic,
                loop.time() + retry_after_seconds,
            )

    async def _wait_for_completion_start_slot(self) -> None:
        """Ensure Mistral completion starts are at least 1.1 seconds apart."""
        loop = asyncio.get_running_loop()

        async with self._completion_start_lock:
            now = loop.time()
            delay = self._next_completion_start_monotonic - now
            if delay > 0:
                await asyncio.sleep(max(delay, MIN_COMPLETION_START_INTERVAL_SECONDS))

            started_at = max(loop.time(), self._next_completion_start_monotonic)
            self._next_completion_start_monotonic = (
                started_at + MIN_COMPLETION_START_INTERVAL_SECONDS
            )

    async def _request_once(self, prompt: str, pdf_url: str | None) -> dict:
        content: list = [TextChunk(text=prompt)]

        if pdf_url is not None:
            content.append(DocumentURLChunk(document_url=pdf_url))

        await self._wait_for_completion_start_slot()
        response = await self.client.chat.complete_async(
            model=self.model,
            messages=[
                {"role": "system", "content": prompt_builder.get_system_prompt()},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            retries=None,
        )

        raw_content = response.choices[0].message.content
        if isinstance(raw_content, list):
            raw_content = "".join(chunk.text for chunk in raw_content if getattr(chunk, "type", None) == "text")

        data = json.loads(raw_content)

        missing_keys = [key for key in REQUIRED_KEYS if key not in data]
        if missing_keys:
            raise ValueError(f"AI response is missing required keys: {missing_keys}")

        return data
