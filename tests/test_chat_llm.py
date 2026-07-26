"""Tests for ChatLLM.generate() (bot/services/llm/agent.py).

The real mistralai.Mistral client is never constructed; a fake client is
injected via the mistral_client constructor parameter, exposing the two
surfaces ChatLLM actually touches: client.chat.complete_async(...) and
client.files.upload_async/get_signed_url_async(...) for the reference-PDF
attachment path.

agent.py caches the signed PDF URL in a module-level variable guarded by an
asyncio.Lock, so every test resets that cache via the autouse fixture below
to avoid cross-test leakage.
"""

import json

import pytest

import bot.services.llm.agent as agent_module
from bot.exceptions.medical_record_exceptions import MedicalRecordGenerationError
from bot.services.llm.agent import BASE_BACKOFF_SECONDS, ChatLLM, MAX_ATTEMPTS
from mistralai.client.models import DocumentURLChunk, TextChunk


@pytest.fixture(autouse=True)
def reset_reference_pdf_cache():
    agent_module._invalidate_reference_pdf_cache()
    yield
    agent_module._invalidate_reference_pdf_cache()


@pytest.fixture(autouse=True)
def sleep_calls(monkeypatch):
    calls: list[float] = []

    async def _instant_sleep(seconds):
        calls.append(seconds)

    monkeypatch.setattr(agent_module.asyncio, "sleep", _instant_sleep)
    return calls


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeChatResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


class FakeUploadedFile:
    def __init__(self, file_id="file-123"):
        self.id = file_id


class FakeSignedUrl:
    def __init__(self, url="https://example.com/signed.pdf"):
        self.url = url


