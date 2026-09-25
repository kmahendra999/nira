"""Turning a user's file into text a model can read.

One implementation, two callers: the RAG upload path
(``nira.server.upload_router``) and chat attachments. They were about to be
two, which is how the ``.docx`` extractor ended up depending on an undeclared
import that 500s on a clean install — a bug worth having exactly once.
"""

from nira.documents.extract import (
    SUPPORTED_TEXT_EXTENSIONS,
    ExtractionError,
    ExtractionResult,
    extract_text,
    is_image,
)

__all__ = [
    "ExtractionError",
    "ExtractionResult",
    "SUPPORTED_TEXT_EXTENSIONS",
    "extract_text",
    "is_image",
]
