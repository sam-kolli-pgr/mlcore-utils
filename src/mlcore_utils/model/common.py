from abc import ABC, abstractmethod
from typing import Any
from result import Result
from enum import Enum


class Http_Method(str, Enum):
    POST = "post"
    GET = "get"


class Blacklodge_Action_Status(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    PENDING = "pending"
    CANCELLED = "cancelled"
    NOT_YET_STARTED = "NOT_YET_STARTED"
    ACCEPTED = "accpeted"
    UNKNOWN = "unknown"


class MLCore_Secret(object):
    def __init__(self, secret_value: str):
        self._raw_value: str = secret_value

    def get_secret_value(self) -> str:
        """Get the secret value.

        Returns:
            The secret value.
        """
        return self._raw_value

    def __eq__(self, other: Any) -> bool:
        return (
            isinstance(other, self.__class__)
            and self.get_secret_value() == other.get_secret_value()
        )

    def __hash__(self) -> int:
        return hash(self.get_secret_value())

    def __str__(self) -> str:
        return str(self._display())

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._display()!r})"

    def _display(self) -> str:
        return "**********" if self.get_secret_value() else ""


class Secret_Getter(ABC):

    @abstractmethod
    def get_secret(self) -> Result[MLCore_Secret, str]:
        pass
