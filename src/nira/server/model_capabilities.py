"""Model capability helpers shared by server model-selection routes."""

_EMBEDDING_MODEL_PREFIXES = (
    "all-minilm",
    "bge-",
    "bge_",
    "e5-",
    "e5_",
    "gte-",
    "gte_",
    "jina-embeddings",
    "nomic-bert",
    "sentence-transformers",
)


def is_embed_only_model(model_name: str) -> bool:
    """Return whether a model identifier denotes a non-chat embedder.

    Ollama does not expose capabilities through its model-list response, so
    model selection needs a conservative name-based guard.  Most embedding
    models contain ``embed``; the explicit prefixes cover common families
    such as MiniLM, BGE, E5, and GTE whose names do not.
    """
    name = (model_name or "").strip().lower()
    leaf = name.rsplit("/", 1)[-1].split(":", 1)[0]
    return (
        "embed" in leaf
        or "minilm" in leaf
        or leaf.startswith(_EMBEDDING_MODEL_PREFIXES)
    )


# Families that can see an image. Ollama does not report capabilities in its
# model list, so this is name-based like the embedder guard above — and for a
# sharper reason: Ollama accepts an `images` array on a *text-only* model,
# ignores it, and answers anyway. The model then describes an image it never
# received, fluently and wrongly, and nothing in the response says so. A
# refusal the user can read is the only honest option.
_VISION_MARKERS = (
    "vision",
    "llava",
    "bakllava",
    "moondream",
    "minicpm-v",
    "llama3.2-vision",
    "gemma3",
    "pixtral",
    "internvl",
    "cogvlm",
    "qwen-vl",
)


def is_vision_model(model_name: str) -> bool:
    """Whether *model_name* can read an attached image.

    Conservative in the direction that matters: an unknown model is treated as
    text-only, so the worst case is telling someone to switch models when they
    did not have to — not silently inventing a description of their chart.
    """
    name = (model_name or "").strip().lower()
    leaf = name.rsplit("/", 1)[-1]
    family = leaf.split(":", 1)[0]
    # The "-VL" suffix is the convention across the Qwen, InternVL and
    # DeepSeek vision lines — but it is not always hyphenated: the tag
    # Ollama ships is `qwen2.5vl`, not `qwen2.5-vl`. Matching on "-vl"
    # missed the single most likely model anyone here would install.
    if family.endswith("vl") or family.endswith("-vl"):
        return True
    return any(marker in leaf for marker in _VISION_MARKERS)


__all__ = ["is_embed_only_model", "is_vision_model"]
