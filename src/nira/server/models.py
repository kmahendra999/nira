"""Pydantic request/response models for the OpenAI-compatible API."""

from __future__ import annotations

import time
import uuid
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: str = ""
    name: Optional[str] = None
    tool_calls: Optional[List[Dict[str, Any]]] = None
    tool_call_id: Optional[str] = None
    # Base64 image data for vision-capable models. The core `Message` type has
    # carried this since the CLI's `nira ask --image` shipped, and
    # `messages_to_dicts` already forwards it to Ollama's `images` array — the
    # HTTP layer was the only missing link.
    images: Optional[List[str]] = None
    # Ids from POST /v1/chat/attachments. Ids rather than bytes: a 3 MB photo
    # is ~4 MB base64, and conversations are persisted in the browser's
    # ~5 MB localStorage.
    attachment_ids: Optional[List[str]] = None

    @model_validator(mode="before")
    @classmethod
    def _accept_openai_content_parts(cls, data: Any) -> Any:
        """Accept OpenAI-style ``content`` arrays, storing them in our shape.

        Every OpenAI-compatible vision client sends
        ``content: [{"type": "text"...}, {"type": "image_url"...}]``, and
        `content` here is a `str`, so all of them got a 422 — the endpoint
        advertises OpenAI compatibility and rejected the standard request.

        Normalising here rather than widening `content` to a union is what
        keeps this cheap: eight places read `.content` expecting a string, and
        a union would hand every one of them a list instead.
        """
        if not isinstance(data, dict):
            return data
        content = data.get("content")
        if not isinstance(content, list):
            return data

        texts: List[str] = []
        images: List[str] = list(data.get("images") or [])
        for part in content:
            if not isinstance(part, dict):
                # A bare string inside the array is not in the spec, but it
                # costs nothing to read it as text rather than 422.
                if isinstance(part, str):
                    texts.append(part)
                continue
            kind = part.get("type")
            if kind == "text":
                texts.append(str(part.get("text") or ""))
            elif kind in {"image_url", "input_image"}:
                url = part.get("image_url")
                if isinstance(url, dict):
                    url = url.get("url")
                url = url or part.get("image")
                if isinstance(url, str) and url:
                    # data:image/png;base64,AAAA... -> AAAA...
                    images.append(url.split(",", 1)[-1] if "," in url else url)

        data = dict(data)
        data["content"] = "\n\n".join(t for t in texts if t)
        if images:
            data["images"] = images
        return data


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[ChatMessage]
    temperature: float = 0.7
    max_tokens: int = 1024
    stream: bool = False
    tools: Optional[List[Dict[str, Any]]] = None
    # Whether to answer through the server's agent — tools, memory, and the
    # learning loop that records the outcome — or to go straight to the model.
    #
    # Until now this was inferred from whether the caller sent `tools`, which
    # meant there was no way to ask for a plain answer: an empty list is falsy,
    # so "no tools" and "don't use the agent" were the same request and both
    # got the agent. None keeps the old inference for existing callers.
    use_agent: Optional[bool] = None


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class UsageInfo(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class AudioMeta(BaseModel):
    url: str


class ChoiceMessage(BaseModel):
    role: str = "assistant"
    content: Optional[str] = ""
    tool_calls: Optional[List[Dict[str, Any]]] = None
    audio: Optional[AudioMeta] = None


class Choice(BaseModel):
    index: int = 0
    message: ChoiceMessage
    finish_reason: str = "stop"


class ComplexityInfo(BaseModel):
    score: float
    tier: str
    suggested_max_tokens: int


class ChatCompletionResponse(BaseModel):
    id: str = Field(default_factory=lambda: f"chatcmpl-{uuid.uuid4().hex[:12]}")
    object: str = "chat.completion"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: List[Choice] = Field(default_factory=list)
    usage: UsageInfo = Field(default_factory=UsageInfo)
    complexity: Optional[ComplexityInfo] = None


# ---------------------------------------------------------------------------
# Streaming chunk models
# ---------------------------------------------------------------------------


class DeltaMessage(BaseModel):
    role: Optional[str] = None
    content: Optional[str] = None
    # Streaming tool_calls (OpenAI delta shape, with `index`). Present only
    # on streamed raw function-calling responses (stream:true + tools).
    tool_calls: Optional[List[Dict[str, Any]]] = None


class StreamChoice(BaseModel):
    index: int = 0
    delta: DeltaMessage
    finish_reason: Optional[str] = None


class ChatCompletionChunk(BaseModel):
    id: str = ""
    object: str = "chat.completion.chunk"
    created: int = Field(default_factory=lambda: int(time.time()))
    model: str = ""
    choices: List[StreamChoice] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Models endpoint
# ---------------------------------------------------------------------------


class ModelObject(BaseModel):
    id: str
    object: str = "model"
    created: int = Field(default_factory=lambda: int(time.time()))
    owned_by: str = "nira"


class ModelListResponse(BaseModel):
    object: str = "list"
    data: List[ModelObject] = Field(default_factory=list)


__all__ = [
    "ChatCompletionChunk",
    "ChatCompletionRequest",
    "ChatCompletionResponse",
    "ChatMessage",
    "Choice",
    "ChoiceMessage",
    "ComplexityInfo",
    "DeltaMessage",
    "ModelListResponse",
    "ModelObject",
    "StreamChoice",
    "UsageInfo",
]
