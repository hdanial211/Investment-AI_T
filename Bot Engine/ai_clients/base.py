"""Shared provider primitives for cloud AI clients."""


class AIProviderError(Exception):
    """Raised when a provider cannot return a usable completion."""

    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable
