"""Regression tests for the KeyPool LRU/round-robin and budget fixes."""

from datetime import UTC, datetime, timedelta

import pytest

from app.llm import (
    KeyPool,
    LLMUnavailable,
    _KeyState,
    keys_from_setting,
)


def _fresh_state(api_key: str, *, last_used_offset_s: float | None = None) -> _KeyState:
    st = _KeyState(api_key)
    if last_used_offset_s is not None:
        st.last_used = datetime.now(UTC) - timedelta(seconds=last_used_offset_s)
    return st


# ---------------------------------------------------------------------------
# keys_from_setting
# ---------------------------------------------------------------------------


def test_keys_from_setting_pool_shape() -> None:
    g = {"enabled": True, "keys": [{"id": "k1", "api_key": "abc", "label": "main"}]}
    assert keys_from_setting(g) == [{"id": "k1", "api_key": "abc", "label": "main"}]


def test_keys_from_setting_legacy_shape() -> None:
    g = {"enabled": True, "api_key": "legacy-key"}
    result = keys_from_setting(g)
    assert len(result) == 1
    assert result[0]["api_key"] == "legacy-key"


def test_keys_from_setting_disabled_returns_empty() -> None:
    g = {"enabled": False, "api_key": "key"}
    assert keys_from_setting(g) == []


def test_keys_from_setting_none_returns_empty() -> None:
    assert keys_from_setting(None) == []


# ---------------------------------------------------------------------------
# KeyPool._sorted_keys — LRU ordering
# ---------------------------------------------------------------------------


async def test_sorted_keys_lru_order(monkeypatch: pytest.MonkeyPatch) -> None:
    """The key used least recently should sort first."""
    keys = [
        {"api_key": "key-a"},
        {"api_key": "key-b"},
        {"api_key": "key-c"},
    ]
    states = {
        "key-a": _fresh_state("key-a", last_used_offset_s=10),   # used 10s ago
        "key-b": _fresh_state("key-b", last_used_offset_s=100),  # used 100s ago (oldest)
        "key-c": _fresh_state("key-c", last_used_offset_s=5),    # used 5s ago (newest)
    }
    monkeypatch.setattr("app.llm._key_states", states)
    pool = KeyPool.__new__(KeyPool)
    pool.keys = keys
    sorted_keys = pool._sorted_keys()
    # key-b (oldest) should be first
    assert sorted_keys[0]["api_key"] == "key-b"
    assert sorted_keys[-1]["api_key"] == "key-c"


# ---------------------------------------------------------------------------
# KeyPool — spend() only on success
# ---------------------------------------------------------------------------


async def test_spend_only_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A failed call must not increment the daily budget counter — spend()
    runs only after generate_content returns. Exercises the real
    KeyPool.call path with the SDK mocked to raise."""
    from app import llm

    llm._key_states.clear()

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = self

        @property
        def models(self):
            return self

        async def generate_content(self, *, model, contents, config=None):
            raise RuntimeError("network error")

        async def aclose(self):
            pass

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", FakeClient)
    pool = llm.KeyPool([{"api_key": "test-key-spend"}])

    with pytest.raises(LLMUnavailable):
        await pool.call(contents="test")

    # The call failed, so the budget counter must not have advanced.
    st = llm._state_for("test-key-spend")
    assert st.count == 0


async def test_spend_increments_on_success(monkeypatch: pytest.MonkeyPatch) -> None:
    """A successful call increments the budget counter exactly once."""
    from app import llm

    llm._key_states.clear()

    class FakeResp:
        text = "ok"

    class FakeClient:
        def __init__(self, api_key):
            self.api_key = api_key
            self.aio = self

        @property
        def models(self):
            return self

        async def generate_content(self, *, model, contents, config=None):
            return FakeResp()

        async def aclose(self):
            pass

    import google.genai as genai_mod

    monkeypatch.setattr(genai_mod, "Client", FakeClient)
    pool = llm.KeyPool([{"api_key": "test-key-ok"}])

    await pool.call(contents="test")
    assert llm._state_for("test-key-ok").count == 1


# ---------------------------------------------------------------------------
# KeyPool — _key_states pruned on rebuild
# ---------------------------------------------------------------------------


def test_key_states_pruned_on_rebuild(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keys removed from the pool must be pruned from _key_states."""
    states = {
        "old-key": _fresh_state("old-key"),
        "current-key": _fresh_state("current-key"),
    }
    monkeypatch.setattr("app.llm._key_states", states)

    # Build a new pool that only contains current-key
    KeyPool([{"api_key": "current-key"}])

    assert "old-key" not in states
    assert "current-key" in states


# ---------------------------------------------------------------------------
# KeyPool — all keys cooling down raises LLMUnavailable
# ---------------------------------------------------------------------------


async def test_all_keys_cooling_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    key = "cooling-key"
    st = _KeyState(key)
    st.cooldown_until = datetime.now(UTC) + timedelta(hours=1)
    monkeypatch.setattr("app.llm._key_states", {key: st})

    pool = KeyPool([{"api_key": key}])
    with pytest.raises(LLMUnavailable, match="cooling down"):
        await pool.call(contents="test")


# ---------------------------------------------------------------------------
# KeyPool — empty pool raises LLMUnavailable
# ---------------------------------------------------------------------------


async def test_empty_pool_raises() -> None:
    pool = KeyPool([])
    with pytest.raises(LLMUnavailable, match="no API key"):
        await pool.call(contents="test")
