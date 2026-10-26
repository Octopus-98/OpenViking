# Copyright (c) 2026 Beijing Volcano Engine Technology Co., Ltd.
# SPDX-License-Identifier: AGPL-3.0
"""Resolve TTL per field: User > Account > global, then fall back to global TTL.

A concrete Peer override precedes peer_events. Unset fields inherit; disabled
stops fallback. Configuration sources are already loaded, so resolution has no I/O.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from openviking.core.namespace import uri_parts
from openviking_cli.utils.config.ttl_config import TTLConfig, UserTTLConfig


class TTLIndexType(str, Enum):
    USER_EVENTS = "user_events"
    PEER_EVENTS = "peer_events"
    SESSIONS = "sessions"


_ROOT_DEPTH = {
    TTLIndexType.USER_EVENTS: 4,
    TTLIndexType.PEER_EVENTS: 6,
    TTLIndexType.SESSIONS: 3,
}


@dataclass(frozen=True)
class EffectiveTTL:
    index_type: Optional[TTLIndexType]
    enabled: bool
    days: Optional[int]

    @classmethod
    def off(cls, index_type: Optional[TTLIndexType]) -> "EffectiveTTL":
        return cls(index_type=index_type, enabled=False, days=None)


def classify_ttl_uri(uri: str) -> Optional[TTLIndexType]:
    """Identify supported user/peer Events and Sessions, including descendants."""
    try:
        parts = uri_parts(uri)
    except ValueError:
        return None
    if len(parts) < 3 or parts[0] != "user":
        return None
    # user/{uid}/peers/{peer_id}/memories/events[/...]
    if len(parts) >= 6 and parts[2] == "peers" and parts[4] == "memories" and parts[5] == "events":
        return TTLIndexType.PEER_EVENTS
    # user/{uid}/memories/events[/...]
    if len(parts) >= 4 and parts[2] == "memories" and parts[3] == "events":
        return TTLIndexType.USER_EVENTS
    # user/{uid}/sessions[/...]
    if parts[2] == "sessions":
        return TTLIndexType.SESSIONS
    return None


def resolve_effective_ttl(
    cluster_ttl: Optional[TTLConfig],
    account_ttl: Optional[TTLConfig],
    uri: str,
    user_ttl: Optional[UserTTLConfig] = None,
) -> EffectiveTTL:
    """Resolve one URI using the already-loaded configuration pair; no I/O."""
    kind = classify_ttl_uri(uri)
    if kind is None:
        return EffectiveTTL.off(None)
    if kind == TTLIndexType.PEER_EVENTS and user_ttl is not None:
        value = (user_ttl.peers or {}).get(uri_parts(uri)[3])
        if value is not None:
            return (
                EffectiveTTL.off(kind) if value == "disabled" else EffectiveTTL(kind, True, value)
            )
    for node in (kind.value, "global_"):
        for config in (user_ttl, account_ttl, cluster_ttl):
            value = getattr(config, node, None)
            if value is not None:
                return (
                    EffectiveTTL.off(kind)
                    if value == "disabled"
                    else EffectiveTTL(kind, True, value)
                )
    return EffectiveTTL.off(kind)


def validate_ttl_root(uri: str) -> None:
    """Validate a management/backfill target, not a configuration map."""
    from openviking.core.identifiers import validate_identifier_part

    kind = classify_ttl_uri(uri)
    parts = uri_parts(uri)
    if (
        kind is None
        or len(parts) != _ROOT_DEPTH[kind]
        or uri != "viking://" + "/".join(parts)
        or validate_identifier_part(parts[1], "user_id")
        or (kind == TTLIndexType.PEER_EVENTS and validate_identifier_part(parts[3], "peer_id"))
    ):
        raise ValueError("TTL target must be a canonical Events or Sessions root")
