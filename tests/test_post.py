import datetime as dt
from collections import Counter

import pytest

import post
from fplbot import squads
from tests.fake_fpl import fake_fpl

CFG = {"budget": 100.0, "min_spend": 97.0, "lookahead_gws": 3, "lineup_hours_before": 30, "reminder_hours_before": 2.5,
       "timezone": "Europe/Dublin"}


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
    monkeypatch.setattr(post.api, "live", lambda g: live)


def set_deadline(boot, gw, hours):
    t = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    next(e for e in boot["events"] if e["id"] == gw)["deadline_time"] = t.isoformat().replace("+00:00", "Z")


def test_three_teams_follow_fpl_rules():
    boot, fixtures, *_ = fake_fpl()
    elements, xp = post.expected_points(boot, fixtures, 13, CFG)
    boot["elements"][0]["chance_of_playing_next_round"] = 50
    most = max(elements.values(), key=lambda p: float(p["selected_by_percent"]))["id"]
    for style in ("safe", "balanced", "bold"):
        t = squads.build(elements, xp, style, 100.0, 97.0)
        assert len(t["squad"]) == 15 and len(t["xi"]) == 11 and 97.0 <= t["cost"] <= 100.0
        assert sum(p["now_cost"] for p in t["bench"]) / 10 <= 18.0 + 1e-9
        assert Counter(p["element_type"] for p in t["squad"]) == {1: 2, 2: 5, 3: 5, 4: 3}
        assert max(Counter(p["team"] for p in t["squad"]).values()) <= 3
        f = Counter(p["element_type"] for p in t["xi"])
        assert f[1] == 1 and 3 <= f[2] <= 5 and 2 <= f[3] <= 5 and 1 <= f[4] <= 3
        assert t["captain"] in t["xi"] and t["vice"] in t["xi"] and t["vice"] is not t["captain"]
        if style == "bold":
            assert most not in {p["id"] for p in t["squad"]}
        if style == "safe":
            assert boot["elements"][0]["id"] not in {p["id"] for p in t["squad"]}


def test_lineup_then_reminder_then_review(sandbox, monkeypatch):
    data = fake_fpl(deadline_hours=20)
    boot = data[0]
    wire(monkeypatch, data)
    post.main([])
    lineup = sandbox[-1]
    print(lineup)
    assert lineup.startswith("<b>⚽ FPL Gameweek 13 – our 3 teams</b>\nDeadline: <b>")
    for k in ("<b>🟢 SAFE</b> · ", "<b>🟡 BALANCED</b> · ", "<b>🔴 BOLD</b> · ", "\nGK ", "\nDEF ", "\nMID ",
              "\nFWD ", "(C)", "(V)", "Bench: ", "<i>Expected: ", "<b>🩹 Team news</b>", "<b>💡 Chips:</b>",
              "Unofficial – not linked to the Premier League or FPL."):
        assert k in lineup, k
    assert lineup.count("<i>Expected: ") == 3 and " – no " in lineup
    sandbox.clear()
    post.main([])
    assert sandbox == []                                    # lineup only once

    # 2 hours before the deadline: one of the SAFE starters becomes doubtful
    state = post.load_state()
    starter = state["gw"]["13"]["teams"]["safe"]["xi"][3]
    el = next(e for e in boot["elements"] if e["id"] == starter)
    el["chance_of_playing_next_round"], el["status"] = 75, "d"
    set_deadline(boot, 13, 2)
    post.main([])
    reminder = sandbox[-1]
    print(reminder)
    assert reminder.startswith("<b>⏰ FPL deadline in 2 hours</b>")
    assert f"{el['web_name']} <b>doubtful</b> (75%) – check your bench order" in reminder
    assert "Captain still: <b>" in reminder or "Captain: switch to" in reminder
    assert reminder.rstrip().endswith("Don't forget to save your team!")

    # gameweek 13 finishes -> review
    sandbox.clear()
    for e in boot["events"]:
        e["finished"] = e["data_checked"] = e["id"] <= 13
        e["is_current"], e["is_next"] = e["id"] == 13, e["id"] == 14
    set_deadline(boot, 14, 100)
    post.main([])
    review = sandbox[-1]
    print(review)
    assert review.startswith("<b>📊 GW13 review – how our teams did</b>")
    for k in ("🟢 Safe: <b>", "🟡 Balanced: <b>", "🔴 Bold: <b>", "Average manager: 54 pts",
              "<b>✅ Best call:</b>", "<b>❌ Worst call:</b>", "<b>Season so far:</b> Safe team is ahead of the average in"):
        assert k in review, k


def test_auto_sub_and_vice_captain():
    t = {"xi": [1, 2, 3], "bench": [10, 11], "captain": 2, "vice": 3}
    pts = {1: 2, 2: 0, 3: 6, 10: 1, 11: 4}
    mins = {1: 90, 2: 0, 3: 90, 10: 90, 11: 90}
    # captain 2 didn't play: outfield sub 11 comes in (keeper 10 can't), vice 3 is doubled
    assert post.team_points(t, pts, mins, keepers={1, 10}) == 2 + 6 + 4 + 6


def test_fpl_forecast_is_blended_in():
    boot, fixtures, *_ = fake_fpl()
    _, ours = post.expected_points(boot, fixtures, 13, CFG | {"fpl_forecast_weight": 0.6})
    assert ours
    boot["elements"][0]["ep_next"] = "10.0"
    _, blended = post.expected_points(boot, fixtures, 13, CFG | {"fpl_forecast_weight": 0.6})
    i = boot["elements"][0]["id"]
    assert blended[i] == pytest.approx(0.6 * 10.0 + 0.4 * ours[i])
