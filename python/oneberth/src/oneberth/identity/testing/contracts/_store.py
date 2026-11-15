# Copyright 2026 The oneberth Authors
# SPDX-License-Identifier: Apache-2.0

"""What every ``IdentityStore`` must do. The times are given, so no test waits."""

from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from oneberth.identity._records import (
    LAST_USED_EVERY,
    PAIRING_WRONG_TRIES,
    Approval,
    DeviceDescription,
    DeviceSession,
    Identity,
    Pairing,
    PairingState,
    PendingSignIn,
    PersonalToken,
    ServiceToken,
    Session,
    User,
)
from oneberth.identity._roles import Grant
from oneberth.identity._secrets import secret_hash
from oneberth.identity._store import SCHEMA_VERSION, IdentityStore

T0 = datetime(2026, 3, 2, 10, 0, tzinfo=UTC)
SECOND = timedelta(seconds=1)
HOUR = timedelta(hours=1)

ADA = Identity(
    provider="okta",
    subject="00u1ada",
    name="Ada Lovelace",
    email="Ada@Example.com",
    hosted_domain=None,
    groups=frozenset({"platform-users", "platform-admins"}),
)
GRACE = Identity(provider="google", subject="1180042", email="grace@example.com")
PHONE = DeviceDescription(name="Ada's phone", platform="android", app_version="1.4")


def at(seconds: float) -> datetime:
    """``seconds`` after ``T0``."""
    return T0 + timedelta(seconds=seconds)