class FakeChatEndpoint:
    """Fake for client.chat -- exposes complete_async(...).

    `responses` is a list of callables consumed one per call (so a test can
    make e.g. the first call fail and the second succeed); the last callable
    is reused once the list is exhausted. Each entry is a zero-arg callable
    returning a FakeChatResponse or raising an exception, so tests can encode
    "fail then succeed" scenarios explicitly.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[dict] = []

    async def complete_async(self, **kwargs):
        self.calls.append(kwargs)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        outcome = self.responses[index]
        return outcome()


class FakeFilesEndpoint:
    """Fake for client.files -- exposes upload_async/get_signed_url_async.

    If `fail_upload` is True, upload_async raises, simulating the PDF-attach
    failure path that ChatLLM.generate() must recover from without the PDF.
    """

    def __init__(self, fail_upload: bool = False):
        self.fail_upload = fail_upload
        self.upload_calls = 0
        self.signed_url_calls = 0
        self.upload_kwargs: list[dict] = []
        self.signed_url_kwargs: list[dict] = []

    async def upload_async(self, **kwargs):
        self.upload_calls += 1
        self.upload_kwargs.append(kwargs)
        if self.fail_upload:
            raise RuntimeError("upload failed")
        return FakeUploadedFile()

    async def get_signed_url_async(self, **kwargs):
        self.signed_url_calls += 1
        self.signed_url_kwargs.append(kwargs)
        return FakeSignedUrl()


class FakeMistralClient:
    def __init__(self, chat_responses, fail_upload: bool = False):
        self.chat = FakeChatEndpoint(chat_responses)
        self.files = FakeFilesEndpoint(fail_upload=fail_upload)


VALID_JSON = json.dumps(
    {
        "complaints": "жалобы",
        "diseases": "заболевания",
        "examination": "осмотр",
        "treatment": "лечение",
    },
    ensure_ascii=False,
)

MISSING_KEY_JSON = json.dumps(
    {
        "complaints": "жалобы",
        "diseases": "заболевания",
        "examination": "осмотр",
    },
    ensure_ascii=False,
)


def _ok_response(content=VALID_JSON):
    return lambda: FakeChatResponse(content)


def _raising_response(exc: Exception):
    def _raise():
        raise exc
    return _raise


@pytest.mark.asyncio
async def test_generate_happy_path_returns_parsed_json_after_one_attempt():
    client = FakeMistralClient(chat_responses=[_ok_response()])
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    result = await chat_llm.generate("prompt text")

    assert result == json.loads(VALID_JSON)
    assert len(client.chat.calls) == 1

    # the reference PDF must actually have been uploaded and attached to
    # the chat message, since the upload succeeded
    assert client.files.upload_calls == 1
    assert client.files.signed_url_calls == 1
    assert client.files.upload_kwargs[0]["purpose"] == "ocr"
    uploaded_file = client.files.upload_kwargs[0]["file"]
    assert "file_name" in uploaded_file and "content" in uploaded_file
    assert client.files.signed_url_kwargs[0]["file_id"] == "file-123"

    user_content = client.chat.calls[0]["messages"][1]["content"]
    document_chunks = [c for c in user_content if isinstance(c, DocumentURLChunk)]
    assert len(document_chunks) == 1
    assert document_chunks[0].document_url == "https://example.com/signed.pdf"


@pytest.mark.asyncio
async def test_generate_reuses_cached_pdf_url_across_calls():
    client = FakeMistralClient(chat_responses=[_ok_response()])
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    await chat_llm.generate("first prompt")
    await chat_llm.generate("second prompt")

    assert len(client.chat.calls) == 2
    # the signed URL is cached at module level, so the second generate()
    # call must not re-upload or re-sign the reference PDF
    assert client.files.upload_calls == 1
    assert client.files.signed_url_calls == 1


@pytest.mark.asyncio
async def test_generate_missing_required_keys_retries_then_raises(sleep_calls):
    # PDF upload succeeds, so attempt 1 consumes the "retry without PDF"
    # branch (no sleep, no attempt limit spent on a backoff wait); attempts
    # 2 and 3 are genuine PDF-free retries with a real backoff sleep
    # in between them.
    client = FakeMistralClient(
        chat_responses=[_ok_response(MISSING_KEY_JSON)],
    )
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    with pytest.raises(MedicalRecordGenerationError):
        await chat_llm.generate("prompt text")

    assert len(client.chat.calls) == MAX_ATTEMPTS
    assert sleep_calls == [BASE_BACKOFF_SECONDS * 2]
    # only the first (PDF-attached) attempt should have a document chunk
    first_call_content = client.chat.calls[0]["messages"][1]["content"]
    assert any(isinstance(c, DocumentURLChunk) for c in first_call_content)
    for call in client.chat.calls[1:]:
        content = call["messages"][1]["content"]
        assert not any(isinstance(c, DocumentURLChunk) for c in content)


@pytest.mark.asyncio
async def test_generate_chat_completion_always_fails_retries_then_raises(sleep_calls):
    client = FakeMistralClient(
        chat_responses=[_raising_response(RuntimeError("network error"))],
    )
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    with pytest.raises(MedicalRecordGenerationError):
        await chat_llm.generate("prompt text")

    assert len(client.chat.calls) == MAX_ATTEMPTS
    assert sleep_calls == [BASE_BACKOFF_SECONDS * 2]


@pytest.mark.asyncio
async def test_generate_persistent_failure_with_pdf_upload_failing_uses_real_backoff_retries(sleep_calls):
    """When the PDF upload itself fails on attempt 1, the failure is caught
    locally and attempt 1 still reaches chat.complete_async as a text-only
    request. Since that text-only chat call also fails, all three attempts
    reach the chat endpoint, separated by normal exponential backoff -- this
    is the test that most directly proves the backoff-driven retry loop
    works and that a broken PDF path no longer silently reduces the
    effective chat-completion retry budget."""
    client = FakeMistralClient(
        chat_responses=[_raising_response(RuntimeError("network error"))],
        fail_upload=True,
    )
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    with pytest.raises(MedicalRecordGenerationError):
        await chat_llm.generate("prompt text")

    # the PDF upload is only attempted once (attempt 1); every attempt
    # reaches the chat endpoint since the upload failure never blocks it
    assert client.files.upload_calls == 1
    assert len(client.chat.calls) == MAX_ATTEMPTS
    assert sleep_calls == [BASE_BACKOFF_SECONDS * (2 ** 0), BASE_BACKOFF_SECONDS * (2 ** 1)]
    for call in client.chat.calls:
        content = call["messages"][1]["content"]
        assert not any(isinstance(c, DocumentURLChunk) for c in content)


@pytest.mark.asyncio
async def test_generate_pdf_attach_failure_falls_back_to_text_only_success(sleep_calls):
    client = FakeMistralClient(chat_responses=[_ok_response()], fail_upload=True)
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    result = await chat_llm.generate("prompt text")

    assert result == json.loads(VALID_JSON)
    assert client.files.upload_calls == 1
    # the upload failure recovers within the same attempt (no backoff sleep)
    # and the chat completion succeeds on the very next try
    assert len(client.chat.calls) == 1
    assert sleep_calls == []

    user_content = client.chat.calls[0]["messages"][1]["content"]
    assert len(user_content) == 1
    assert user_content[0].text == "prompt text"
    assert not any(isinstance(c, DocumentURLChunk) for c in user_content)


@pytest.mark.asyncio
async def test_generate_handles_list_shaped_response_content():
    """The Mistral SDK can return message.content as a list of chunk objects
    rather than a plain string; ChatLLM must join the "text"-typed chunks
    into the raw JSON string before parsing."""
    list_content = [TextChunk(text=VALID_JSON)]
    client = FakeMistralClient(chat_responses=[lambda: FakeChatResponse(list_content)])
    chat_llm = ChatLLM(api_key="key", model="mistral-large", mistral_client=client)

    result = await chat_llm.generate("prompt text")

    assert result == json.loads(VALID_JSON)


def test_prompt_builder_getters_do_not_raise_and_return_usable_values():
    """Regression guard for the wrong-hardcoded-path bug where prompt_builder
    paths were built with an extra "PythonProject3/" prefix, crashing at
    import/read time instead of resolving from the actual project root."""
    from bot.utils import prompt_builder

    system_prompt = prompt_builder.get_system_prompt()
    unfilled_template = prompt_builder.get_unfilled_template()
    filled_example = prompt_builder.get_filled_example()
    reference_pdf_path = prompt_builder.get_reference_pdf_path()

    assert isinstance(system_prompt, str) and system_prompt.strip() != ""
    assert isinstance(unfilled_template, str) and unfilled_template.strip() != ""
    assert isinstance(filled_example, str) and filled_example.strip() != ""
    assert reference_pdf_path.exists()

    user_prompt = prompt_builder.build_user_prompt("summary", "diagnosis")
    assert "summary" in user_prompt
    assert "diagnosis" in user_prompt
