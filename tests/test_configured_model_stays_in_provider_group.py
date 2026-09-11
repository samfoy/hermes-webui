"""Configured (Primary/Fallback) models stay inside their provider group.

Before this, a model carrying a Primary or Fallback badge was pulled OUT of its
provider group and rendered only in a pinned "Configured" section at the top of
the dropdown. The group header still counted it, so a provider group advertised
"(8)" while showing 6 rows, and a user scrolled to that group could not find
Opus 5 or Sonnet 5 at all.

The pinned section now carries ORPHANS only: a configured model whose provider
has no group in the picker. Those would otherwise render nowhere.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.resolve()
UI_JS_PATH = REPO_ROOT / "static" / "ui.js"
NODE = shutil.which("node")

pytestmark = pytest.mark.skipif(NODE is None, reason="node not on PATH")


_RENDER_DRIVER = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[2], 'utf8');
const payload = JSON.parse(process.argv[3]);

function extractFunc(name) {
  const re = new RegExp('function\\s+' + name + '\\s*\\(');
  const start = src.search(re);
  if (start < 0) throw new Error('not found: ' + name);
  let i = src.indexOf('{', start), depth = 0;
  for (let j = i; j < src.length; j++) {
    if (src[j] === '{') depth++;
    else if (src[j] === '}') { depth--; if (depth === 0) { i = j; break; } }
  }
  return src.slice(start, i + 1);
}

class El {
  constructor(tag) {
    this.tagName = tag.toUpperCase(); this.children = []; this.dataset = {};
    this._cls = ''; this.value = ''; this.textContent = ''; this._html = '';
    this.style = {}; this.label = '';
  }
  set className(v) { this._cls = v; } get className() { return this._cls; }
  set innerHTML(v) { this._html = v; if (v === '') this.children = []; }
  get innerHTML() { return this._html; }
  appendChild(c) { this.children.push(c); return c; }
  insertBefore(c) { this.children.push(c); return c; }
  removeChild(c) { this.children = this.children.filter(x => x !== c); }
  querySelector(sel) {
    if (sel === '.model-search-input') {
      const i = new El('input');
      i.value = ''; i._listeners = {}; i.addEventListener = () => {};
      i.focus = () => {}; i.select = () => {};
      return i;
    }
    if (sel === '.model-search-clear' || sel === '.model-custom-input'
        || sel === '.model-custom-btn') {
      const b = new El('button'); b.addEventListener = () => {}; b.focus = () => {};
      return b;
    }
    return null;
  }
  querySelectorAll(sel) {
    const out = [];
    const walk = (n) => {
      for (const c of n.children) {
        if (sel === 'optgroup' && c.tagName === 'OPTGROUP') out.push(c);
        walk(c);
      }
    };
    walk(this);
    return out;
  }
  addEventListener() {}
  get classList() { return { contains: () => false, add() {}, remove() {}, toggle() {} }; }
}

global.document = {
  createElement: (t) => new El(t),
  createDocumentFragment: () => new El('fragment'),
  baseURI: 'http://127.0.0.1:8787/',
};
global.window = { _configuredModelBadges: {}, __modelGroupForceOpenByPicker: {} };
global.globalThis.window = global.window;
global.CSS = { escape: (s) => s };
global.requestAnimationFrame = (fn) => fn();
global.Event = class { constructor(t) { this.type = t; } };

global.esc = (s) => String(s == null ? '' : s);
global.t = () => '';
global.li = () => '';
global.getModelLabel = (id) => String(id);
global.selectModelFromDropdown = () => {};
global.closeModelDropdown = () => {};
global._positionModelDropdown = () => {};
global._readModelOverflowData = () => [];
global._appendOverflowOptionsToGroup = () => 0;
global._providerFromModelValue = (v) => {
  const s = String(v || '');
  if (s.startsWith('@') && s.includes(':')) return s.slice(1, s.indexOf(':'));
  return '';
};
global._getOptionProviderId = (opt) =>
  (opt && opt.parentNode && opt.parentNode.dataset && opt.parentNode.dataset.provider) || '';
global._modelStateForSelect = (sel, id) => ({ model: id || '', model_provider: null });

for (const name of ['_normalizeConfiguredModelKey', '_isEquivalentConfiguredModelEntry',
                    '_getConfiguredModelBadge', '_modelPickerOptionIdentity',
                    '_deduplicateModelPickerOptions', 'renderModelDropdown']) {
  eval(extractFunc(name));
}

const sel = new El('select');
sel.value = payload.selectedValue || '';
for (const g of payload.groups) {
  const og = new El('optgroup');
  og.label = g.provider;
  og.dataset.provider = g.provider_id;
  for (const id of g.models) {
    const o = new El('option');
    o.value = id; o.textContent = id; o.parentNode = og;
    og.appendChild(o);
  }
  sel.appendChild(og);
}
const dd = new El('div');
global.$ = (id) => (id === 'modelSelect' ? sel : dd);
window._configuredModelBadges = payload.configuredBadges || {};

renderModelDropdown({ dropdownId: 'composerModelDropdown', selectId: 'modelSelect' });

let current = null;
const groups = [];
const counts = {};
const visit = (n) => {
  for (const c of n.children) {
    const cls = String(c._cls || '').split(/\s+/);
    if (cls.includes('model-group')) {
      current = { heading: c.textContent, rows: [] };
      groups.push(current);
    } else if (cls.includes('model-opt')) {
      const m = String(c._html || '').match(/model-opt-id">([^<]*)</);
      const id = m ? m[1] : '';
      const badged = /model-opt-badge--(primary|fallback)/.test(String(c._html || ''));
      if (current) current.rows.push({ id, badged });
      counts[id] = (counts[id] || 0) + 1;
      continue;
    }
    visit(c);
  }
};
visit(dd);
process.stdout.write(JSON.stringify({ groups, counts }));
"""


