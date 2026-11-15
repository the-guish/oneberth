# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The secrets oneberth hands out, and what the store keeps of them.

Every secret is 256 random bits. The store keeps its SHA-256 and finds it by
that hash. A secret is never chosen by a person, so a plain hash makes a stolen
table useless, and a lookup by hash needs no comparison in constant time.

A credential's secret starts with a prefix that names its kind. The prefix
picks where a bearer is looked up, and lets a secret scanner recognise ours.
"""

from __future__ import annotations

import hashlib
import secrets
from enum import StrEnum

SECRET_BYTES = 32
"""256 bits."""

MAX_SECRET_LENGTH = 256
"""Longer than any secret oneberth makes. A longer one is not looked up."""


class CredentialKind(StrEnum):
    """The four kinds of credential."""

    SESSION = "session"
    """A browser's sign-in. Sent as a cookie, or forwarded as a bearer."""
    PERSONAL_TOKEN = "personal_token"
    """A person's token for their scripts. Sent as a bearer."""
    DEVICE = "device"
    """A linked phone. Sent as a bearer."""
    SERVICE_TOKEN = "service_token"
    """A program's token, bound to one role. Sent as a bearer."""


PREFIXES: dict[CredentialKind, str] = {
    CredentialKind.SESSION: "ob_ses_",
    CredentialKind.PERSONAL_TOKEN: "ob_pat_",
    CredentialKind.DEVICE: "ob_dev_",
    CredentialKind.SERVICE_TOKEN: "ob_svc_",
}


def random_secret() -> str:
    """256 random bits, URL-safe, with no prefix: a state, a nonce or a code."""
    return secrets.token_urlsafe(SECRET_BYTES)


def new_secret(kind: CredentialKind) -> str:
    """A new secret of ``kind``, its prefix first."""
    return PREFIXES[kind] + random_secret()


def kind_of(secret: str) -> CredentialKind | None:
    """The kind a secret's prefix names, or ``None`` for one oneberth did not make."""
    if len(secret) > MAX_SECRET_LENGTH:
        return None
    for kind, prefix in PREFIXES.items():
        if secret.startswith(prefix) and len(secret) > len(prefix):
            return kind
    return None


def secret_hash(secret: str) -> str:
    """The SHA-256 hex of the whole secret, its prefix included."""
    return hashlib.sha256(secret.encode("utf-8", "surrogatepass")).hexdigest()
