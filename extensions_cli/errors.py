from __future__ import annotations


class ExtensionsError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message