def _render(tmp_path, payload):
    driver = tmp_path / "render_driver.js"
    driver.write_text(_RENDER_DRIVER, encoding="utf-8")
    assert NODE is not None
    result = subprocess.run(
        [NODE, str(driver), str(UI_JS_PATH), json.dumps(payload)],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


_TWO_ACCOUNT_PAYLOAD = {
    "groups": [
        {
            "provider": "AWS Bedrock",
            "provider_id": "bedrock",
            "models": [
                "@bedrock:us.anthropic.claude-opus-5",
                "@bedrock:us.anthropic.claude-sonnet-5",
                "@bedrock:us.anthropic.claude-fable-5-1",
            ],
        },
        {
            "provider": "Bedrock: Personal Claude + GPT",
            "provider_id": "bedrock-personal",
            "models": [
                "@bedrock-personal:us.anthropic.claude-opus-5",
                "@bedrock-personal:us.anthropic.claude-sonnet-5",
                "@bedrock-personal:us.openai.gpt-6-astra",
            ],
        },
    ],
    "configuredBadges": {
        "@bedrock:us.anthropic.claude-opus-5": {
            "role": "primary", "label": "Primary", "provider": "bedrock",
        },
        "@bedrock:us.anthropic.claude-sonnet-5": {
            "role": "fallback", "label": "Fallback 1", "provider": "bedrock",
        },
        "@bedrock-personal:us.anthropic.claude-opus-5": {
            "role": "fallback", "label": "Fallback 2", "provider": "bedrock-personal",
        },
        "@bedrock-personal:us.anthropic.claude-sonnet-5": {
            "role": "fallback", "label": "Fallback 3", "provider": "bedrock-personal",
        },
    },
    "selectedValue": "@bedrock:us.anthropic.claude-opus-5",
}


def test_badged_model_still_renders_inside_its_provider_group(tmp_path):
    """A Primary/Fallback badge must not remove the row from its own group."""
    rendered = _render(tmp_path, _TWO_ACCOUNT_PAYLOAD)
    by_provider = {
        g["heading"]: [r["id"] for r in g["rows"]]
        for g in rendered["groups"]
        if g["rows"]
    }
    personal = next(
        (rows for head, rows in by_provider.items() if "Personal" in head), None
    )
    assert personal is not None, rendered
    assert "@bedrock-personal:us.anthropic.claude-opus-5" in personal
    assert "@bedrock-personal:us.anthropic.claude-sonnet-5" in personal
    assert "@bedrock-personal:us.openai.gpt-6-astra" in personal


def test_group_row_count_matches_its_header_count(tmp_path):
    """The header count and the rendered rows must agree.

    The header is built from the <optgroup> length, so pulling badged rows out
    of the group made every group under-render against its own advertised count.
    """
    rendered = _render(tmp_path, _TWO_ACCOUNT_PAYLOAD)
    for group in _TWO_ACCOUNT_PAYLOAD["groups"]:
        expected = len(group["models"])
        match = next(
            (
                g for g in rendered["groups"]
                if g["rows"] and group["provider"].split(":")[0] in g["heading"]
            ),
            None,
        )
        assert match is not None, (group["provider"], rendered)
        assert len(match["rows"]) == expected, (group["provider"], match)


def test_each_model_renders_exactly_once(tmp_path):
    """No model appears both in a pinned section and in its provider group."""
    rendered = _render(tmp_path, _TWO_ACCOUNT_PAYLOAD)
    dupes = {k: v for k, v in rendered["counts"].items() if v > 1 and k}
    assert dupes == {}, dupes


def test_badge_is_still_shown_on_the_in_group_row(tmp_path):
    """Moving the row back into its group must not drop its badge."""
    rendered = _render(tmp_path, _TWO_ACCOUNT_PAYLOAD)
    badged = {
        r["id"] for g in rendered["groups"] for r in g["rows"] if r["badged"]
    }
    assert "@bedrock:us.anthropic.claude-opus-5" in badged
    assert "@bedrock-personal:us.anthropic.claude-sonnet-5" in badged


def test_orphan_configured_model_still_renders(tmp_path):
    """A configured model whose provider has NO group must remain reachable.

    This is the only reason the pinned section survives. Without it the model
    renders nowhere and the user cannot select it.
    """
    payload = {
        "groups": [
            {
                "provider": "Primary",
                "provider_id": "custom:primary",
                "models": ["@custom:primary:model-a"],
            }
        ],
        "configuredBadges": {
            "@custom:backup:model-a": {
                "role": "fallback",
                "label": "Fallback 1",
                "provider": "custom:backup",
            }
        },
        "selectedValue": "@custom:primary:model-a",
    }
    rendered = _render(tmp_path, payload)
    all_ids = [r["id"] for g in rendered["groups"] for r in g["rows"]]
    assert "@custom:backup:model-a" in all_ids, rendered


def test_no_pinned_duplicate_for_a_grouped_provider(tmp_path):
    """The pinned section must stay empty when every badge has a real group."""
    rendered = _render(tmp_path, _TWO_ACCOUNT_PAYLOAD)
    headings = [g["heading"] for g in rendered["groups"] if g["rows"]]
    assert not any(h == "Configured" for h in headings), headings
