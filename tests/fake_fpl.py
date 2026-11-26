"""FPL helper rehearsal with pretend FPL data."""
import datetime as dt
import random









def fake_fpl(deadline_hours=20):
    rnd = random.Random(3)
    now = dt.datetime.now(dt.timezone.utc)
    teams = [{"id": t, "name": f"Club{t}", "short_name": f"C{t:02d}"} for t in range(1, 21)]
    elements, pid = [], 1
    for t in range(1, 21):
        for pos, n in ((1, 2), (2, 5), (3, 5), (4, 3)):
            for _ in range(n):
                elements.append({"id": pid, "web_name": f"P{pid}", "team": t, "element_type": pos,
                                 "now_cost": rnd.randint(40, 120), "form": f"{rnd.uniform(0, 8):.1f}",
                                 "points_per_game": f"{rnd.uniform(1, 7):.1f}", "minutes": rnd.randint(0, 1080),
                                 "starts": rnd.randint(0, 12), "status": "a", "chance_of_playing_next_round": None,
                                 "goals_scored": rnd.randint(0, 9), "assists": rnd.randint(0, 6),
                                 "clean_sheets": rnd.randint(0, 6),
                                 "selected_by_percent": f"{rnd.uniform(0, 40):.1f}", "news": ""})
                pid += 1
    events = []
    for g in range(1, 39):
        deadline = now + dt.timedelta(hours=deadline_hours + (g - 13) * 168)
        events.append({"id": g, "deadline_time": deadline.isoformat().replace("+00:00", "Z"),
                       "finished": g <= 12, "data_checked": g <= 12, "is_current": g == 12, "is_next": g == 13,
                       "average_entry_score": 54})
    chips = [{"name": n, "start_event": a, "stop_event": b} for n in ("wildcard", "freehit", "bboost", "3xc")
             for a, b in ((1, 19), (20, 38))]
    fixtures = []
    for g in range(13, 16):
        order = list(range(1, 21))
        rnd.shuffle(order)
        for i in range(0, 20, 2):
            fixtures.append({"event": g, "team_h": order[i], "team_a": order[i + 1],
                             "team_h_difficulty": rnd.randint(2, 5), "team_a_difficulty": rnd.randint(2, 5)})
    fixtures.append({"event": 15, "team_h": 1, "team_a": 2, "team_h_difficulty": 2, "team_a_difficulty": 3})  # double GW
    boot = {"elements": elements, "teams": teams, "events": events, "chips": chips}
    # a legal squad: 2 GK, 5 DEF, 5 MID, 3 FWD from 15 different clubs
    need, squad = {1: 2, 2: 5, 3: 5, 4: 3}, []
    for e in elements:
        if need[e["element_type"]] and e["team"] not in {elements[s - 1]["team"] for s in squad}:
            squad.append(e["id"]); need[e["element_type"]] -= 1
    history = {"current": [{"event": g, "points": 50 + g, "total_points": 600, "overall_rank": 500000 - g * 1000,
                            "event_transfers": 1 if g % 3 else 0, "event_transfers_cost": 0} for g in range(1, 13)],
               "chips": [{"name": "wildcard", "event": 5}]}
    picks = {"active_chip": None, "entry_history": {"bank": 15},
             "picks": [{"element": s, "is_captain": i == 0} for i, s in enumerate(squad)]}
    live = {"elements": [{"id": e["id"], "stats": {"total_points": e["id"] % 13, "minutes": 90}} for e in elements]}
    return boot, fixtures, history, picks, live


