class LLMValidationError(Exception):
    """Raised when a critical LLM response cannot be validated and the pipeline cannot meaningfully continue"""