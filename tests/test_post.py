import pytest

import post
from fplbot import model as fm
from tests.fake_fpl import fake_fpl


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(post, "STATE", tmp_path / "state.json")
    sent = []
    monkeypatch.setattr(post, "send", lambda text, dry_run=False: sent.append(text) or True)
    return sent


def wire(monkeypatch, data):
    boot, fixtures, history, picks, live = data
    monkeypatch.setattr(post.api, "bootstrap", lambda: boot)
    monkeypatch.setattr(post.api, "fixtures", lambda: fixtures)
    monkeypatch.setattr(post.api, "history", lambda t: history)
    monkeypatch.setattr(post.api, "picks", lambda t, g: picks)
    monkeypatch.setattr(post.api, "live", lambda g: live)


def test_posts_result_then_lineup_once(sandbox, monkeypatch):
    wire(monkeypatch, fake_fpl())
    assert post.main([]) == 0
    print("\n\n".join(sandbox))
    result, lineup = sandbox
    assert result.startswith("📊 <b>EdgeFinder Fantasy – Gameweek 12 result</b>") and "average 54" in result
    assert lineup.startswith("⚽ <b>EdgeFinder Fantasy – Gameweek 13</b>")
    assert lineup.count(" pts\n") == 11                       # 11 players, each with estimated points
    for k in ("<b>1 FT:</b>", "<b>2 FT:</b>", "<b>3 FT:</b>", "Taking a -4 hit?", "Top buys by position"):
        assert k in lineup
    assert "5879611" not in lineup and "5879611" not in result  # team id never shown
    sandbox.clear()
    post.main([])
    assert sandbox == []                                       # nothing twice


def test_estimate_check_after_lineup(sandbox, monkeypatch):
    data = fake_fpl()
    wire(monkeypatch, data)
    post.main([])
    sandbox.clear()
    boot = data[0]
    for e in boot["events"]:  # GW13 is now finished
        e["finished"] = e["data_checked"] = e["id"] <= 13
        e["is_current"], e["is_next"] = e["id"] == 13, e["id"] == 14
    data[2]["current"].append({"event": 13, "points": 70, "overall_rank": 1, "event_transfers": 0,
                               "event_transfers_cost": 0})
    post.main([])
    assert any("Estimate check:" in m and "Our captain:" in m for m in sandbox)


def test_transfer_tiers_follow_the_rules():
    boot, fixtures, history, picks, live = fake_fpl()
    elements = {e["id"]: e for e in boot["elements"]}
    tfix = fm.team_fixtures(fixtures, {13, 14, 15})
    xp3 = {i: sum(fm.expected_points(e, tfix, [13, 14, 15], 12).values()) for i, e in elements.items()}
    squad = [p["element"] for p in picks["picks"]]
    plans = fm.transfer_plans(squad, elements, xp3, 1.5, {"hit_threshold": 4, "min_transfer_gain": 1})
    for k in (1, 2, 3):
        assert len(plans[k]) <= k
        assert len({m["out"] for m in plans[k]}) == len(plans[k])   # never sell the same player twice
    gains = [sum(m["gain"] for m in plans[k]) for k in (1, 2, 3)]
    assert gains == sorted(gains)                                    # more transfers never plan less gain
