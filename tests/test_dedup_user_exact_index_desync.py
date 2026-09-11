"""Regression: ``_deduplicate_context_messages`` must not desync its index map.

``user_exact_index`` maps a user message's exact-identity key to that message's
position in ``deduped``. Before this fix the index was recorded before the
``key in seen`` drop branch ran, so a dropped duplicate still registered
``len(deduped)`` — one past the end. A later exact duplicate carrying
``_active_turn_token`` then executed ``deduped[prior_exact_idx] = msg`` against
that stale index and raised::

    IndexError: list assignment index out of range

The turn died after its text had already streamed, so the WebUI rendered a
bare "Error: list assignment index out of range" card under a complete reply.
Ambient meeting-capture sessions replay byte-identical user rows, which made
them hit this on almost every turn.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from api.streaming import _deduplicate_context_messages, _message_identity

TRANSCRIPT = "[MEETING TRANSCRIPT] ambient speech"


def _user(content, timestamp, *, token=None, source="webui"):
    msg = {"role": "user", "content": content, "timestamp": timestamp, "_source": source}
    if token is not None:
        msg["_active_turn_token"] = token
    return msg


def test_dropped_duplicate_does_not_register_out_of_range_index():
    """The exact shape that crashed: dup drop, then an exact dup with a token."""
    messages = [
        _user(TRANSCRIPT, 1.0),
        _user(TRANSCRIPT, 2.0),
        _user(TRANSCRIPT, 2.0, token="tok"),
    ]
    result = _deduplicate_context_messages(messages)
    assert result, "dedup must not return an empty transcript"
    assert result[-1].get("_active_turn_token") == "tok"


def test_active_turn_token_replaces_exact_duplicate_in_place():
    """Preserve the #6481 behaviour: replace the row, never duplicate it."""
    messages = [
        _user("hello", 5.0),
        _user("hello", 5.0, token="t2"),
    ]
    result = _deduplicate_context_messages(messages)
    assert len(result) == 1
    assert result[0]["_active_turn_token"] == "t2"


def test_every_recorded_index_stays_in_range_for_repeated_transcripts():
    """A long ambient run of identical rows must never raise IndexError."""
    messages = []
    for i in range(40):
        messages.append(_user(TRANSCRIPT, float(i % 3)))
        if i % 4 == 0:
            messages.append(_user(TRANSCRIPT, float(i % 3), token=f"tok{i}"))
    result = _deduplicate_context_messages(messages)
    assert result


@pytest.mark.parametrize("token_first", [True, False])
def test_mixed_roles_and_ordering_preserved(token_first):
    messages = [
        _user("q", 1.0, token="a" if token_first else None),
        {"role": "assistant", "content": "answer"},
        _user("q2", 2.0),
    ]
    result = _deduplicate_context_messages(messages)
    assert [m["role"] for m in result] == ["user", "assistant", "user"]


def test_distinct_users_are_not_collapsed():
    messages = [_user("one", 1.0), _user("two", 2.0), _user("three", 3.0)]
    result = _deduplicate_context_messages(messages)
    assert [m["content"] for m in result] == ["one", "two", "three"]