class IdentityStoreContract:
    """Subclass, and provide a ``store`` fixture: an empty store, set up."""

    @pytest.fixture
    def store(self) -> IdentityStore:
        raise NotImplementedError("an IdentityStoreContract subclass provides `store`")

    # Helpers.

    async def user(
        self, store: IdentityStore, identity: Identity = ADA, now: datetime = T0
    ) -> User:
        return await store.upsert_user(identity, user_id=uuid.uuid4(), now=now)

    async def session(
        self, store: IdentityStore, user: User, key: str, expires_at: datetime
    ) -> Session:
        session = Session(uuid.uuid4(), user.id, secret_hash(key), T0, expires_at)
        await store.add_session(session)
        return session

    async def waiting(
        self,
        store: IdentityStore,
        user: User,
        code: str,
        *,
        now: datetime = T0,
        life: timedelta = 120 * SECOND,
    ) -> Pairing:
        pairing = Pairing(
            id=uuid.uuid4(),
            user_id=user.id,
            code_hash=secret_hash(code),
            state=PairingState.WAITING,
            created_at=now,
            expires_at=now + life,
        )
        assert await store.add_pairing(pairing, now, at_most=3)
        return pairing

    async def claimed(
        self, store: IdentityStore, user: User, code: str, claim: str
    ) -> Pairing:
        await self.waiting(store, user, code)
        claimed = await store.claim_pairing(
            secret_hash(code),
            claim_hash=secret_hash(claim),
            number="123456",
            device=PHONE,
            now=at(10),
            expires_at=at(130),
        )
        assert claimed is not None
        return claimed

    async def device(
        self, store: IdentityStore, user: User, code: str, claim: str
    ) -> DeviceSession:
        pairing = await self.claimed(store, user, code, claim)
        outcome, device = await store.approve_pairing(
            user.id,
            pairing.id,
            "123456",
            device_id=uuid.uuid4(),
            device_expires_at=at(30 * 86400),
            now=at(20),
        )
        assert outcome is Approval.APPROVED and device is not None
        return device

    # The schema.

    async def test_setup_records_the_version_and_is_safe_to_repeat(
        self, store: IdentityStore
    ) -> None:
        user = await self.user(store)

        await store.setup()

        assert await store.schema_version() == SCHEMA_VERSION
        assert await store.user(user.id) == user

    # Users.

    async def test_the_first_sign_in_creates_the_user(
        self, store: IdentityStore
    ) -> None:
        user_id = uuid.uuid4()

        user = await store.upsert_user(ADA, user_id=user_id, now=T0)

        assert user == User(
            id=user_id,
            provider="okta",
            subject="00u1ada",
            created_at=T0,
            name="Ada Lovelace",
            email="Ada@Example.com",
            groups=frozenset({"platform-users", "platform-admins"}),
        )
        assert await store.user(user_id) == user
        assert await store.user_of("okta", "00u1ada") == user
        assert await store.user_of("google", "00u1ada") is None
        assert await store.user(uuid.uuid4()) is None

    async def test_a_later_sign_in_refreshes_the_user_and_keeps_its_id(
        self, store: IdentityStore
    ) -> None:
        first = await self.user(store)
        changed = Identity(
            provider="okta",
            subject="00u1ada",
            name="Ada King",
            hosted_domain="example.com",
        )

        later = await store.upsert_user(changed, user_id=uuid.uuid4(), now=at(60))

        assert (later.id, later.created_at) == (first.id, T0)
        assert later.identity == changed
        assert await store.user(first.id) == later

    async def test_users_are_found_by_email_without_regard_to_case(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        other = await self.user(
            store,
            Identity(provider="google", subject="9", email="ada@example.com"),
            now=at(5),
        )
        await self.user(store, GRACE)

        found = await store.users_with_email("ADA@example.COM")

        assert found == [ada, other]
        assert await store.users_with_email("nobody@example.com") == []

    # Sessions.

    async def test_a_session_is_found_by_its_hash_until_it_expires(
        self, store: IdentityStore
    ) -> None:
        user = await self.user(store)
        session = await self.session(store, user, "s", at(3600))

        assert await store.session_by_hash(secret_hash("s"), at(3599)) == (
            user,
            session,
        )
        assert await store.session_by_hash(secret_hash("s"), at(3600)) is None
        assert await store.session_by_hash(secret_hash("other"), T0) is None

    async def test_sessions_are_ended_one_or_all(self, store: IdentityStore) -> None:
        user = await self.user(store)
        for key in ("a", "b"):
            await self.session(store, user, key, at(3600))
        await self.session(store, user, "old", at(1))

        assert await store.delete_session(secret_hash("a")) is True
        assert await store.delete_session(secret_hash("a")) is False
        assert await store.session_by_hash(secret_hash("a"), T0) is None
        assert await store.delete_sessions() == 2
        assert await store.session_by_hash(secret_hash("b"), T0) is None
        assert await store.delete_sessions() == 0

    # Personal tokens.

    async def test_a_personal_token_is_found_and_listed_by_its_owner(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        later = PersonalToken(
            uuid.uuid4(), ada.id, "laptop", secret_hash("t2"), at(10), at(100)
        )
        first = PersonalToken(
            uuid.uuid4(), ada.id, "ci", secret_hash("t1"), T0, at(100)
        )
        theirs = PersonalToken(
            uuid.uuid4(), grace.id, "x", secret_hash("t3"), T0, at(100)
        )
        for token in (later, first, theirs):
            await store.add_personal_token(token)

        assert await store.personal_token_by_hash(secret_hash("t1"), at(99)) == (
            ada,
            first,
        )
        assert await store.personal_token_by_hash(secret_hash("t1"), at(100)) is None
        assert await store.personal_tokens_of(ada.id) == [first, later]
        assert await store.personal_tokens_of(grace.id) == [theirs]

    async def test_a_personal_token_is_deleted_by_its_owner_alone(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        token = PersonalToken(uuid.uuid4(), ada.id, "ci", secret_hash("t"), T0, at(99))
        await store.add_personal_token(token)

        assert await store.delete_personal_token(grace.id, token.id) is False
        assert await store.delete_personal_token(ada.id, token.id) is True
        assert await store.delete_personal_token(ada.id, token.id) is False
        assert await store.personal_token_by_hash(secret_hash("t"), T0) is None

    # Pairings.

    async def test_a_user_has_at_most_so_many_pairings_waiting(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        for n in range(3):
            await self.waiting(store, ada, f"c{n}", life=60 * SECOND)
        fourth = Pairing(
            uuid.uuid4(), ada.id, secret_hash("c3"), PairingState.WAITING, T0, at(120)
        )

        refused = await store.add_pairing(fourth, at(1), at_most=3)
        theirs = await store.add_pairing(
            Pairing(
                uuid.uuid4(),
                grace.id,
                secret_hash("g"),
                PairingState.WAITING,
                T0,
                at(60),
            ),
            at(1),
            at_most=3,
        )
        after_expiry = await store.add_pairing(fourth, at(60), at_most=3)

        assert (refused, theirs, after_expiry) == (False, True, True)
        assert await store.pairing_of(ada.id, fourth.id) == fourth

    async def test_a_code_is_claimed_once_while_it_waits(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        pairing = await self.waiting(store, ada, "code")

        claims = await asyncio.gather(
            *(
                store.claim_pairing(
                    secret_hash("code"),
                    claim_hash=secret_hash(f"claim{n}"),
                    number="123456",
                    device=PHONE,
                    now=at(10),
                    expires_at=at(130),
                )
                for n in range(3)
            )
        )

        won = [c for c in claims if c is not None]
        assert len(won) == 1
        assert won[0].id == pairing.id
        assert won[0].state is PairingState.CLAIMED
        assert (won[0].number, won[0].device, won[0].expires_at) == (
            "123456",
            PHONE,
            at(130),
        )
        assert await store.pairing_of(ada.id, pairing.id) == won[0]

    async def test_an_expired_or_unknown_code_is_not_claimed(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        await self.waiting(store, ada, "code", life=60 * SECOND)

        async def claim(code: str, now: datetime) -> Pairing | None:
            return await store.claim_pairing(
                secret_hash(code),
                claim_hash=secret_hash("claim"),
                number="000001",
                device=PHONE,
                now=now,
                expires_at=now + 120 * SECOND,
            )

        assert await claim("code", at(60)) is None
        assert await claim("other", at(1)) is None

    async def test_a_pairing_is_seen_and_deleted_by_its_owner_alone(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        pairing = await self.waiting(store, ada, "code")

        assert await store.pairing_of(grace.id, pairing.id) is None
        assert await store.delete_pairing(grace.id, pairing.id) is False
        assert await store.delete_pairing(ada.id, pairing.id) is True
        assert await store.pairing_of(ada.id, pairing.id) is None

    async def test_the_right_number_moves_the_claim_to_a_device(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        pairing = await self.claimed(store, ada, "code", "claim")
        device_id = uuid.uuid4()
        assert await store.claim_state(secret_hash("claim"), at(20)) is (
            PairingState.CLAIMED
        )

        outcome, device = await store.approve_pairing(
            ada.id,
            pairing.id,
            "123456",
            device_id=device_id,
            device_expires_at=at(86400),
            now=at(20),
        )

        assert outcome is Approval.APPROVED
        assert device == DeviceSession(
            id=device_id,
            user_id=ada.id,
            device=PHONE,
            secret_hash=secret_hash("claim"),
            created_at=at(20),
            last_used_at=at(20),
            expires_at=at(86400),
        )
        assert await store.device_by_hash(secret_hash("claim"), at(21)) == (
            ada,
            device,
        )
        assert await store.claim_state(secret_hash("claim"), at(21)) is None
        approved = await store.pairing_of(ada.id, pairing.id)
        assert approved is not None
        assert (approved.state, approved.claim_hash) == (PairingState.APPROVED, None)
        again = await store.approve_pairing(
            ada.id,
            pairing.id,
            "123456",
            device_id=uuid.uuid4(),
            device_expires_at=at(86400),
            now=at(22),
        )
        assert again == (Approval.NOT_CLAIMED, None)

    async def test_wrong_numbers_count_and_the_last_ends_the_pairing(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        pairing = await self.claimed(store, ada, "code", "claim")

        outcomes = [
            (
                await store.approve_pairing(
                    ada.id,
                    pairing.id,
                    "999999",
                    device_id=uuid.uuid4(),
                    device_expires_at=at(86400),
                    now=at(20),
                )
            )[0]
            for _ in range(PAIRING_WRONG_TRIES + 1)
        ]

        assert outcomes == [Approval.WRONG_NUMBER] * (PAIRING_WRONG_TRIES - 1) + [
            Approval.GONE,
            Approval.GONE,
        ]
        assert await store.pairing_of(ada.id, pairing.id) is None
        assert await store.device_by_hash(secret_hash("claim"), at(21)) is None

    async def test_an_approve_decides_only_a_claimed_pairing_of_its_owner(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        waiting = await self.waiting(store, ada, "waiting")
        claimed = await self.claimed(store, ada, "code", "claim")

        async def approve(user: User, pairing: Pairing, now: datetime) -> Approval:
            outcome, _ = await store.approve_pairing(
                user.id,
                pairing.id,
                "123456",
                device_id=uuid.uuid4(),
                device_expires_at=at(86400),
                now=now,
            )
            return outcome

        assert await approve(ada, waiting, at(20)) is Approval.NOT_CLAIMED
        assert await approve(grace, claimed, at(20)) is Approval.GONE
        assert await approve(ada, claimed, at(130)) is Approval.GONE
        assert await store.claim_state(secret_hash("claim"), at(130)) is None

    async def test_of_two_approves_at_once_one_links_a_device(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        pairing = await self.claimed(store, ada, "code", "claim")

        results = await asyncio.gather(
            *(
                store.approve_pairing(
                    ada.id,
                    pairing.id,
                    "123456",
                    device_id=uuid.uuid4(),
                    device_expires_at=at(86400),
                    now=at(20),
                )
                for _ in range(3)
            )
        )

        assert sorted(outcome for outcome, _ in results) == sorted(
            [Approval.APPROVED, Approval.NOT_CLAIMED, Approval.NOT_CLAIMED]
        )
        assert len(await store.devices_of(ada.id)) == 1

    # Device sessions.

    async def test_a_device_records_its_last_use_once_a_minute(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        device = await self.device(store, ada, "code", "claim")
        hashed = secret_hash("claim")

        soon = await store.device_by_hash(hashed, device.created_at + 59 * SECOND)
        later = await store.device_by_hash(hashed, device.created_at + LAST_USED_EVERY)

        assert soon is not None and later is not None
        assert soon[1].last_used_at == device.created_at
        assert later[1].last_used_at == device.created_at + LAST_USED_EVERY
        assert await store.devices_of(ada.id) == [later[1]]
        assert await store.device_by_hash(hashed, device.expires_at) is None

    async def test_devices_are_listed_and_removed_by_owner(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        first = await self.device(store, ada, "c1", "d1")
        theirs = await self.device(store, grace, "c2", "d2")

        assert await store.all_devices() == sorted(
            [(ada, first), (grace, theirs)], key=lambda pair: pair[1].id
        )
        assert await store.devices_of(grace.id) == [theirs]
        assert await store.delete_device(grace.id, first.id) is False
        assert await store.delete_device(ada.id, first.id) is True
        assert await store.devices_of(ada.id) == []

    async def test_the_operator_ends_devices_by_user_by_id_or_all(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        a1 = await self.device(store, ada, "c1", "d1")
        a2 = await self.device(store, ada, "c2", "d2")
        g1 = await self.device(store, grace, "c3", "d3")
        g2 = await self.device(store, grace, "c4", "d4")

        by_user = await store.delete_devices(user_id=ada.id)
        by_id = await store.delete_devices(device_id=g1.id)
        every = await store.delete_devices(every=True)

        assert sorted(d.id for d in by_user) == sorted([a1.id, a2.id])
        assert by_id == [g1]
        assert every == [g2]
        with pytest.raises(ValueError):
            await store.delete_devices()
        with pytest.raises(ValueError):
            await store.delete_devices(user_id=ada.id, every=True)

    # Service tokens.

    async def test_a_service_token_keeps_its_grant_and_is_listed_by_name(
        self, store: IdentityStore
    ) -> None:
        worker = ServiceToken(
            uuid.uuid4(),
            "worker-gpu",
            Grant("neorc/worker", "python-gpu"),
            secret_hash("w"),
            T0,
        )
        ci = ServiceToken(
            uuid.uuid4(), "ci", Grant("neorc/ci"), secret_hash("c"), T0, at(60)
        )

        assert await store.add_service_token(worker) is True
        assert await store.add_service_token(ci) is True

        assert await store.service_token_by_hash(secret_hash("w"), at(10**8)) == worker
        assert await store.service_token_by_hash(secret_hash("c"), at(59)) == ci
        assert await store.service_token_by_hash(secret_hash("c"), at(60)) is None
        assert await store.service_tokens() == [ci, worker]

    async def test_a_service_token_name_is_taken_once(
        self, store: IdentityStore
    ) -> None:
        first = ServiceToken(
            uuid.uuid4(), "ci", Grant("neorc/ci"), secret_hash("1"), T0, at(1)
        )
        second = ServiceToken(
            uuid.uuid4(), "ci", Grant("neorc/ci"), secret_hash("2"), at(5)
        )
        await store.add_service_token(first)
        await store.delete_expired(at(10))

        assert await store.add_service_token(second) is False
        assert await store.service_token_by_hash(secret_hash("2"), at(5)) is None
        assert await store.service_tokens() == [first]

    async def test_a_revoked_service_token_is_gone(self, store: IdentityStore) -> None:
        token = ServiceToken(
            uuid.uuid4(), "ci", Grant("neorc/ci"), secret_hash("t"), T0
        )
        await store.add_service_token(token)

        assert await store.delete_service_token(token.id) is True
        assert await store.delete_service_token(token.id) is False
        assert await store.service_token_by_hash(secret_hash("t"), T0) is None
        assert await store.service_tokens() == []

    # Sign-ins in progress.

    def pending(self, state: str, expires_at: datetime) -> PendingSignIn:
        return PendingSignIn(
            state_hash=secret_hash(state),
            provider="okta",
            nonce="n" * 43,
            verifier="v" * 64,
            return_to="/#/neorc/runs",
            created_at=T0,
            expires_at=expires_at,
        )

    async def test_a_pending_sign_in_is_taken_once(self, store: IdentityStore) -> None:
        pending = self.pending("state", at(600))
        assert await store.add_pending_sign_in(pending, T0, limit=10)

        taken = await asyncio.gather(
            *(store.take_pending_sign_in(secret_hash("state"), at(1)) for _ in range(3))
        )

        assert taken.count(pending) == 1
        assert taken.count(None) == 2
        assert await store.take_pending_sign_in(secret_hash("never"), at(1)) is None

    async def test_an_expired_pending_sign_in_is_not_taken(
        self, store: IdentityStore
    ) -> None:
        await store.add_pending_sign_in(self.pending("s", at(600)), T0, limit=10)

        assert await store.take_pending_sign_in(secret_hash("s"), at(600)) is None
        assert await store.take_pending_sign_in(secret_hash("s"), at(1)) is None

    async def test_no_more_sign_ins_than_the_limit_are_in_progress(
        self, store: IdentityStore
    ) -> None:
        added = [
            await store.add_pending_sign_in(self.pending(f"s{n}", at(600)), T0, limit=3)
            for n in range(4)
        ]
        await store.take_pending_sign_in(secret_hash("s0"), at(1))
        after_a_take = await store.add_pending_sign_in(
            self.pending("s4", at(600)), at(1), limit=3
        )
        after_expiry = await store.add_pending_sign_in(
            self.pending("s5", at(1200)), at(600), limit=3
        )

        assert added == [True, True, True, False]
        assert (after_a_take, after_expiry) == (True, True)
        assert await store.take_pending_sign_in(secret_hash("s3"), at(1)) is None

    # Every credential of a person, and the sweep.

    async def test_every_credential_of_a_user_ends_at_once(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        grace = await self.user(store, GRACE)
        await self.session(store, ada, "s", at(3600))
        await store.add_personal_token(
            PersonalToken(uuid.uuid4(), ada.id, "t", secret_hash("t"), T0, at(99))
        )
        await self.device(store, ada, "c1", "d1")
        await self.waiting(store, ada, "c2")
        kept = await self.session(store, grace, "g", at(3600))

        deleted = await store.delete_credentials_of(ada.id)

        # The session, the token, the device, and the two pairings.
        assert deleted == 5
        assert await store.session_by_hash(secret_hash("s"), T0) is None
        assert await store.personal_tokens_of(ada.id) == []
        assert await store.devices_of(ada.id) == []
        assert await store.user(ada.id) == ada
        assert await store.session_by_hash(secret_hash("g"), T0) == (grace, kept)
        assert await store.delete_credentials_of(ada.id) == 0

    async def test_every_credential_of_an_identity_ends_at_once(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        await self.session(store, ada, "s", at(3600))

        assert await store.delete_credentials_of_identity("okta", "nobody") == 0
        assert await store.delete_credentials_of_identity("okta", ADA.subject) == 1
        assert await store.session_by_hash(secret_hash("s"), T0) is None

    async def test_the_sweep_deletes_what_expired_but_service_tokens(
        self, store: IdentityStore
    ) -> None:
        ada = await self.user(store)
        await self.session(store, ada, "old", at(10))
        new = await self.session(store, ada, "new", at(3600))
        await store.add_personal_token(
            PersonalToken(uuid.uuid4(), ada.id, "t", secret_hash("t"), T0, at(10))
        )
        await self.waiting(store, ada, "code", life=10 * SECOND)
        await store.add_pending_sign_in(self.pending("p", at(10)), T0, limit=10)
        service = ServiceToken(
            uuid.uuid4(), "ci", Grant("neorc/ci"), secret_hash("c"), T0, at(10)
        )
        await store.add_service_token(service)

        deleted = await store.delete_expired(at(10))

        assert deleted == 4
        assert await store.delete_expired(at(10)) == 0
        assert await store.session_by_hash(secret_hash("new"), at(11)) == (ada, new)
        assert await store.personal_tokens_of(ada.id) == []
        assert await store.service_tokens() == [service]
