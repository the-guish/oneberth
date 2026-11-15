# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""The identity core's flows, on the memory store, with a clock moved by hand."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from oneberth.identity import (
    LOCAL_PROVIDER,
    ONEBERTH_ROLES,
    OPERATOR,
    TOKENS_MANAGE,
    Access,
    AuthenticationError,
    BearerRefusedError,
    BusyError,
    CredentialKind,
    DeviceDescription,
    FreshSignInRequiredError,
    Grant,
    GrantEntry,
    Identity,
    InvalidValueError,
    Match,
    Matcher,
    NotClaimedError,
    NotFoundError,
    PairingState,
    PermissionDeniedError,
    Policy,
    Principal,
    Registry,
    Role,
    RoleTable,
    SignInRefusedError,
    WrongNumberError,
    is_fresh,
    is_service_name,
    is_token_name,
    typed_number,
)
from oneberth.identity.memory import MemoryIdentityStore
from oneberth.identity.testing import ManualClock

NEORC = RoleTable(
    app="neorc",
    permissions=frozenset({"neorc/runs:start", "neorc/tasks:claim"}),
    roles=(
        Role("neorc/user", frozenset({"neorc/runs:start"}), people=True),
        Role("neorc/worker", frozenset({"neorc/tasks:claim"}), resource="queue"),
    ),
    default="neorc/user",
)
POLICY = Policy(
    allow=(Match("okta", Matcher.GROUP, "users"),),
    grants=(
        GrantEntry(
            Match("okta", Matcher.GROUP, "admins"), frozenset({"oneberth/admin"})
        ),
    ),
)
ADA = Identity("okta", "ada", name="Ada", groups=frozenset({"users", "admins"}))
BOB = Identity("okta", "bob", email="bob@example.com", groups=frozenset({"users"}))
PHONE = DeviceDescription("Pixel", "android")
MINUTE = timedelta(minutes=1)


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
async def store() -> MemoryIdentityStore:
    store = MemoryIdentityStore()
    await store.setup()
    return store


@pytest.fixture
def access(store: MemoryIdentityStore, clock: ManualClock) -> Access:
    return new_access(store, clock)


def new_access(
    store: MemoryIdentityStore, clock: ManualClock, policy: Policy = POLICY
) -> Access:
    return Access(store, Registry([ONEBERTH_ROLES, NEORC]), policy, clock=clock)


async def browser(access: Access, identity: Identity = ADA) -> Principal:
    """A signed-in browser, as its cookie authenticates."""
    signed_in = await access.sign_in(identity)
    return await access.authenticate(signed_in.secret, bearer=False)


# Signing in.


async def test_a_sign_in_through_a_provider(access: Access, clock: ManualClock) -> None:
    state, pending = await access.begin_sign_in("okta", return_to="/#/neorc")
    taken = await access.take_sign_in("okta", state)
    signed_in = await access.sign_in(ADA)
    principal = await access.authenticate(signed_in.secret, bearer=False)

    assert taken == pending
    assert (pending.return_to, len(pending.verifier)) == ("/#/neorc", 64)
    assert pending.expires_at == clock.now + timedelta(minutes=10)
    assert signed_in.secret.startswith("ob_ses_")
    assert signed_in.session.expires_at == clock.now + timedelta(hours=12)
    assert principal.user == signed_in.user
    assert principal.roles == {"neorc/user", "oneberth/admin"}
    assert principal.is_browser_session and principal.name == "Ada"
    with pytest.raises(AuthenticationError, match="used already"):
        await access.take_sign_in("okta", state)


async def test_a_sign_in_is_taken_by_its_own_provider_within_ten_minutes(
    access: Access, clock: ManualClock
) -> None:
    first, _ = await access.begin_sign_in("okta")
    second, _ = await access.begin_sign_in("okta")

    with pytest.raises(AuthenticationError, match="another provider"):
        await access.take_sign_in("google", first)
    clock.advance(timedelta(minutes=10))
    with pytest.raises(AuthenticationError, match="expired"):
        await access.take_sign_in("okta", second)
    with pytest.raises(AuthenticationError):
        await access.take_sign_in("okta", "")


