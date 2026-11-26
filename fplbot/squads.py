"""Builds the three public teams (SAFE / BALANCED / BOLD) from scratch.

Each is the best 15-man FPL squad within the budget, with the FPL rules:
2 GK, 5 DEF, 5 MID, 3 FWD, max 3 players per club, and a legal starting XI
(1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD). Solved exactly with a free optimiser (PuLP).

Styles (how each player is scored before choosing):
 - SAFE:     expected points, but players who might not play are left out and
             widely-owned, regular starters are preferred.
 - BALANCED: plain expected points.
 - BOLD:     the most-owned player is left out and low-ownership players get a boost.
The "Expected" shown in posts is always the plain expected points.
"""
import pulp

from . import model as fm

SQUAD = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}


def _owned(p):
    return float(p.get("selected_by_percent") or 0)


def style_scores(elements, xp, style):
    """Score every player for one style; None = not allowed in this team."""
    most_owned = max(elements.values(), key=_owned)["id"]
    out = {}
    for pid, p in elements.items():
        x = xp[pid]
        chance = p.get("chance_of_playing_next_round")
        if p.get("status") in ("u", "n"):
            continue
        if style == "safe":
            if chance is not None and chance < 100:
                continue
            out[pid] = x * (0.85 + 0.15 * min(1.0, _owned(p) / 20))
        elif style == "bold":
            if pid == most_owned:
                continue
            out[pid] = x * (1.25 if _owned(p) < 10 else 1.0)
        else:
            out[pid] = x
    return out


def build(elements, xp, style, budget=100.0, min_spend=0.0):
    """Best squad for one style. Returns dict with squad, xi, bench, captain, vice, cost."""
    score = style_scores(elements, xp, style)
    ids = list(score)
    m = pulp.LpProblem(f"squad_{style}", pulp.LpMaximize)
    x = {i: pulp.LpVariable(f"x_{i}", cat="Binary") for i in ids}   # in squad
    s = {i: pulp.LpVariable(f"s_{i}", cat="Binary") for i in ids}   # starts
    c = {i: pulp.LpVariable(f"c_{i}", cat="Binary") for i in ids}   # captain
    # starters count fully, captain twice, bench a little (so it isn't junk)
    m += pulp.lpSum(score[i] * (s[i] + c[i] + 0.1 * x[i]) for i in ids)
    m += pulp.lpSum(elements[i]["now_cost"] * x[i] for i in ids) <= int(round(budget * 10))
    if min_spend:  # use the budget: keeps premium players in the teams
        m += pulp.lpSum(elements[i]["now_cost"] * x[i] for i in ids) >= int(round(min_spend * 10))
    for pos, n in SQUAD.items():
        m += pulp.lpSum(x[i] for i in ids if elements[i]["element_type"] == pos) == n
        m += pulp.lpSum(s[i] for i in ids if elements[i]["element_type"] == pos) >= XI_MIN[pos]
        m += pulp.lpSum(s[i] for i in ids if elements[i]["element_type"] == pos) <= XI_MAX[pos]
    m += pulp.lpSum(s.values()) == 11
    m += pulp.lpSum(c.values()) == 1
    for i in ids:
        m += s[i] <= x[i]
        m += c[i] <= s[i]
    for club in {elements[i]["team"] for i in ids}:
        m += pulp.lpSum(x[i] for i in ids if elements[i]["team"] == club) <= 3
    m.solve(pulp.PULP_CBC_CMD(msg=0, timeLimit=60))
    if pulp.LpStatus[m.status] != "Optimal":
        raise RuntimeError(f"no {style} squad found ({pulp.LpStatus[m.status]})")
    squad = [elements[i] for i in ids if x[i].value() > 0.5]
    xi = [elements[i] for i in ids if s[i].value() > 0.5]
    cap = next(elements[i] for i in ids if c[i].value() > 0.5)
    vice = max((p for p in xi if p is not cap), key=lambda p: xp[p["id"]])
    bench_out = [p for p in squad if p not in xi]
    bench = [p for p in bench_out if p["element_type"] == 1] + \
        sorted((p for p in bench_out if p["element_type"] != 1), key=lambda p: -xp[p["id"]])
    formation = "-".join(str(sum(p["element_type"] == k for p in xi)) for k in (2, 3, 4))
    return {"style": style, "squad": squad, "xi": xi, "bench": bench, "captain": cap, "vice": vice,
            "cost": sum(p["now_cost"] for p in squad) / 10, "formation": formation,
            "expected": sum(xp[p["id"]] for p in xi) + xp[cap["id"]]}


def chip_tip(fixtures, teams_count, gw, horizon=6):
    """Generic chip timing from upcoming double/blank gameweeks."""
    from collections import Counter
    per_gw = {}
    for f in fixtures:
        g = f.get("event")
        if g and gw <= g < gw + horizon:
            per_gw.setdefault(g, Counter())
            per_gw[g][f["team_h"]] += 1
            per_gw[g][f["team_a"]] += 1
    for g in range(gw, gw + horizon):
        cnt = per_gw.get(g, {})
        doubles = sum(1 for v in cnt.values() if v >= 2)
        blanks = teams_count - len(cnt) if cnt else 0
        if doubles >= 4:
            if g == gw:
                return f"play Triple Captain or Bench Boost this week – double gameweek for {doubles} teams."
            return f"save them – Triple Captain looks better in GW{g} (double gameweek)."
        if blanks >= 4:
            if g == gw:
                return f"Free Hit this week – {blanks} teams have no game."
            return f"save them – Free Hit looks useful in GW{g} (blank gameweek)."
    return "save them – no double or blank gameweek in the next few weeks."
