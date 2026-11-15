# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""One answer shape for every refusal: ``{"error": …, "detail": …}``.

``error`` names the refusal in a word a client branches on, and ``detail`` says
it in a sentence for a person. The identity core's errors, FastAPI's own
refusals, the checks on a request and each component's errors all answer so.
An error nobody named is a 500, logged, with a detail that tells nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from fastapi.responses import JSONResponse
from pydantic import BaseModel

from oneberth.identity import (
    AuthenticationError,
    BearerRefusedError,
    BusyError,
    FreshSignInRequiredError,
    IdentityError,
    InvalidValueError,
    NotClaimedError,
    NotFoundError,
    PermissionDeniedError,
    SignInRefusedError,
    WrongNumberError,
)

log = logging.getLogger("oneberth.web")


class ErrorBody(BaseModel):
    """Every refusal, as the OpenAPI documents describe it."""

    error: str
    detail: str


@dataclass(frozen=True, slots=True)
class Refusal(Exception):
    """A request refused before it reaches a handler, or by oneberth's routes."""

    status: int
    error: str
    detail: str

    def __str__(self) -> str:
        return f"{self.status} {self.error}: {self.detail}"

    def answer(self, headers: Mapping[str, str] | None = None) -> JSONResponse:
        return JSONResponse(
            {"error": self.error, "detail": self.detail},
            status_code=self.status,
            headers=headers,
        )


IDENTITY_REFUSALS: dict[type[IdentityError], tuple[int, str]] = {
    AuthenticationError: (401, "Unauthorized"),
    FreshSignInRequiredError: (403, "FreshSignInRequired"),
    BearerRefusedError: (403, "BearerRefused"),
    PermissionDeniedError: (403, "Forbidden"),
    SignInRefusedError: (403, "Forbidden"),
    WrongNumberError: (403, "WrongNumber"),
    NotFoundError: (404, "NotFound"),
    NotClaimedError: (409, "Conflict"),
    InvalidValueError: (422, "InvalidValue"),
    BusyError: (429, "Busy"),
}
"""The status and the name each error of the identity core answers with."""

HTTP_ERRORS: dict[int, str] = {
    400: "BadRequest",
    401: "Unauthorized",
    403: "Forbidden",
    404: "NotFound",
    405: "MethodNotAllowed",
    409: "Conflict",
    413: "PayloadTooLarge",
    415: "UnsupportedMediaType",
    422: "InvalidRequest",
    429: "Busy",
    500: "InternalError",
    503: "Unavailable",
}
"""The names of the statuses a refusal without a name of its own has."""


def http_error_name(status: int) -> str:
    return HTTP_ERRORS.get(status, f"HTTP{status}")


def identity_refusal(error: IdentityError) -> Refusal:
    """The answer to an error of the identity core: its class's, or its
    nearest base's."""
    for cls in type(error).__mro__:
        found = IDENTITY_REFUSALS.get(cls)
        if found is not None:
            status, name = found
            return Refusal(status, name, str(error))
    return Refusal(500, "InternalError", "the server failed to answer")


ErrorBodyOf = Callable[[Exception], Mapping[str, Any]]


def default_error_body(error: Exception) -> Mapping[str, Any]:
    """An application's error as a body: its class's name, and its message."""
    return {"error": type(error).__name__, "detail": str(error)}


def status_in(errors: Mapping[type[Exception], int], error: Exception) -> int | None:
    """The status ``errors`` names for ``error``'s class or its nearest base."""
    for cls in type(error).__mro__:
        if cls in errors:
            return errors[cls]
    return None
