# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The configuration reader: what a file yields, and every refusal with its key."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from oneberth.config import (
    AppConfig,
    Config,
    ConfigError,
    ProviderConfig,
    load_config,
    normalise_issuer,
    normalise_origin,
    parse_config,
)
from oneberth.identity import (
    ONEBERTH_ROLES,
    GrantEntry,
    Match,
    Matcher,
    Policy,
    Registry,
)
from oneberth.identity.memory import MemoryIdentityStore

ENVIRON = {"OKTA_SECRET": "s3cret", "GOOGLE_SECRET": "g00gle"}

FULL = """
session_hours = 8
device_days = 7

[apps.robinauts]
public_url = "https://Robinauts.example.com:443/"

[apps.neorc]
public_url = "http://127.0.0.1:8420"

[providers.okta]
title = "Okta"
issuer = "https://example.okta.com/oauth2/default/"
client_id = "okta-client"
client_secret_env = "OKTA_SECRET"
scopes = ["openid", "email", "profile", "groups"]
groups_claim = "groups"

[providers.google]
issuer = "https://accounts.google.com"
client_id = "google-client"
client_secret_env = "GOOGLE_SECRET"

[[allow]]
provider = "okta"
group = "platform-users"

[[allow]]
provider = "google"
hosted_domain = "example.com"

[[grant]]
provider = "okta"
group = "platform-admins"
roles = ["robinauts/admin", "oneberth/admin"]
"""

OKTA = """
[providers.okta]
issuer = "https://example.okta.com"
client_id = "c"
client_secret_env = "OKTA_SECRET"

[providers.google]
issuer = "https://accounts.google.com"
client_id = "g"
client_secret_env = "GOOGLE_SECRET"
"""


def parsed(text: str) -> Config:
    return parse_config(tomllib.loads(text), ENVIRON)


def test_a_full_file_yields_the_values_the_core_takes() -> None:
    config = parsed(FULL)

    assert (config.session_hours, config.device_days) == (8.0, 7.0)
    assert config.apps == {
        "robinauts": AppConfig("robinauts", "https://robinauts.example.com"),
        "neorc": AppConfig("neorc", "http://127.0.0.1:8420"),
    }
    assert config.providers["okta"] == ProviderConfig(
        id="okta",
        title="Okta",
        issuer="https://example.okta.com/oauth2/default",
        client_id="okta-client",
        client_secret="s3cret",
        scopes=("openid", "email", "profile", "groups"),
        groups_claim="groups",
    )
    google = config.providers["google"]
    assert (google.title, google.scopes, google.is_google) == (
        "google",
        ("openid", "email", "profile"),
        True,
    )
    assert config.policy == Policy(
        allow=(
            Match("okta", Matcher.GROUP, "platform-users"),
            Match("google", Matcher.HOSTED_DOMAIN, "example.com"),
        ),
        grants=(
            GrantEntry(
                Match("okta", Matcher.GROUP, "platform-admins"),
                frozenset({"robinauts/admin", "oneberth/admin"}),
            ),
        ),
    )
    assert config.redirect_uri("robinauts", "okta") == (
        "https://robinauts.example.com/auth/callback/okta"
    )
    assert "s3cret" not in repr(config)


def test_an_empty_file_is_the_local_mode_with_the_default_lives() -> None:
    assert parsed("") == Config()


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("colour = 'blue'", "colour: unknown key"),
        ("session_hours = 0", "session_hours must be a number of hours over 0"),
        ("device_days = 'a month'", "device_days must be a number of days over 0"),
        ("session_hours = true", "session_hours must be a number of hours"),
        ("apps = 3", "apps: a table of tables"),
        ("[apps.Robin]\npublic_url = 'https://r.example.com'", "apps.Robin: an app"),
        ("[apps.r]\npublic_url = 'https://r.example.com/r'", "apps.r.public_url: "),
        ("[apps.r]\npublic_url = 'http://r.example.com'", "not loopback: use https"),
        ("[apps.r]\nurl = 'https://r.example.com'", "apps.r.url: unknown key"),
        ("[apps.r]", "apps.r.public_url: missing"),
        (OKTA + "[providers.okta.extra]", "providers.okta.extra: unknown key"),
        ("[providers.Okta]", "providers.Okta: an id is up to 40"),
        (
            "[providers.okta]\nissuer='https://o.example.com'\nclient_id='c'\n"
            "client_secret_env='MISSING'",
            "providers.okta.client_secret_env: $MISSING is not set",
        ),
        (
            "[providers.okta]\nissuer='ftp://o.example.com'\nclient_id='c'\n"
            "client_secret_env='OKTA_SECRET'",
            "providers.okta.issuer: 'ftp://o.example.com' is not an http",
        ),
        ("[providers.okta]\nissuer='https://o'", "providers.okta.client_id: missing"),
        (
            OKTA.replace('client_id = "c"', 'client_id = "c"\nscopes = ["email"]'),
            "providers.okta.scopes: must include 'openid'",
        ),
        (OKTA, "allow: no entry, so nobody could sign in"),
        (OKTA + "[[allow]]\nprovider = 'azure'\nemail = 'a@b.c'", "allow[1].provider"),
        (OKTA + "[[allow]]\nprovider = 'okta'", "allow[1]: exactly one of everyone"),
        (
            OKTA + "[[allow]]\nprovider = 'okta'\nemail = 'a@b.c'\ngroup = 'g'",
            "not email, group",
        ),
        (OKTA + "[[allow]]\nprovider = 'okta'\neveryone = 1", "allow[1].everyone"),
        (OKTA + "[[allow]]\nprovider = 'okta'\ngroup = ''", "allow[1].group: a non"),
        (OKTA + "[[allow]]\nprovider = 'okta'\nrole = 'x'", "allow[1].role: unknown"),
        (
            OKTA + "[[allow]]\nprovider = 'google'\neveryone = true",
            "allow[1].everyone: refused for Google",
        ),
        (
            OKTA + "[[allow]]\nprovider = 'google'\nemail_domain = 'example.com'",
            "allow[1].email_domain: refused for Google",
        ),
        (
            OKTA + "[[allow]]\nprovider = 'okta'\nhosted_domain = 'example.com'",
            "allow[1].hosted_domain: Google's hd claim",
        ),
        (
            OKTA + "[[allow]]\nprovider='okta'\ngroup='u'\n"
            "[[grant]]\nprovider='okta'\ngroup='a'",
            "grant[1].roles: an array of one role or more",
        ),
        (
            OKTA + "[[allow]]\nprovider='okta'\ngroup='u'\n"
            "[[grant]]\nprovider='okta'\ngroup='a'\nroles=['admin']",
            "grant[1].roles: 'admin' is not a role",
        ),
        (
            OKTA + "[[allow]]\nprovider='okta'\ngroup='u'\n"
            "[[grant]]\nprovider='google'\neveryone=true\nroles=['oneberth/admin']",
            "grant[1].everyone: refused for Google",
        ),
        ("allow = 'everyone'", "allow: an array of tables"),
    ],
)
def test_a_refusal_names_the_key(text: str, problem: str) -> None:
    with pytest.raises(ConfigError) as refused:
        parsed(text)

    assert any(problem in p for p in refused.value.problems), refused.value.problems