async def test_too_many_sign_ins_in_progress_are_refused(
    store: MemoryIdentityStore, clock: ManualClock
) -> None:
    access = Access(store, Registry(), clock=clock, max_pending_sign_ins=1)
    await access.begin_sign_in("okta")

    with pytest.raises(BusyError):
        await access.begin_sign_in("okta")
    clock.advance(timedelta(minutes=10))
    await access.begin_sign_in("okta")


async def test_a_later_sign_in_refreshes_the_user(access: Access) -> None:
    first = await access.sign_in(ADA)
    later = await access.sign_in(
        Identity("okta", "ada", name="Ada King", groups=frozenset({"users"}))
    )

    assert later.user.id == first.user.id
    assert later.user.name == "Ada King"
    assert later.principal.roles == {"neorc/user"}


async def test_a_refused_sign_in_ends_every_credential_of_that_identity(
    access: Access,
) -> None:
    session = await access.sign_in(ADA)
    phone = await browser(access)
    secret, _ = await access.mint_personal_token(phone, "ci")

    with pytest.raises(SignInRefusedError, match="'ada'"):
        await access.sign_in(Identity("okta", "ada", groups=frozenset({"admins"})))
    for stale in (session.secret, secret):
        with pytest.raises(AuthenticationError):
            await access.authenticate(stale, bearer=True)


async def test_no_provider_signs_anyone_in_as_the_local_user(access: Access) -> None:
    with pytest.raises(InvalidValueError, match="!local"):
        await access.sign_in(Identity(LOCAL_PROVIDER, "me"))


async def test_a_session_lasts_its_hours_and_ends_at_sign_out(
    access: Access, clock: ManualClock
) -> None:
    kept = await access.sign_in(ADA)
    ended = await access.sign_in(ADA)

    await access.sign_out(await access.authenticate(ended.secret, bearer=False))
    clock.advance(timedelta(hours=12) - timedelta(seconds=1))
    await access.authenticate(kept.secret, bearer=False)
    clock.advance(timedelta(seconds=1))

    for secret in (ended.secret, kept.secret):
        with pytest.raises(AuthenticationError, match="session is unknown"):
            await access.authenticate(secret, bearer=False)


async def test_a_forwarded_session_is_a_bearer_and_ends_nothing(access: Access) -> None:
    signed_in = await access.sign_in(ADA)
    forwarded = await access.authenticate(signed_in.secret, bearer=True)

    await access.sign_out(forwarded)

    assert forwarded.bearer and not forwarded.is_browser_session
    await access.authenticate(signed_in.secret, bearer=False)
    with pytest.raises(BearerRefusedError):
        await access.mint_personal_token(forwarded, "ci")


async def test_a_cookie_holds_a_session_alone(access: Access) -> None:
    secret, _ = await access.mint_personal_token(await browser(access), "ci")

    with pytest.raises(AuthenticationError, match="session alone"):
        await access.authenticate(secret, bearer=False)
    with pytest.raises(AuthenticationError, match="not one oneberth issues"):
        await access.authenticate("neorc_abc", bearer=True)


# The allow list at every use.


async def test_a_person_taken_out_of_the_allow_list_loses_every_credential(
    store: MemoryIdentityStore, clock: ManualClock
) -> None:
    before = new_access(store, clock)
    session = await before.sign_in(BOB)
    token, _ = await before.mint_personal_token(await browser(before, BOB), "ci")
    # The backend restarts with an allow list that no longer names Bob.
    after = new_access(
        store, clock, Policy(allow=(Match("okta", Matcher.SUBJECT, "ada"),))
    )

    with pytest.raises(AuthenticationError, match="no longer admits"):
        await after.authenticate(token, bearer=True)
    # Back on the list: nothing revives.
    for secret in (session.secret, token):
        with pytest.raises(AuthenticationError, match="unknown"):
            await before.authenticate(secret, bearer=True)


async def test_the_roles_are_checked_again_once_a_minute(
    store: MemoryIdentityStore, clock: ManualClock
) -> None:
    here = new_access(store, clock)
    there = new_access(store, clock)
    session = await here.sign_in(ADA)
    # Another backend signs Ada in after she left the admins' group.
    await there.sign_in(Identity("okta", "ada", groups=frozenset({"users"})))

    clock.advance(MINUTE - timedelta(seconds=1))
    believed = await here.authenticate(session.secret, bearer=False)
    clock.advance(timedelta(seconds=1))
    checked = await here.authenticate(session.secret, bearer=False)

    assert "oneberth/admin" in believed.roles
    assert checked.roles == {"neorc/user"}


