# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""TTL policy precedence, explicit disabling and shared Peer Events policies."""

from __future__ import annotations

from itertools import product

import pytest

from openviking.config.ttl import (
    EffectiveTTL,
    TTLIndexType,
    classify_ttl_uri,
    resolve_effective_ttl,
    validate_ttl_root,
)
from openviking_cli.utils.config.ttl_config import TTLConfig

USER_EVENTS_DIR = "viking://user/u1/memories/events/2026/10/01"
USER_EVENTS_ROOT = "viking://user/u1/memories/events"
PEER_EVENTS_DIR = "viking://user/u1/peers/p1/memories/events/2026/10/01"
SESSION_DIR = "viking://user/u1/sessions/s1"


def _cfg(**kwargs) -> TTLConfig:
    return TTLConfig(**kwargs)


# -- classification ---------------------------------------------------------


@pytest.mark.parametrize(
    "uri,expected",
    [
        (USER_EVENTS_DIR, TTLIndexType.USER_EVENTS),
        (USER_EVENTS_ROOT, TTLIndexType.USER_EVENTS),
        (PEER_EVENTS_DIR, TTLIndexType.PEER_EVENTS),
        ("viking://user/u1/peers", TTLIndexType.PEER_EVENTS),
        (SESSION_DIR, TTLIndexType.SESSIONS),
        ("viking://user/u1/sessions", TTLIndexType.SESSIONS),
        ("viking://user/u1/memories/entities/x", None),
        ("viking://resources/project/doc", None),
        ("viking://agent/skills/s", None),
        ("viking://user/u1", None),
    ],
)
def test_classify_ttl_uri(uri, expected):
    assert classify_ttl_uri(uri) == expected


def test_ungoverned_uri_is_always_off():
    cfg = _cfg(global_=30)
    result = resolve_effective_ttl(cfg, cfg, "viking://resources/x")
    assert result == EffectiveTTL.off(None)


# -- default off ------------------------------------------------------------


def test_default_off_when_no_config():
    result = resolve_effective_ttl(None, None, SESSION_DIR)
    assert result == EffectiveTTL.off(TTLIndexType.SESSIONS)
    assert result.enabled is False
    assert result.days is None


def test_empty_config_is_off_but_classified():
    result = resolve_effective_ttl(_cfg(), _cfg(), USER_EVENTS_DIR)
    assert result.index_type is TTLIndexType.USER_EVENTS
    assert result.enabled is False


# -- target selection precedence -------------------------------------------


def test_global_applies_when_no_type_default():
    cluster = _cfg(global_=45)
    result = resolve_effective_ttl(cluster, None, SESSION_DIR)
    assert result.enabled is True
    assert result.days == 45


def test_type_default_beats_global():
    cluster = _cfg(global_=45, sessions=30)
    result = resolve_effective_ttl(cluster, None, SESSION_DIR)
    assert result.days == 30


def test_peer_events_type_default():
    cluster = _cfg(peer_events=14, user_events=60)
    result = resolve_effective_ttl(cluster, None, PEER_EVENTS_DIR)
    assert result.days == 14


def test_user_events_type_default_does_not_apply_to_peer():
    cluster = _cfg(user_events=60)
    result = resolve_effective_ttl(cluster, None, PEER_EVENTS_DIR)
    # peer_events unset -> falls through to global -> default off
    assert result.enabled is False


# -- disabled stops the chain ----------------------------------------------


def test_disabled_type_stops_fallback_to_global():
    cluster = _cfg(global_=45, sessions="disabled")
    result = resolve_effective_ttl(cluster, None, SESSION_DIR)
    assert result.enabled is False
    assert result.index_type is TTLIndexType.SESSIONS


# -- per-node account-over-cluster merge -----------------------------------


def test_doc_example_account_global_does_not_override_cluster_sessions():
    # 库 sessions=30, Account.global=45 -> Session still 30.
    cluster = _cfg(sessions=30)
    account = _cfg(global_=45)
    result = resolve_effective_ttl(cluster, account, SESSION_DIR)
    assert result.days == 30


def test_doc_example_account_sessions_overrides_at_same_node():
    # Account sessions=45 overrides the 库 sessions=30 at the same node.
    cluster = _cfg(sessions=30)
    account = _cfg(sessions=45)
    result = resolve_effective_ttl(cluster, account, SESSION_DIR)
    assert result.days == 45


def test_account_global_overrides_cluster_global_only():
    cluster = _cfg(global_=10)
    account = _cfg(global_=90)
    result = resolve_effective_ttl(cluster, account, SESSION_DIR)
    assert result.days == 90


def test_account_disable_overrides_cluster_enabled_type():
    cluster = _cfg(sessions=30)
    account = _cfg(sessions="disabled")
    result = resolve_effective_ttl(cluster, account, SESSION_DIR)
    assert result.enabled is False


@pytest.mark.parametrize(
    "kind,root",
    [
        (TTLIndexType.SESSIONS, "viking://user/u1/sessions"),
        (TTLIndexType.USER_EVENTS, USER_EVENTS_ROOT),
        (TTLIndexType.PEER_EVENTS, "viking://user/u1/peers/p1/memories/events"),
    ],
)
def test_user_account_global_precedence(kind, root):
    for cg, ag, ug, ct, at, ut in product((None, "disabled", 7), repeat=6):
        cluster = TTLConfig(global_=cg, **{kind.value: ct})
        account = TTLConfig(global_=ag, **{kind.value: at})
        user = TTLConfig(global_=ug, **{kind.value: ut})
        value = next((v for v in (ut, at, ct, ug, ag, cg) if v is not None), "disabled")
        expected = (
            EffectiveTTL.off(kind) if value == "disabled" else EffectiveTTL(kind, True, value)
        )
        for uri in (root, root + "/child/nested"):
            assert resolve_effective_ttl(cluster, account, uri, user) == expected


@pytest.mark.parametrize("peer_days", [7, "disabled", None])
def test_peers_share_user_policy_independently_of_user_events(peer_days):
    config = TTLConfig(peer_events=peer_days, user_events=60)
    account = TTLConfig(peer_events=30)
    expected = {7: 7, "disabled": None, None: 30}[peer_days]
    for suffix in ("", "/p1/memories/events", "/p2/memories/events/2026/10/01"):
        assert (
            resolve_effective_ttl(None, account, "viking://user/u1/peers" + suffix, config).days
            == expected
        )
    assert resolve_effective_ttl(None, account, USER_EVENTS_DIR, config).days == 60


def test_peer_scope_is_queryable_but_not_a_concrete_scan_root():
    scope = "viking://user/u1/peers"
    validate_ttl_root(scope, allow_peer_scope=True)
    with pytest.raises(ValueError):
        validate_ttl_root(scope)
    validate_ttl_root(scope + "/p1/memories/events")


@pytest.mark.parametrize(
    "payload",
    [
        {"roots": {USER_EVENTS_ROOT: 7}},
        {"sessions": True},
        {"sessions": 0},
        {"sessions": 365001},
        {"peers": {"p1": 7}},
    ],
)
def test_reject_invalid_user_ttl(payload):
    with pytest.raises(ValueError):
        TTLConfig.model_validate(payload)
