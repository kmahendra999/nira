"""Per-device identity.

The server authenticated with one static bearer token shared by every caller:
no way to tell a phone from a laptop, no way to revoke one without revoking
all, no per-device audit trail, and no way to let a phone ask questions without
also letting it approve a destructive tool call.

That matters more than usual here, because a tailnet is not automatically
yours alone — so "reachable over Tailscale" cannot stand in for "trusted".
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from nira.devices import DeviceStore
from nira.devices.store import (
    DEFAULT_SCOPES,
    SCOPE_ADMIN,
    SCOPE_APPROVE,
    SCOPE_ASK,
    SCOPE_WATCH,
    hash_secret,
    normalize_scopes,
)


@pytest.fixture
def store(tmp_path):
    registry = DeviceStore(tmp_path / "devices.db")
    yield registry
    registry.close()


def _pair(store, name="Pixel 8", **kwargs):
    enrollment = store.create_enrollment(name, **kwargs)
    return store.redeem_enrollment(enrollment.token, platform="android")


class TestScopes:
    def test_normalizes_and_deduplicates(self) -> None:
        assert normalize_scopes(["watch", "ask", "ask"]) == ["ask", "watch"]

    def test_accepts_a_comma_string(self) -> None:
        assert normalize_scopes("ask, watch") == ["ask", "watch"]

    def test_rejects_an_unknown_scope(self) -> None:
        """A scope nobody enforces reads like a guarantee and is not one."""
        with pytest.raises(ValueError, match="Unknown scope"):
            normalize_scopes(["ask", "superuser"])

    def test_a_new_device_cannot_approve(self) -> None:
        """Pairing a phone must not silently let it say yes to anything."""
        assert SCOPE_APPROVE not in DEFAULT_SCOPES
        assert SCOPE_ADMIN not in DEFAULT_SCOPES


class TestPairing:
    def test_redeeming_an_enrollment_yields_a_device_and_key(self, store) -> None:
        device, key = _pair(store)

        assert device.name == "Pixel 8"
        assert device.platform == "android"
        assert device.scopes == list(DEFAULT_SCOPES)
        assert key.startswith("nira_dk_")

    def test_an_enrollment_is_single_use(self, store) -> None:
        """The token is briefly on screen as a QR; a second claim must fail."""
        enrollment = store.create_enrollment("Phone")
        store.redeem_enrollment(enrollment.token)

        with pytest.raises(ValueError, match="already used"):
            store.redeem_enrollment(enrollment.token)

    def test_an_expired_enrollment_is_refused(self, store) -> None:
        enrollment = store.create_enrollment("Phone", ttl=timedelta(seconds=-1))

        with pytest.raises(ValueError, match="expired"):
            store.redeem_enrollment(enrollment.token)

    def test_an_unknown_token_is_refused(self, store) -> None:
        with pytest.raises(ValueError, match="Unknown enrollment"):
            store.redeem_enrollment("nira_en_nonsense")

    def test_each_device_gets_a_distinct_key(self, store) -> None:
        _, first = _pair(store, "Phone A")
        _, second = _pair(store, "Phone B")

        assert first != second

    def test_purging_clears_used_and_expired_invitations(self, store) -> None:
        used = store.create_enrollment("Used")
        store.redeem_enrollment(used.token)
        store.create_enrollment("Stale", ttl=timedelta(seconds=-1))
        live = store.create_enrollment("Live")

        store.purge_expired_enrollments()

        # The live one must survive the sweep.
        assert store.redeem_enrollment(live.token)[0].name == "Live"


class TestSecretsAreNotStored:
    def test_the_raw_key_is_never_written_to_the_database(
        self, store, tmp_path
    ) -> None:
        """A leaked database must not hand over working keys."""
        _, key = _pair(store)

        blob = (tmp_path / "devices.db").read_bytes()
        assert key.encode() not in blob
        assert hash_secret(key).encode() in blob

    def test_the_enrollment_token_is_never_written_either(self, tmp_path) -> None:
        registry = DeviceStore(tmp_path / "d.db")
        try:
            enrollment = registry.create_enrollment("Phone")
        finally:
            registry.close()

        assert enrollment.token.encode() not in (tmp_path / "d.db").read_bytes()


class TestAuthentication:
    def test_a_valid_key_resolves_to_its_device(self, store) -> None:
        device, key = _pair(store)

        assert store.authenticate(key).id == device.id

    def test_an_unknown_key_resolves_to_nothing(self, store) -> None:
        _pair(store)

        assert store.authenticate("nira_dk_not-a-real-key") is None

    def test_an_empty_key_resolves_to_nothing(self, store) -> None:
        assert store.authenticate("") is None

    def test_a_revoked_device_authenticates_as_nothing(self, store) -> None:
        """Not "itself with no scopes" — callers then fail closed by default
        rather than depending on each remembering to check."""
        device, key = _pair(store)
        store.revoke(device.id)

        assert store.authenticate(key) is None

    def test_last_seen_is_recorded(self, store) -> None:
        device, _ = _pair(store)
        assert store.get(device.id).last_seen_at == ""

        store.touch(device.id)

        assert store.get(device.id).last_seen_at != ""


class TestCapabilities:
    def test_granted_scopes_are_allowed(self, store) -> None:
        device, _ = _pair(store)

        assert device.can(SCOPE_ASK) is True
        assert device.can(SCOPE_WATCH) is True

    def test_ungranted_scopes_are_refused(self, store) -> None:
        device, _ = _pair(store)

        assert device.can(SCOPE_APPROVE) is False

    def test_admin_implies_everything(self, store) -> None:
        device, _ = _pair(store, scopes=[SCOPE_ADMIN])

        assert device.can(SCOPE_APPROVE) is True

    def test_a_revoked_device_can_do_nothing(self, store) -> None:
        device, _ = _pair(store, scopes=[SCOPE_ADMIN])
        store.revoke(device.id)

        assert store.get(device.id).can(SCOPE_ASK) is False


class TestManagement:
    def test_scopes_can_be_changed(self, store) -> None:
        device, _ = _pair(store)

        assert store.set_scopes(device.id, [SCOPE_ASK, SCOPE_APPROVE]) is True
        assert store.get(device.id).can(SCOPE_APPROVE) is True

    def test_a_revoked_device_cannot_be_regranted(self, store) -> None:
        device, _ = _pair(store)
        store.revoke(device.id)

        assert store.set_scopes(device.id, [SCOPE_ADMIN]) is False

    def test_revoking_twice_reports_false(self, store) -> None:
        device, _ = _pair(store)

        assert store.revoke(device.id) is True
        assert store.revoke(device.id) is False

    def test_revoked_devices_are_kept_for_the_audit_trail(self, store) -> None:
        """A deleted row makes past activity anonymous."""
        device, _ = _pair(store)
        store.revoke(device.id)

        assert store.get(device.id) is not None
        assert [d.id for d in store.list()] == []
        assert device.id in [d.id for d in store.list(include_revoked=True)]


class TestPersistence:
    def test_a_paired_device_survives_a_reopen(self, tmp_path) -> None:
        first = DeviceStore(tmp_path / "d.db")
        _, key = _pair(first, "Phone")
        first.close()

        second = DeviceStore(tmp_path / "d.db")
        try:
            assert second.authenticate(key).name == "Phone"
        finally:
            second.close()