# Personal tokens.


async def test_a_personal_token_is_minted_from_a_fresh_browser_session(
    access: Access, clock: ManualClock
) -> None:
    session = await browser(access)
    secret, token = await access.mint_personal_token(session, "laptop")
    principal = await access.authenticate(secret, bearer=True)
    clock.advance(timedelta(minutes=10))

    assert secret.startswith("ob_pat_")
    assert token.expires_at == token.created_at + timedelta(days=90)
    assert principal.kind is CredentialKind.PERSONAL_TOKEN
    assert principal.roles == session.roles
    assert await access.personal_tokens(principal) == [token]
    with pytest.raises(FreshSignInRequiredError):
        await access.mint_personal_token(session, "late")
    with pytest.raises(BearerRefusedError):
        await access.mint_personal_token(principal, "from a token")
    with pytest.raises(InvalidValueError):
        await access.mint_personal_token(await browser(access), "")


async def test_a_personal_token_is_revoked_from_its_owner_browser(
    access: Access, clock: ManualClock
) -> None:
    ada = await browser(access)
    secret, token = await access.mint_personal_token(ada, "ci")
    as_token = await access.authenticate(secret, bearer=True)

    with pytest.raises(BearerRefusedError):
        await access.revoke_personal_token(as_token, token.id)
    with pytest.raises(NotFoundError):
        await access.revoke_personal_token(await browser(access, BOB), token.id)
    # Revoking needs no fresh session.
    clock.advance(timedelta(hours=1))
    await access.revoke_personal_token(ada, token.id)

    with pytest.raises(AuthenticationError):
        await access.authenticate(secret, bearer=True)


async def test_a_personal_token_lasts_ninety_days(
    access: Access, clock: ManualClock
) -> None:
    secret, _ = await access.mint_personal_token(await browser(access), "ci")

    clock.advance(timedelta(days=90) - timedelta(seconds=1))
    await access.authenticate(secret, bearer=True)
    clock.advance(timedelta(seconds=1))
    with pytest.raises(AuthenticationError):
        await access.authenticate(secret, bearer=True)


# Device pairing.


async def test_a_phone_is_linked_and_removed(
    access: Access, clock: ManualClock
) -> None:
    ada = await browser(access)
    code, pairing = await access.begin_pairing(ada)

    claimed = await access.claim_pairing(code, PHONE)
    with pytest.raises(NotFoundError):
        await access.claim_pairing(code, PHONE)
    waiting_phone = await access.pairing_state(claimed.secret)
    with pytest.raises(AuthenticationError):
        await access.authenticate(claimed.secret, bearer=True)
    seen = await access.pairing(ada, pairing.id)
    wrong = "000000" if claimed.number != "000000" else "111111"
    with pytest.raises(WrongNumberError):
        await access.approve_pairing(ada, pairing.id, wrong)
    # Approving is a step of the same pairing: no fresh session is needed.
    clock.advance(timedelta(seconds=90))
    number = f"{claimed.number[:3]} {claimed.number[3:]}"
    device = await access.approve_pairing(ada, pairing.id, number)
    phone = await access.authenticate(claimed.secret, bearer=True)

    assert claimed.secret.startswith("ob_dev_") and len(claimed.number) == 6
    assert waiting_phone is PairingState.CLAIMED
    assert seen.state is PairingState.CLAIMED and seen.device == PHONE
    assert await access.pairing_state(claimed.secret) is None
    assert device.expires_at == clock.now + timedelta(days=30)
    assert phone.kind is CredentialKind.DEVICE and phone.roles == ada.roles
    assert await access.devices(phone) == [device]
    assert access.require_device(phone) == device
    with pytest.raises(PermissionDeniedError, match="linked device"):
        access.require_device(ada)
    with pytest.raises(BearerRefusedError):
        await access.remove_device(phone, device.id)

    await access.remove_device(ada, device.id)
    with pytest.raises(AuthenticationError):
        await access.authenticate(claimed.secret, bearer=True)


async def test_a_device_signs_itself_out(access: Access) -> None:
    ada = await browser(access)
    code, pairing = await access.begin_pairing(ada)
    claimed = await access.claim_pairing(code, PHONE)
    await access.approve_pairing(ada, pairing.id, claimed.number)

    await access.sign_out(await access.authenticate(claimed.secret, bearer=True))

    assert await access.devices(ada) == []