def test_every_problem_is_listed_at_once() -> None:
    with pytest.raises(ConfigError) as refused:
        parsed("colour = 1\nsession_hours = -1\n[apps.r]\n")

    assert len(refused.value.problems) == 3


def test_the_file_is_the_one_the_variable_names(tmp_path: Path) -> None:
    path = tmp_path / "oneberth.toml"
    path.write_text(FULL)

    config = load_config(environ={"ONEBERTH_CONFIG": str(path), **ENVIRON})

    assert config == parsed(FULL)
    with pytest.raises(ConfigError, match=r"\$ONEBERTH_CONFIG names no"):
        load_config(environ={})
    with pytest.raises(ConfigError, match="cannot be read"):
        load_config(tmp_path / "missing.toml", environ={})


def test_a_file_that_is_not_toml_is_refused_with_its_line(tmp_path: Path) -> None:
    path = tmp_path / "oneberth.toml"
    path.write_text("session_hours = 12\n\n[apps.r\n")

    with pytest.raises(ConfigError, match=r"oneberth\.toml: not TOML: .*line 3"):
        load_config(path, environ={})


def test_a_problem_in_a_file_names_the_file(tmp_path: Path) -> None:
    path = tmp_path / "oneberth.toml"
    path.write_text("colour = 1\n")

    with pytest.raises(ConfigError, match=r"oneberth\.toml: colour: unknown key"):
        load_config(path, environ={})


def test_a_backend_missing_from_apps_is_refused_by_name() -> None:
    with pytest.raises(ConfigError, match=r"apps\.neorc: missing"):
        Config().app("neorc")


def test_the_access_refuses_a_grant_of_a_role_nobody_registered() -> None:
    config = parsed(
        OKTA + "[[allow]]\nprovider='okta'\ngroup='u'\n"
        "[[grant]]\nprovider='okta'\ngroup='a'\nroles=['robinauts/admin']"
    )
    registry = Registry([ONEBERTH_ROLES])

    with pytest.raises(ConfigError, match="'robinauts/admin' is not a registered"):
        config.access(MemoryIdentityStore(), registry)
    access = parsed(FULL.split("[[grant]]")[0]).access(MemoryIdentityStore(), registry)
    assert access.session_life.total_seconds() == 8 * 3600


@pytest.mark.parametrize(
    ("url", "origin"),
    [
        ("https://Example.COM", "https://example.com"),
        ("https://example.com:443/", "https://example.com"),
        ("https://example.com:8443", "https://example.com:8443"),
        ("http://localhost:8000", "http://localhost:8000"),
        ("http://[::1]:80", "http://[::1]"),
        ("http://app.localhost", "http://app.localhost"),
    ],
)
def test_an_origin_has_one_form(url: str, origin: str) -> None:
    assert normalise_origin(url) == origin


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/app",
        "http://example.com",
        "https://user@example.com",
        "https://example.com?x=1",
        "https://",
        "example.com",
        "https://example.com:99999",
    ],
)
def test_what_is_not_an_origin_is_refused(url: str) -> None:
    with pytest.raises(ValueError):
        normalise_origin(url)


@pytest.mark.parametrize(
    ("url", "issuer"),
    [
        (
            "https://Example.okta.com/oauth2/default/",
            "https://example.okta.com/oauth2/default",
        ),
        ("https://accounts.google.com/", "https://accounts.google.com"),
    ],
)
def test_an_issuer_keeps_its_path(url: str, issuer: str) -> None:
    assert normalise_issuer(url) == issuer
