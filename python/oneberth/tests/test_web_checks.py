# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The pure parts of the web: the checks on a request, the cookies, the return
of a sign-in, the answer to each error of the core, and the QR code."""

from __future__ import annotations

import random

import pytest
from qrcodegen import QrCode as Reference  # type: ignore[import-untyped]
from qrcodegen import QrSegment

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
    WrongNumberError,
)
from oneberth.web import Cookies, bearer_of, check_request, qr_svg, safe_return_to
from oneberth.web._errors import identity_refusal
from oneberth.web._qr import Ecc, QrCode, QrTooLongError
from oneberth.web.testing import read_qr

URL = "https://app.example.com"
JSON = "application/json"


@pytest.mark.parametrize(
    ("method", "content_type", "body", "site", "origin", "bearer", "cookie", "refused"),
    [
        ("GET", None, False, None, None, False, False, None),
        ("GET", None, False, "cross-site", None, False, True, None),
        ("GET", None, False, None, None, True, True, "TwoCredentials"),
        ("HEAD", None, False, None, None, False, True, None),
        ("OPTIONS", "text/plain", True, "cross-site", None, False, False, None),
        ("POST", JSON, True, "same-origin", URL, False, True, None),
        ("POST", JSON, True, None, URL, False, True, None),
        ("POST", "application/json; charset=utf-8", True, None, URL, False, True, None),
        ("POST", "Application/JSON", True, None, URL, False, True, None),
        ("POST", JSON, True, "cross-site", URL, False, True, "CrossSite"),
        ("POST", JSON, True, "same-site", URL, False, True, "CrossSite"),
        ("POST", JSON, True, "Cross-Site", None, True, False, "CrossSite"),
        ("POST", "text/plain", True, None, URL, False, True, "UnsupportedMediaType"),
        ("POST", None, False, None, URL, False, True, "UnsupportedMediaType"),
        (
            "POST",
            "multipart/form-data",
            True,
            None,
            None,
            True,
            False,
            "UnsupportedMediaType",
        ),
        (
            "PUT",
            "application/jsonx",
            True,
            None,
            URL,
            False,
            True,
            "UnsupportedMediaType",
        ),
        ("POST", JSON, True, None, "https://evil.example", False, True, "CrossOrigin"),
        ("POST", JSON, True, None, None, False, True, "CrossOrigin"),
        ("POST", JSON, True, None, "null", False, True, "CrossOrigin"),
        ("POST", JSON, True, None, URL + ":444", False, True, "CrossOrigin"),
        ("POST", JSON, True, None, "https://evil.example", True, False, None),
        ("POST", JSON, True, None, None, False, False, None),
        ("DELETE", None, False, None, URL, False, True, None),
        (
            "DELETE",
            None,
            False,
            None,
            "https://evil.example",
            False,
            True,
            "CrossOrigin",
        ),
        ("DELETE", "text/plain", True, None, URL, False, True, "UnsupportedMediaType"),
        ("PATCH", JSON, True, None, URL, True, True, "TwoCredentials"),
    ],
)
def test_the_checks_on_a_request(
    method: str,
    content_type: str | None,
    body: bool,
    site: str | None,
    origin: str | None,
    bearer: bool,
    cookie: bool,
    refused: str | None,
) -> None:
    refusal = check_request(
        method,
        content_type=content_type,
        has_body=body,
        fetch_site=site,
        origin=origin,
        bearer=bearer,
        cookie=cookie,
        public_url=URL,
    )

    assert (refusal.error if refusal else None) == refused


@pytest.mark.parametrize(
    ("header", "secret"),
    [
        ("Bearer ob_pat_abc", "ob_pat_abc"),
        ("bearer  ob_pat_abc ", "ob_pat_abc"),
        ("Basic dXNlcjpwYXNz", None),
        ("Bearer", None),
        ("Bearer ", None),
        ("", None),
        (None, None),
    ],
)
def test_the_secret_of_a_bearer(header: str | None, secret: str | None) -> None:
    assert bearer_of(header) == secret


@pytest.mark.parametrize(
    ("public_url", "session", "login", "secure"),
    [
        (URL, "__Host-oneberth_session", "__Host-oneberth_login", True),
        (
            "https://127.0.0.1:8443",
            "__Host-oneberth_session",
            "__Host-oneberth_login",
            True,
        ),
        (
            "http://127.0.0.1:8420",
            "oneberth_session_8420",
            "oneberth_login_8420",
            False,
        ),
        ("http://localhost", "oneberth_session_80", "oneberth_login_80", False),
        ("http://[::1]:9000", "oneberth_session_9000", "oneberth_login_9000", False),
    ],
)
def test_the_cookies_of_an_origin(
    public_url: str, session: str, login: str, secure: bool
) -> None:
    assert Cookies.of(public_url) == Cookies(session, login, secure)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("/ui/#/notes/3", "/ui/#/notes/3"),
        ("/ui/?x=1#/account/tokens", "/ui/?x=1#/account/tokens"),
        ("/", "/"),
        (None, "/ui/"),
        ("", "/ui/"),
        ("https://evil.example/", "/ui/"),
        ("//evil.example/", "/ui/"),
        ("/\\evil.example", "/ui/"),
        ("ui/", "/ui/"),
        ("/ui/\nset-cookie", "/ui/"),
        ("/ui/ x", "/ui/"),
        ("/" + "a" * 2048, "/ui/"),
    ],
)
def test_where_a_sign_in_may_return(value: str | None, expected: str) -> None:
    assert safe_return_to(value) == expected


@pytest.mark.parametrize(
    ("error", "status", "name"),
    [
        (AuthenticationError("x"), 401, "Unauthorized"),
        (PermissionDeniedError("x"), 403, "Forbidden"),
        (BearerRefusedError("x"), 403, "BearerRefused"),
        (FreshSignInRequiredError("x"), 403, "FreshSignInRequired"),
        (WrongNumberError("x"), 403, "WrongNumber"),
        (NotFoundError("x"), 404, "NotFound"),
        (NotClaimedError("x"), 409, "Conflict"),
        (InvalidValueError("x"), 422, "InvalidValue"),
        (BusyError("x"), 429, "Busy"),
        (IdentityError("x"), 500, "InternalError"),
    ],
)
def test_each_error_of_the_core_answers_with_one_status(
    error: IdentityError, status: int, name: str
) -> None:
    refusal = identity_refusal(error)

    assert (refusal.status, refusal.error) == (status, name)


_LEVELS = {
    Ecc.LOW: Reference.Ecc.LOW,
    Ecc.MEDIUM: Reference.Ecc.MEDIUM,
    Ecc.QUARTILE: Reference.Ecc.QUARTILE,
    Ecc.HIGH: Reference.Ecc.HIGH,
}
_RANDOM = random.Random(18004)


@pytest.mark.parametrize("ecc", list(Ecc))
@pytest.mark.parametrize(
    "length", [0, 1, 17, 32, 78, 106, 134, 271, 367, 858, 1273, 2331]
)
def test_the_qr_code_is_the_reference_encoder_s_module_for_module(
    ecc: Ecc, length: int
) -> None:
    data = bytes(_RANDOM.randrange(256) for _ in range(length))
    try:
        expected = Reference.encode_segments([QrSegment.make_bytes(data)], _LEVELS[ecc])
    except Exception:
        with pytest.raises(QrTooLongError):
            QrCode(data, ecc)
        return

    ours = QrCode(data, ecc)

    assert (ours.version, ours.mask) == (expected.get_version(), expected.get_mask())
    assert ours.modules == [
        [expected.get_module(x, y) for x in range(expected.get_size())]
        for y in range(expected.get_size())
    ]


@pytest.mark.parametrize(
    "text",
    [
        "https://app.example.com/#/link?v=1&c=" + "A" * 43,
        "http://127.0.0.1:8420/#/link?v=1&c=xyz",
        "héllo, wörld",
        "x" * 400,
    ],
)
def test_the_qr_picture_reads_back_as_its_text(text: str) -> None:
    svg = qr_svg(text)

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "<script" not in svg and "href" not in svg
    assert read_qr(svg) == text
