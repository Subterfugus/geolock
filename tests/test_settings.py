"""Desktop settings: analyst model and effort choices, and the 0.3 -> 0.4 map default."""
import json

import pytest

from geolock.desktop.library import DEFAULT_SETTINGS, Settings


def test_model_and_effort_are_checked(tmp_path):
    s = Settings(tmp_path / "settings.json")
    assert s["claude_model"] == "" and s["chatgpt_effort"] == "" and s["map_style"] == "streets"
    v = s.update({"claude_model": " opus ", "claude_effort": "High", "chatgpt_model": "gpt-6.1-sol",
                  "chatgpt_effort": "default"})
    assert v["claude_model"] == "opus" and v["claude_effort"] == "high"
    assert v["chatgpt_model"] == "gpt-6.1-sol" and v["chatgpt_effort"] == ""
    for bad in ({"claude_model": "--dangerously-skip-permissions"}, {"claude_model": "a b"},
                {"chatgpt_effort": "ultra"}):
        with pytest.raises(ValueError):
            s.update(bad)
    assert Settings(tmp_path / "settings.json")["claude_model"] == "opus"  # saved


def test_old_offline_default_moves_to_streets(tmp_path):
    p = tmp_path / "settings.json"
    old = {k: v for k, v in DEFAULT_SETTINGS.items() if not k.startswith(("claude", "chatgpt", "settings"))}
    p.write_text(json.dumps(dict(old, map_style="offline", theme="dark")))
    s = Settings(p)
    assert s["map_style"] == "streets" and s["theme"] == "dark" and s["settings_rev"] == 2
    s.update({"map_style": "offline"})  # a choice made in 0.4 sticks
    assert Settings(p)["map_style"] == "offline"
    assert s.update({"settings_rev": 1})["settings_rev"] == 2
