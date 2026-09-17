class CodePreflightError(Exception):
    """Expected engine failure with a stable error code."""

    def __init__(self, code: str, message: str, *, recoverable: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.recoverable = recoverable
