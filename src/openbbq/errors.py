from __future__ import annotations


class OpenBBQError(Exception):
    def __init__(self, code: str, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.exit_code = exit_code

    def __str__(self) -> str:
        return f"{self.code}: {self.message}"


class ValidationError(OpenBBQError):
    def __init__(self, message: str, code: str = "validation_error", exit_code: int = 3) -> None:
        super().__init__(code, message, exit_code)


class PluginError(OpenBBQError):
    def __init__(self, message: str, code: str = "plugin_error", exit_code: int = 4) -> None:
        super().__init__(code, message, exit_code)


class ExecutionError(OpenBBQError):
    def __init__(self, message: str, code: str = "execution_error", exit_code: int = 5) -> None:
        super().__init__(code, message, exit_code)


class ArtifactNotFoundError(OpenBBQError):
    def __init__(self, message: str, code: str = "artifact_not_found", exit_code: int = 6) -> None:
        super().__init__(code, message, exit_code)
