"""Plugin slash commands must execute while the agent is busy.

Regression: the busy branch of ``sendMessage`` intercepted only a hardcoded
allowlist of built-in commands (steer/interrupt/queue/terminal/goal/yolo).
Anything else that started with ``/`` fell through to ``_trySteer``, so typing
``/conductor status`` mid-turn rendered a STEER bubble and handed the literal
string to the model as a mid-turn nudge. The command silently never ran.

These tests read the shipped source so they fail if the intercept is removed
or narrowed again.
"""

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MESSAGES = (ROOT / "static" / "messages.js").read_text(encoding="utf-8")
COMMANDS = (ROOT / "static" / "commands.js").read_text(encoding="utf-8")


def _busy_branch() -> str:
    """Return the busy/compression branch of the send path."""
    start = MESSAGES.find("if(S.busy||compressionRunning){")
    assert start >= 0, "busy branch not found in messages.js"
    # The steer fallback marks the end of the region we care about.
    end = MESSAGES.find("await _trySteer(text, /*explicitSteer=*/false);", start)
    assert end > start, "busy-path steer fallback not found"
    return MESSAGES[start:end]


def test_busy_path_dispatches_plugin_commands_before_steering():
    branch = _busy_branch()
    assert "getAgentCommandMetadata" in branch, (
        "busy path no longer resolves command metadata, so plugin commands "
        "will fall through to _trySteer and be sent to the model as text"
    )
    assert "category==='Plugin'" in branch, (
        "busy path no longer detects plugin commands"
    )
    assert "executeAgentPluginCommand" in branch, (
        "busy path no longer executes plugin commands"
    )


def test_plugin_dispatch_precedes_the_steer_fallback():
    """Ordering matters: the intercept is useless after the steer call."""
    plugin_at = MESSAGES.find("category==='Plugin'")
    steer_at = MESSAGES.find("await _trySteer(text, /*explicitSteer=*/false);")
    assert plugin_at >= 0 and steer_at >= 0
    assert plugin_at < steer_at, (
        "plugin dispatch must run BEFORE the steer fallback"
    )


def test_busy_plugin_dispatch_returns_and_does_not_also_steer():
    """The plugin branch must return, otherwise the text is ALSO steered."""
    branch = _busy_branch()
    idx = branch.find("category==='Plugin'")
    assert idx >= 0
    tail = branch[idx:]
    assert "return;" in tail, (
        "plugin branch must return so the message is not also sent as a steer"
    )


@pytest.mark.parametrize(
    "builtin", ["steer", "interrupt", "queue", "terminal", "goal", "yolo"]
)
def test_builtin_busy_controls_are_still_intercepted(builtin):
    """The pre-existing allowlist must survive the change."""
    branch = _busy_branch()
    assert f"'{builtin}'" in branch, f"/{builtin} lost its busy-path intercept"


def test_command_transport_sends_session_id():
    """Plugin command dispatch must identify the session that issued it.

    Without this the backend falls back to process-global env, which in a
    multi-session WebUI is whichever session last ran a turn.
    """
    start = COMMANDS.find("async function _runAgentCommandTransport(")
    assert start >= 0, "_runAgentCommandTransport not found"
    end = COMMANDS.find("\n}", start)
    body = COMMANDS[start:end]
    assert "session_id" in body, "command transport no longer sends session_id"
    assert "S.session.session_id" in body, (
        "command transport does not read the active session id"
    )
