"""A graceful parser for the pipeline's structured LLM outputs.

Every LLM call in the pipeline is prompted to return JSON in a fixed shape. The models below describe those shapes, and parse_llm_response validates
a raw LLM string against a model without raising on malformed output - it logs the problem and returns None so each caller can decide how to degrade.
"""

import json
import logging
from typing import Optional, Type, TypeVar

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

# Parsing Functionalities
T = TypeVar("T", bound=BaseModel)


def _strip_code_fences(raw: str) -> str:
    """Drop a wrapping markdown code fence if the model added one despite the prompt telling it not to"""

    text = raw.strip()
    if not text.startswith("```"):
        return text
    newline = text.find("\n")
    text = text[newline+1:] if newline != -1 else ""
    test = text.rstrip()
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


def parse_llm_response(raw, model: Type[T], context: str = "LLM response") -> Optional[T]:
    """Validate a raw LLM string against pydantic model.
    Returns the validated model instance, or None if the response is missing, not valid JSON or does not match the expected structure.
    """

    if not raw or not isinstance(raw, str):
        logger.error("%s: empty or non-string response (%s)", context, type(raw).__name__)
        return None

    try:
        data = json.loads(_strip_code_fences(raw))
    except (json.JSONDecodeError, ValueError) as ex:
        logger.error("%s: response was not valid JSON: %s", context, ex)
        return None

    try:
        return model.model_validate(data)
    except ValidationError as ex:
        logger.error("%s: response failed schema validation: %s", context, ex)
        return None