async def test_a_code_works_once_within_two_minutes(
    access: Access, clock: ManualClock
) -> None:
    ada = await browser(access)
    code, pairing = await access.begin_pairing(ada)

    with pytest.raises(NotClaimedError):
        await access.approve_pairing(ada, pairing.id, "123456")
    clock.advance(timedelta(minutes=2))
    with pytest.raises(NotFoundError):
        await access.claim_pairing(code, PHONE)
    with pytest.raises(NotFoundError):
        await access.pairing(ada, pairing.id)


async def test_pairings_are_minted_from_a_fresh_session_three_at_a_time(
    access: Access, clock: ManualClock
) -> None:
    ada = await browser(access)
    pairings = [(await access.begin_pairing(ada))[1] for _ in range(3)]

    with pytest.raises(BusyError):
        await access.begin_pairing(ada)
    with pytest.raises(NotFoundError):
        await access.refuse_pairing(await browser(access, BOB), pairings[0].id)
    await access.refuse_pairing(ada, pairings[0].id)
    await access.begin_pairing(ada)
    clock.advance(timedelta(minutes=10))
    with pytest.raises(FreshSignInRequiredError):
        await access.begin_pairing(ada)


async def test_three_wrong_numbers_end_a_pairing(access: Access) -> None:
    ada = await browser(access)
    code, pairing = await access.begin_pairing(ada)
    await access.claim_pairing(code, PHONE)

    for _ in range(2):
        with pytest.raises(WrongNumberError):
            await access.approve_pairing(ada, pairing.id, "not a number")
    with pytest.raises(NotFoundError):
        await access.approve_pairing(ada, pairing.id, "12")


# Service tokens.


async def test_the_operator_makes_a_worker_token_bound_to_one_queue(
    access: Access, clock: ManualClock
) -> None:
    secret, token = await access.create_service_token(
        "worker-gpu", "neorc/worker", resource="python-gpu", by=OPERATOR
    )
    worker = await access.authenticate(secret, bearer=True)

    assert secret.startswith("ob_svc_")
    assert (token.grant, token.expires_at) == (
        Grant("neorc/worker", "python-gpu"),
        None,
    )
    assert worker.is_service and worker.name == "worker-gpu"
    access.authorize(worker, "neorc/tasks:claim", "python-gpu")
    for permission, resource in (
        ("neorc/tasks:claim", "default"),
        ("neorc/runs:start", None),
    ):
        with pytest.raises(PermissionDeniedError):
            access.authorize(worker, permission, resource)
    with pytest.raises(PermissionDeniedError, match="no personal credentials"):
        await access.personal_tokens(worker)
    assert access.bound_resource(worker, "neorc/tasks:claim") == "python-gpu"
    with pytest.raises(PermissionDeniedError):
        access.bound_resource(worker, "neorc/runs:start")
    assert access.bound_resource(await browser(access), "neorc/runs:start") is None


async def test_a_service_token_is_minted_by_a_holder_of_tokens_manage(
    access: Access, clock: ManualClock
) -> None:
    admin = await browser(access)
    person = await browser(access, BOB)
    launcher_secret, _ = await access.create_service_token(
        "launcher", "oneberth/launcher", expires_in=timedelta(hours=1), by=OPERATOR
    )
    launcher = await access.authenticate(launcher_secret, bearer=True)

    _, by_admin = await access.create_service_token("ci", "neorc/user", by=admin)
    _, by_launcher = await access.create_service_token(
        "w1", "neorc/worker", resource="q", by=launcher
    )
    with pytest.raises(PermissionDeniedError, match="tokens"):
        await access.create_service_token("x", "neorc/user", by=person)
    with pytest.raises(PermissionDeniedError):
        await access.service_tokens(by=person)

    assert access.allows(admin, TOKENS_MANAGE)
    names = [t.name for t in await access.service_tokens(by=launcher)]
    assert names == ["ci", "launcher", "w1"]
    await access.revoke_service_token(by_admin.id, by=admin)
    with pytest.raises(NotFoundError):
        await access.revoke_service_token(by_admin.id, by=admin)
    clock.advance(timedelta(hours=1))
    with pytest.raises(AuthenticationError, match="service token"):
        await access.authenticate(launcher_secret, bearer=True)
    assert by_launcher.grant == Grant("neorc/worker", "q")


