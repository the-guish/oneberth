# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The sign-in configuration of a deployment, in the file ``ONEBERTH_CONFIG`` names.

    session_hours = 12
    device_days = 30

    [apps.robinauts]
    public_url = "https://robinauts.example.com"

    [providers.okta]
    title = "Okta"
    issuer = "https://example.okta.com/oauth2/default"
    client_id = "..."
    client_secret_env = "ONEBERTH_OKTA_SECRET"
    scopes = ["openid", "email", "profile", "groups"]
    groups_claim = "groups"

    [[allow]]
    provider = "okta"
    group = "platform-users"

    [[grant]]
    provider = "okta"
    group = "platform-admins"
    roles = ["robinauts/admin", "oneberth/admin"]

Every backend of the deployment reads the same file, and finds its
``public_url`` under its own name. A secret is given as the name of the
environment variable that holds it. Unknown keys are errors. Every problem is
listed at once, each with the key it is about, or the line for a file that is
not TOML. URLs are normalised as they are read, so each has one form: the one
redirect URIs are built from, ``Origin`` is compared with, and an ID token's
``iss`` must match.

The reader uses the standard library alone.
"""

from __future__ import annotations

import ipaddress
import os
import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from oneberth.identity import (
    DEFAULT_DEVICE_DAYS,
    DEFAULT_SESSION_HOURS,
    REFUSED_FOR_GOOGLE,
    Access,
    Clock,
    GrantEntry,
    IdentityStore,
    InvalidValueError,
    Match,
    Matcher,
    Policy,
    Registry,
    is_role_name,
    system_clock,
)
from oneberth.identity._access import life
from oneberth.identity._roles import is_app_name

CONFIG_ENV = "ONEBERTH_CONFIG"
"""The environment variable that names the configuration file."""

GOOGLE_ISSUER = "https://accounts.google.com"

DEFAULT_SCOPES = ("openid", "email", "profile")

_PROVIDER_ID = re.compile(r"[a-z0-9][a-z0-9_-]{0,39}")
_DEFAULT_PORTS = {"http": 80, "https": 443}
_MATCHERS = {matcher.value: matcher for matcher in Matcher}
_TOP = {"session_hours", "device_days", "apps", "providers", "allow", "grant"}
_PROVIDER_KEYS = {
    "title",
    "issuer",
    "client_id",
    "client_secret_env",
    "scopes",
    "groups_claim",
}


class ConfigError(ValueError):
    """The configuration cannot be used. ``problems`` lists every one found."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__("invalid oneberth configuration:\n" + "\n".join(problems))


@dataclass(frozen=True, slots=True)
class ProviderConfig:
    """One OpenID Connect provider people sign in with."""

    id: str
    title: str
    issuer: str
    """Normalised: lower-case scheme and host, no default port, no trailing slash."""
    client_id: str
    client_secret: str = field(repr=False)
    """Read from the variable the file names. Out of the repr, so no log prints it."""
    scopes: tuple[str, ...] = DEFAULT_SCOPES
    groups_claim: str | None = None

    @property
    def is_google(self) -> bool:
        return self.issuer == GOOGLE_ISSUER


@dataclass(frozen=True, slots=True)
class AppConfig:
    """One application of the deployment, by the name its component has."""

    name: str
    public_url: str
    """The backend's origin, normalised: ``scheme://host[:port]``, no path."""

    @property
    def secure(self) -> bool:
        """Whether the public URL is ``https``."""
        return self.public_url.startswith("https://")


