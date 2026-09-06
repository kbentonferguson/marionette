"""Immutable device authority, independent of GUI selection."""
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class Grant:
    operation: str
    resource_id: str
    binding: str


@dataclass(frozen=True)
class RequestPrincipal:
    device_id: str
    endpoint_id: str
    grants_revision: int
    grants: Tuple[Grant, ...]
