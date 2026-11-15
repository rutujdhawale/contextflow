"""Optional answer synthesis providers for the interactive demo."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import base64
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .schema import EvidencePacket


class LLMError(RuntimeError):
    """Raised when an enabled synthesis provider cannot answer."""


SYSTEM_PROMPT = (
    "You are the PathContext incident assistant. Answer only from the supplied "
    "evidence. Cite source labels in square brackets. If evidence is insufficient "
    "or contradictory, say so plainly. Never invent graph relationships."
)


@dataclass(frozen=True)
class LLMAnswer:
    provider: str
    text: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    total_tokens: int | None = None


class GroqProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "llama-3.1-8b-instant",
        timeout: float = 30,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def answer(self, question: str, packet: EvidencePacket) -> LLMAnswer:
        body = {
            "model": self.model,
            "temperature": 0.1,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nEvidence:\n{packet.context}",
                },
            ],
        }
        request = Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(body).encode(),
            headers={
                "Authorization": "Bearer " + self.api_key,
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode())
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as error:
            raise LLMError(f"Groq request failed: {error}") from error
        try:
            text = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as error:
            raise LLMError("Groq returned an unexpected response shape") from error
        if not isinstance(text, str) or not text.strip():
            raise LLMError("Groq returned an empty answer")
        usage = payload.get("usage", {})
        input_tokens = usage.get("prompt_tokens")
        output_tokens = usage.get("completion_tokens")
        total_tokens = usage.get("total_tokens")
        return LLMAnswer(
            "groq",
            text.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=total_tokens,
        )


def describe_image(
    image_path: str | os.PathLike[str],
    api_key: str,
    *,
    model: str | None = None,
    timeout: float = 45,
) -> str:
    """Create one compact image description for storage-time indexing.

    The image is sent only during ingestion. Later questions use the stored
    description, avoiding repeated image tokens and repeated provider calls.
    """
    path = os.fspath(image_path)
    with open(path, "rb") as image_file:
        encoded = base64.b64encode(image_file.read()).decode("ascii")
    mime = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }.get(os.path.splitext(path)[1].lower(), "application/octet-stream")
    body = {
        "model": model or os.getenv("GROQ_VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct"),
        "temperature": 0.1,
        "max_tokens": 220,
        "messages": [
            {
                "role": "system",
                "content": (
                    "Describe this image compactly for retrieval. Extract visible "
                    "chart trends, table headers/values, labels, entities, and "
                    "uncertainty. Do not invent unreadable details."
                ),
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Return a concise factual description."},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{encoded}"},
                    },
                ],
            },
        ],
    }
    request = Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={
            "Authorization": "Bearer " + api_key,
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode())
        text = payload["choices"][0]["message"]["content"]
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise LLMError(f"Groq image analysis failed: {error}") from error
    if not isinstance(text, str) or not text.strip():
        raise LLMError("Groq image analysis returned an empty description")
    return text.strip()


class OpenCodeProvider:
    """Fallback adapter for a locally installed OpenCode CLI."""

    def __init__(self, command: str | None = None, timeout: float = 60) -> None:
        self.command = command or os.getenv("OPENCODE_COMMAND", "opencode run")
        self.timeout = timeout

    def answer(self, question: str, packet: EvidencePacket) -> LLMAnswer:
        prompt = (
            f"{SYSTEM_PROMPT}\n\nQuestion: {question}\n\n"
            f"Evidence:\n{packet.context}"
        )
        command = shlex.split(self.command) + [prompt]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LLMError(f"OpenCode request failed: {error}") from error
        if result.returncode != 0:
            detail = result.stderr.strip() or f"exit status {result.returncode}"
            raise LLMError(f"OpenCode request failed: {detail}")
        if not result.stdout.strip():
            raise LLMError("OpenCode returned an empty answer")
        output_tokens = max(1, len(result.stdout.split()) * 4 // 3)
        input_tokens = max(1, len(prompt.split()) * 4 // 3)
        return LLMAnswer(
            "opencode",
            result.stdout.strip(),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )


def synthesize(
    question: str,
    packet: EvidencePacket,
    *,
    groq_api_key: str | None = None,
    groq_model: str | None = None,
    opencode_command: str | None = None,
) -> LLMAnswer:
    """Use Groq when configured, otherwise fall back to OpenCode."""
    if groq_api_key:
        try:
            return GroqProvider(
                groq_api_key, groq_model or "llama-3.1-8b-instant"
            ).answer(question, packet)
        except LLMError:
            pass
    return OpenCodeProvider(opencode_command).answer(question, packet)