@dataclass(frozen=True, slots=True)
class Config:
    """The sign-in configuration of a deployment."""

    session_hours: float = DEFAULT_SESSION_HOURS
    device_days: float = DEFAULT_DEVICE_DAYS
    apps: Mapping[str, AppConfig] = field(default_factory=dict)
    providers: Mapping[str, ProviderConfig] = field(default_factory=dict)
    policy: Policy = field(default_factory=Policy)

    def app(self, name: str) -> AppConfig:
        """The application called ``name``; ``ConfigError`` when the file has none."""
        found = self.apps.get(name)
        if found is None:
            raise ConfigError([f"apps.{name}: missing; the backend of {name} needs it"])
        return found

    def redirect_uri(self, app: str, provider: str) -> str:
        """Where ``provider`` sends a browser back to ``app``; registered with it."""
        return f"{self.app(app).public_url}/auth/callback/{provider}"

    def access(
        self, store: IdentityStore, registry: Registry, *, clock: Clock = system_clock
    ) -> Access:
        """The ``Access`` this configuration describes, on ``store``.

        Raises ``ConfigError`` when a ``[[grant]]`` names a role the registry
        does not have, or one that is not for people.
        """
        try:
            return Access(
                store,
                registry,
                self.policy,
                clock=clock,
                session_hours=self.session_hours,
                device_days=self.device_days,
            )
        except InvalidValueError as error:
            raise ConfigError([str(error)]) from None


