"""pi-sourced state.db sessions must be visible in the sidebar.

pi (the standalone coding agent CLI, ~/.pi/agent/sessions/*.jsonl) is imported
into the Hermes agent DB by ~/.hermes/scripts/pi_session_import.py, which writes
rows with ``source='pi'``. Before this fix, 'pi' normalised to session_source
'other', which fell through BOTH sidebar buckets:

- ``sidebar_source=webui`` skips the state.db projection entirely, and a pi
  session has no WebUI sidecar, so it never appeared there.
- ``sidebar_source=cli`` keeps only CLI-classified rows
  (``is_cli_session_row``), which dropped 'other' rows.

pi is an external coding agent whose transcripts Hermes only reads, exactly
like Claude Code and Codex, so it is classified ``external_agent`` (read-only)
rather than into the writable CLI family. ``external_agent`` already files into
the CLI sidebar bucket via the ``is_cli_session_row`` fallthrough, and is a hard
refusal for chat-start, which is what we want: a pi transcript is a record to
read, not a Hermes conversation to resume.
"""

from api.agent_sessions import (
    is_cli_session_row,
    is_cli_session_row_visible,
    normalize_agent_session_source,
)


def test_pi_normalizes_to_external_agent():
    meta = normalize_agent_session_source('pi')
    assert meta['session_source'] == 'external_agent'
    assert meta['raw_source'] == 'pi'
    assert meta['source_label'] == 'pi'


def test_pi_row_is_cli_classified():
    """Rows must file into the CLI sidebar bucket, normalized or raw.

    The server-side count classifier and the client renderer
    (static/sessions.js: _isCliSession) must agree, or the WebUI shows a
    non-zero count with an empty list (#5831).
    """
    row = {'id': 'pi-abc123', 'source': 'pi'}
    assert is_cli_session_row({**row, **normalize_agent_session_source('pi')}) is True
    # Raw rows (no prior normalization) must classify the same way — several
    # callers pass sidecar/state rows that only carry source metadata.
    assert is_cli_session_row(row) is True


def test_pi_row_with_messages_stays_visible_even_when_ended():
    """Ended pi rows are real user work, never framework noise."""
    row = {
        'id': 'pi-ended',
        'source': 'pi',
        'title': 'Refactor the auth module',
        'message_count': 12,
        'ended_at': 1785950000.0,
    }
    normalized = {**row, **normalize_agent_session_source('pi')}
    assert is_cli_session_row(normalized) is True
    assert is_cli_session_row_visible(normalized) is True


def test_pi_is_not_confused_with_writable_cli():
    """pi transcripts are read-only: they must not claim the writable CLI family."""
    meta = normalize_agent_session_source('pi')
    assert meta['session_source'] != 'cli'


def test_pi_prefix_does_not_swallow_other_sources():
    """Only the exact source 'pi' maps to pi — not 'pipeline', 'pi_foo', etc."""
    for other in ('pipeline', 'pi_foo', 'pixel', 'api_server'):
        meta = normalize_agent_session_source(other)
        assert meta['session_source'] != 'external_agent' or other == 'api_server', other
        assert meta['raw_source'] == other
