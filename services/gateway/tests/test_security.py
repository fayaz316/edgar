from __future__ import annotations

import pytest

from services.gateway.security import (
    KeyStore,
    RateLimiter,
    Security,
    generate_key,
    hash_key,
    parse_keys,
)


def test_generated_keys_are_random_prefixed_and_hash_to_their_config_entry() -> None:
    k1, h1 = generate_key()
    k2, _ = generate_key()
    assert k1 != k2 and k1.startswith("ea_") and len(k1) >= 40
    assert h1 == hash_key(k1) and len(h1) == 64


def test_parse_keys_accepts_good_entries_and_rejects_malformed_ones_loudly() -> None:
    good = hash_key("x")
    assert parse_keys(f"alice:{good}, bob:{hash_key('y')}") == {good: "alice", hash_key("y"): "bob"}
    assert parse_keys("") == {}
    for bad in ("alice", "alice:short", f":{good}", f"alice:{good.upper()}"):
        with pytest.raises(ValueError, match="EA_API_KEYS"):
            parse_keys(bad)


def test_authenticate_matches_only_the_exact_key() -> None:
    key, digest = generate_key()
    store = KeyStore({digest: "alice"})
    assert store.authenticate(key) == "alice"
    assert store.authenticate(key + "x") is None
    assert store.authenticate("") is None
    assert KeyStore({}).authenticate(key) is None


def test_sliding_window_blocks_then_frees_up() -> None:
    rl = RateLimiter(per_minute=3, daily_cap=100)
    assert [rl.check("a", now=t) for t in (0.0, 1.0, 2.0)] == [0.0, 0.0, 0.0]
    wait = rl.check("a", now=3.0)
    assert 56.0 <= wait <= 58.0  # the oldest hit (t=0) leaves the window at t=60
    assert rl.check("b", now=3.0) == 0.0  # other callers are independent
    assert rl.check("a", now=60.5) == 0.0  # window slid


def test_blocked_calls_are_not_counted() -> None:
    rl = RateLimiter(per_minute=1, daily_cap=100)
    assert rl.check("a", now=0.0) == 0.0
    for t in (1.0, 2.0, 3.0):
        assert rl.check("a", now=t) > 0
    assert rl.check("a", now=60.1) == 0.0  # hammering did not extend the penalty


def test_daily_cap_is_per_caller_and_per_day() -> None:
    rl = RateLimiter(per_minute=100, daily_cap=2)
    assert [rl.take_daily("a", "2026-11-08") for _ in range(3)] == [True, True, False]
    assert rl.take_daily("b", "2026-11-08") is True
    assert rl.take_daily("a", "2026-11-09") is True


def test_failed_auth_throttle_trips_after_ten_failures_and_expires() -> None:
    sec = Security(KeyStore({}), RateLimiter(10, 10))
    assert not any(sec.note_failure("1.2.3.4", now=float(i)) for i in range(10))
    assert sec.note_failure("1.2.3.4", now=10.0) is True and sec.throttled("1.2.3.4", now=11.0)
    assert not sec.throttled("5.6.7.8", now=11.0)
    assert not sec.throttled("1.2.3.4", now=400.0)  # 5 minutes later it clears


def test_refund_gives_back_one_counted_call_in_both_windows() -> None:
    rl = RateLimiter(per_minute=1, daily_cap=1)
    assert rl.check("a", now=0.0) == 0.0 and rl.take_daily("a", "d")
    assert rl.check("a", now=1.0) > 0 and not rl.take_daily("a", "d")  # both exhausted
    rl.refund("a", "d")
    assert rl.check("a", now=2.0) == 0.0 and rl.take_daily("a", "d")
    rl.refund("never-seen", "d")  # refunding an unknown caller is harmless