def load_config(
    path: str | os.PathLike[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Config:
    """Read the file at ``path``, or the one ``ONEBERTH_CONFIG`` names.

    Raises ``ConfigError`` listing every problem.
    """
    environ = os.environ if environ is None else environ
    if path is None:
        named = environ.get(CONFIG_ENV)
        if not named:
            raise ConfigError([f"${CONFIG_ENV} names no configuration file"])
        path = named
    shown = os.fspath(path)
    try:
        with Path(path).open("rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as error:
        raise ConfigError([f"{shown}: not TOML: {error}"]) from None
    except OSError as error:
        raise ConfigError([f"{shown}: cannot be read: {error.strerror}"]) from None
    try:
        return parse_config(data, environ)
    except ConfigError as error:
        raise ConfigError([f"{shown}: {p}" for p in error.problems]) from None


def parse_config(data: Mapping[str, Any], environ: Mapping[str, str]) -> Config:
    """The configuration from its TOML structure, with secrets from ``environ``."""
    problems: list[str] = []
    _unknown(data, _TOP, "", problems)
    session_hours = _life(
        data, "session_hours", "hours", DEFAULT_SESSION_HOURS, problems
    )
    device_days = _life(data, "device_days", "days", DEFAULT_DEVICE_DAYS, problems)

    apps: dict[str, AppConfig] = {}
    for name, table in _tables(data, "apps", problems).items():
        app = _app(name, table, problems)
        if app is not None:
            apps[name] = app

    raw_providers = _tables(data, "providers", problems)
    providers: dict[str, ProviderConfig] = {}
    for provider_id, table in raw_providers.items():
        provider = _provider(provider_id, table, environ, problems)
        if provider is not None:
            providers[provider_id] = provider

    allow: list[Match] = []
    for index, entry in enumerate(_array(data, "allow", problems), start=1):
        where = f"allow[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{where}: a table")
            continue
        _unknown(entry, {"provider", *_MATCHERS}, where, problems)
        match = _match(where, entry, raw_providers, problems)
        if match is not None:
            allow.append(match)

    grants: list[GrantEntry] = []
    for index, entry in enumerate(_array(data, "grant", problems), start=1):
        where = f"grant[{index}]"
        if not isinstance(entry, Mapping):
            problems.append(f"{where}: a table")
            continue
        _unknown(entry, {"provider", "roles", *_MATCHERS}, where, problems)
        match = _match(where, entry, raw_providers, problems)
        roles = _roles(where, entry, problems)
        if match is not None and roles:
            grants.append(GrantEntry(match, roles))

    if raw_providers and not allow and not any(p.startswith("allow") for p in problems):
        problems.append("allow: no entry, so nobody could sign in")
    if problems:
        raise ConfigError(problems)
    return Config(
        session_hours=session_hours,
        device_days=device_days,
        apps=apps,
        providers=providers,
        policy=Policy(allow=tuple(allow), grants=tuple(grants)),
    )


def _life(
    data: Mapping[str, Any], key: str, unit: str, default: float, problems: list[str]
) -> float:
    if key not in data:
        return default
    value = data[key]
    try:
        life(value, unit, key)
    except InvalidValueError as error:
        problems.append(f"{error}, not {value!r}")
        return default
    return float(value)


def _tables(
    data: Mapping[str, Any], key: str, problems: list[str]
) -> Mapping[str, Any]:
    value = data.get(key, {})
    if not isinstance(value, Mapping):
        problems.append(f"{key}: a table of tables, as [{key}.<name>]")
        return {}
    return value


def _array(data: Mapping[str, Any], key: str, problems: list[str]) -> list[Any]:
    value = data.get(key, [])
    if not isinstance(value, list):
        problems.append(f"{key}: an array of tables, as [[{key}]]")
        return []
    return value


def _app(name: str, table: object, problems: list[str]) -> AppConfig | None:
    where = f"apps.{name}"
    if not is_app_name(name):
        problems.append(
            f"{where}: an application name is lower-case letters, digits and -"
        )
        return None
    if not isinstance(table, Mapping):
        problems.append(f"{where}: a table")
        return None
    _unknown(table, {"public_url"}, where, problems)
    raw = _string(table, "public_url", where, problems)
    if not raw:
        return None
    try:
        return AppConfig(name, normalise_origin(raw))
    except ValueError as error:
        problems.append(f"{where}.public_url: {error}")
        return None


def _provider(
    provider_id: str, table: object, environ: Mapping[str, str], problems: list[str]
) -> ProviderConfig | None:
    where = f"providers.{provider_id}"
    if not _PROVIDER_ID.fullmatch(provider_id):
        problems.append(
            f"{where}: an id is up to 40 lower-case letters, digits, _ and -"
        )
        return None
    if not isinstance(table, Mapping):
        problems.append(f"{where}: a table")
        return None
    before = len(problems)
    _unknown(table, _PROVIDER_KEYS, where, problems)
    title = _string(table, "title", where, problems, default=provider_id)
    client_id = _string(table, "client_id", where, problems)
    issuer = ""
    raw_issuer = _string(table, "issuer", where, problems)
    if raw_issuer:
        try:
            issuer = normalise_issuer(raw_issuer)
        except ValueError as error:
            problems.append(f"{where}.issuer: {error}")
    secret = ""
    variable = _string(table, "client_secret_env", where, problems)
    if variable:
        secret = environ.get(variable, "")
        if not secret:
            problems.append(f"{where}.client_secret_env: ${variable} is not set")
    scopes = DEFAULT_SCOPES
    if "scopes" in table:
        raw = table["scopes"]
        if not (isinstance(raw, list) and all(isinstance(s, str) and s for s in raw)):
            problems.append(f"{where}.scopes: an array of scope names")
        elif "openid" not in raw:
            problems.append(f"{where}.scopes: must include 'openid'")
        else:
            scopes = tuple(raw)
    groups_claim = None
    if "groups_claim" in table:
        groups_claim = _string(table, "groups_claim", where, problems) or None
    if len(problems) > before:
        return None
    return ProviderConfig(
        id=provider_id,
        title=title,
        issuer=issuer,
        client_id=client_id,
        client_secret=secret,
        scopes=scopes,
        groups_claim=groups_claim,
    )


def _match(
    where: str,
    entry: Mapping[str, Any],
    declared: Mapping[str, Any],
    problems: list[str],
) -> Match | None:
    provider_id = entry.get("provider")
    if not isinstance(provider_id, str) or provider_id not in declared:
        problems.append(
            f"{where}.provider: {provider_id!r} is not one of the [providers]"
        )
        return None
    given = [name for name in _MATCHERS if name in entry]
    if len(given) != 1:
        problems.append(
            f"{where}: exactly one of {', '.join(_MATCHERS)}, not "
            + (", ".join(given) or "none")
        )
        return None
    (name,) = given
    matcher = _MATCHERS[name]
    raw = entry[name]
    value: str | None = None
    if matcher is Matcher.EVERYONE:
        if raw is not True:
            problems.append(f"{where}.everyone: true, or no everyone at all")
            return None
    elif not isinstance(raw, str) or not raw:
        problems.append(f"{where}.{name}: a non-empty string")
        return None
    else:
        value = raw
    # From the provider's own table, so the rule holds even when the provider
    # has problems of its own.
    table = declared[provider_id]
    google = _is_google(table.get("issuer") if isinstance(table, Mapping) else None)
    if google and matcher in REFUSED_FOR_GOOGLE:
        problems.append(
            f"{where}.{name}: refused for Google, where anybody may open an account "
            "and verify an address at any domain: use hosted_domain for a "
            "Workspace, or email for one person"
        )
        return None
    if matcher is Matcher.HOSTED_DOMAIN and not google:
        problems.append(
            f"{where}.hosted_domain: Google's hd claim, which no other provider "
            f"sends: use group or email for {provider_id!r}"
        )
        return None
    return Match(provider_id, matcher, value)


def _roles(where: str, entry: Mapping[str, Any], problems: list[str]) -> frozenset[str]:
    raw = entry.get("roles")
    if not isinstance(raw, list) or not raw or not all(isinstance(r, str) for r in raw):
        problems.append(f"{where}.roles: an array of one role or more")
        return frozenset()
    misspelt = [r for r in raw if not is_role_name(r)]
    if misspelt:
        named = ", ".join(map(repr, misspelt))
        problems.append(f"{where}.roles: {named} is not a role: <app>/<name>")
        return frozenset()
    return frozenset(raw)


def _is_google(issuer: object) -> bool:
    try:
        return isinstance(issuer, str) and normalise_issuer(issuer) == GOOGLE_ISSUER
    except ValueError:
        return False


def _unknown(
    table: Mapping[str, object], known: set[str], where: str, problems: list[str]
) -> None:
    for key in table:
        if key not in known:
            problems.append(
                f"{where}.{key}: unknown key" if where else f"{key}: unknown key"
            )


def _string(
    table: Mapping[str, object],
    key: str,
    where: str,
    problems: list[str],
    *,
    default: str | None = None,
) -> str:
    value = table.get(key, default)
    if not isinstance(value, str) or not value:
        problems.append(f"{where}.{key}: missing, or not a non-empty string")
        return ""
    return value


def normalise_origin(url: str) -> str:
    """``url`` as a browser's ``Origin``; ``ValueError`` unless it is one.

    ``http`` only for a loopback host. A backend is served at the root of its
    origin, so a path is refused.
    """
    scheme, host, port, path = _split(url)
    if path not in ("", "/"):
        raise ValueError(f"{url!r} has a path: a backend is served at the root")
    return _joined(scheme, host, port)


def normalise_issuer(url: str) -> str:
    """An issuer in one form: its path kept, without a trailing slash."""
    scheme, host, port, path = _split(url)
    return _joined(scheme, host, port) + path.rstrip("/")


def _split(url: str) -> tuple[str, str, int | None, str]:
    parts = urlsplit(url.strip())
    scheme = parts.scheme.lower()
    if scheme not in _DEFAULT_PORTS:
        raise ValueError(f"{url!r} is not an http or https URL")
    if parts.username or parts.password or parts.query or parts.fragment:
        raise ValueError(f"{url!r} holds more than a scheme, host, port and path")
    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError(f"{url!r} has no host")
    try:
        port = parts.port
    except ValueError:
        raise ValueError(f"{url!r} has a port that is not one") from None
    if scheme == "http" and not is_loopback(host):
        raise ValueError(f"{url!r} is http on a host that is not loopback: use https")
    return scheme, host, port, parts.path


def _joined(scheme: str, host: str, port: int | None) -> str:
    shown = f"[{host}]" if ":" in host else host
    if port is None or port == _DEFAULT_PORTS[scheme]:
        return f"{scheme}://{shown}"
    return f"{scheme}://{shown}:{port}"


def is_loopback(host: str) -> bool:
    """Whether ``host`` names this machine: ``localhost``, or a loopback address."""
    host = host.strip("[]").lower()
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False