@pytest.mark.parametrize(
    ("name", "role", "resource", "expires_in", "problem"),
    [
        ("w", "neorc/worker", None, None, "needs a queue"),
        ("w", "neorc/user", "q", None, "every resource"),
        ("w", "neorc/admin", None, None, "not a registered role"),
        ("bad name", "neorc/user", None, None, "not a service token name"),
        ("w", "neorc/user", None, timedelta(0), "life"),
        ("w", "neorc/user", None, timedelta(days=5 * 366 + 1), "life"),
        ("taken", "neorc/user", None, None, "exists"),
    ],
)
async def test_a_service_token_refused(
    access: Access,
    name: str,
    role: str,
    resource: str | None,
    expires_in: timedelta | None,
    problem: str,
) -> None:
    await access.create_service_token("taken", "neorc/user", by=OPERATOR)

    with pytest.raises(InvalidValueError, match=problem):
        await access.create_service_token(
            name, role, resource=resource, expires_in=expires_in, by=OPERATOR
        )


# The sweep, and the settings.


async def test_a_sign_in_begun_sweeps_expired_rows_once_a_minute(
    store: MemoryIdentityStore, access: Access, clock: ManualClock
) -> None:
    await access.sign_in(ADA)
    await access.begin_sign_in("okta")
    clock.advance(timedelta(hours=12))
    # Sweeps the session and the first sign-in in progress.
    await access.begin_sign_in("okta")
    swept = await store.delete_expired(clock.now)
    clock.advance(timedelta(minutes=9, seconds=30))
    await access.begin_sign_in("okta")
    clock.advance(timedelta(seconds=40))
    # Within a minute of the last sweep: the sign-in begun 10:10 ago stays.
    await access.begin_sign_in("okta")
    left = await store.delete_expired(clock.now)

    assert (swept, left) == (0, 1)
    assert await access.sweep() == 0


@pytest.mark.parametrize(
    ("settings", "problem"),
    [
        ({"session_hours": 0}, "session_hours"),
        ({"session_hours": float("nan")}, "session_hours"),
        ({"device_days": -1}, "device_days"),
        ({"device_days": True}, "device_days"),
        ({"max_pending_sign_ins": 0}, "at least one"),
    ],
)
def test_settings_out_of_bounds_are_refused(
    store: MemoryIdentityStore, settings: dict[str, float], problem: str
) -> None:
    with pytest.raises(InvalidValueError, match=problem):
        Access(store, Registry(), **settings)  # type: ignore[arg-type]


def test_a_policy_with_an_unknown_role_is_refused(store: MemoryIdentityStore) -> None:
    policy = Policy(
        allow=(Match("okta", Matcher.EVERYONE),),
        grants=(GrantEntry(Match("okta", Matcher.EVERYONE), frozenset({"neorc/x"})),),
    )

    with pytest.raises(InvalidValueError, match="neorc/x"):
        Access(store, Registry([NEORC]), policy)


# Pure rules of the flows.


@pytest.mark.parametrize(
    ("text", "service", "token"),
    [
        ("worker-gpu.1", True, True),
        ("ci", True, True),
        ("my laptop", False, True),
        ("-ci", False, True),
        ("", False, False),
        ("   ", False, False),
        ("a" * 100, True, True),
        ("a" * 101, False, False),
        ("tab\there", False, False),
    ],
)
def test_names_of_tokens(text: str, service: bool, token: bool) -> None:
    assert (is_service_name(text), is_token_name(text)) == (service, token)


T = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.parametrize(
    ("age", "expected"),
    [
        (timedelta(0), True),
        (timedelta(minutes=9, seconds=59), True),
        (timedelta(minutes=10), False),
        (timedelta(hours=2), False),
        (timedelta(seconds=-1), False),
    ],
)
def test_a_fresh_session(age: timedelta, expected: bool) -> None:
    assert is_fresh(T, T + age) is expected


@pytest.mark.parametrize(
    ("typed", "expected"),
    [
        ("123456", "123456"),
        ("123 456", "123456"),
        (" 012345 ", "012345"),
        ("12345", None),
        ("1234567", None),
        ("12345a", None),
        ("١٢٣٤٥٦", None),
        ("", None),
    ],
)
def test_a_typed_number(typed: str, expected: str | None) -> None:
    assert typed_number(typed) == expected
