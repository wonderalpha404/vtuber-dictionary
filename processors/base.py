from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Outcome:
    state: str
    record: dict[str, Any]


class Processor(ABC):
    name: str
    upstream: str | None

    @abstractmethod
    def process(self, record: dict[str, Any]) -> Outcome:
        """Process one normalized record and return ok/ng/error."""
        raise NotImplementedError
