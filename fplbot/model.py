"""FPL advice maths (section 10). Simple and explainable on purpose.

Expected points (xP) for a player in one gameweek =
   base points per game  (half recent form, half season average)
 x fixture difficulty    (easy fixture = more points, hard = fewer)
 x home/away             (small boost at home)
 x chance he starts      (from his starts and minutes so far)
 x chance he is fit      (from FPL's injury flags)
 summed over his fixtures that week (0 in a blank week, 2 in a double week).
"""
from collections import Counter

FDR_MULT = {1: 1.25, 2: 1.1, 3: 1.0, 4: 0.85, 5: 0.7}
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}
CHIP_NAMES = {"wildcard": "Wildcard", "freehit": "Free Hit", "3xc": "Triple Captain", "bboost": "Bench Boost"}


def team_fixtures(fixtures, gws):
    """{team_id: {gw: [(difficulty, is_home, opponent_id)]}} for the given gameweeks."""
    out = {}
    for f in fixtures:
        if f.get("event") not in gws:
            continue
        out.setdefault(f["team_h"], {}).setdefault(f["event"], []).append((f["team_h_difficulty"], True, f["team_a"]))
        out.setdefault(f["team_a"], {}).setdefault(f["event"], []).append((f["team_a_difficulty"], False, f["team_h"]))
    return out


def availability(p):
    chance = p.get("chance_of_playing_next_round")
    if chance is not None:
        return chance / 100
    return {"a": 1.0, "d": 0.5}.get(p.get("status"), 0.0)


def expected_points(p, tfix, gws, finished_gws, form_weight=0.5):
    # form = recent weeks, points_per_game = whole season; less form = steadier picks
    base = form_weight * float(p.get("form") or 0) + (1 - form_weight) * float(p.get("points_per_game") or 0)
    if finished_gws:
        share = max(p.get("starts", 0) / finished_gws, p.get("minutes", 0) / (90 * finished_gws))
        share = min(1.0, share)
    else:
        share = 0.5
    fit_now = availability(p)
    out = {}
    for i, gw in enumerate(gws):
        fit = 0.0 if p.get("status") in ("u", "n") else min(1.0, fit_now + 0.25 * i)  # injuries heal
        pts = sum(base * FDR_MULT.get(d, 1.0) * (1.08 if home else 0.95)
                  for d, home, _ in tfix.get(p["team"], {}).get(gw, []))
        out[gw] = pts * share * fit
    return out


def best_xi(squad, xp_next):
    """Pick the best legal starting 11 (1 GK, 3-5 DEF, 2-5 MID, 1-3 FWD) and bench order."""
    by = lambda pos: sorted((p for p in squad if p["element_type"] == pos), key=lambda p: xp_next[p["id"]], reverse=True)
    gks = by(1)
    xi = gks[:1]
    for pos, n in ((2, 3), (3, 2), (4, 1)):
        xi += by(pos)[:n]
    maxes = {2: 5, 3: 5, 4: 3}
    rest = sorted((p for p in squad if p["element_type"] != 1 and p not in xi), key=lambda p: xp_next[p["id"]], reverse=True)
    for p in rest:
        if len(xi) == 11:
            break
        if sum(q["element_type"] == p["element_type"] for q in xi) < maxes[p["element_type"]]:
            xi.append(p)
    bench = gks[1:] + [p for p in rest if p not in xi]
    return xi, bench


def suggest_transfers(squad_ids, elements, xp3, bank, free_transfers, cfg):
    """Greedy: best single swap, then the best next one, up to max_transfers.
    A free transfer must gain > min_transfer_gain; a paid one (-4) must gain > hit_threshold."""
    current, bank_now, moves = set(squad_ids), bank, []
    for n in range(cfg["max_transfers"]):
        clubs = Counter(elements[i]["team"] for i in current)
        best = None
        for out_id in current:
            po = elements[out_id]
            budget = bank_now + po["now_cost"] / 10
            for pin in elements.values():
                if pin["id"] in current or pin["element_type"] != po["element_type"]:
                    continue
                if pin["now_cost"] / 10 > budget or pin.get("status") != "a":
                    continue
                if clubs[pin["team"]] - (po["team"] == pin["team"]) >= 3:
                    continue  # max 3 players per club
                gain = xp3[pin["id"]] - xp3[out_id]
                if best is None or gain > best["gain"]:
                    best = {"out": out_id, "in": pin["id"], "gain": gain,
                            "bank_after": budget - pin["now_cost"] / 10}
        if not best:
            break
        hit = n >= free_transfers
        if best["gain"] <= (cfg["hit_threshold"] if hit else cfg["min_transfer_gain"]):
            break
        best["hit"] = hit
        moves.append(best)
        current = (current - {best["out"]}) | {best["in"]}
        bank_now = best["bank_after"]
    return moves, current


def free_transfers_estimate(history_current, chips):
    """Free transfers for the next gameweek, worked out from your history:
    +1 each week, max 5 saved, Wildcard/Free Hit weeks don't use any."""
    chip_by_gw = {c["event"]: c["name"] for c in chips}
    rows = sorted(history_current, key=lambda h: h["event"])
    ft = 1
    for h in rows[1:]:  # your first gameweek had unlimited transfers
        if chip_by_gw.get(h["event"]) not in ("wildcard", "freehit"):
            ft = max(0, ft - h["event_transfers"])
        ft = min(5, ft + 1)
    return max(1, ft) if rows else 1


def chip_halves(boot):
    """Chip windows from FPL's own data; falls back to GW1-19 / GW20-38."""
    halves = {}
    for c in boot.get("chips") or []:
        if c.get("start_event") and c.get("stop_event"):
            halves.setdefault(c["name"], []).append((c["start_event"], c["stop_event"]))
    if not halves:
        halves = {n: [(1, 19), (20, 38)] for n in CHIP_NAMES}
    return halves


def chips_left(boot, used_chips, gw):
    """Chips still available in the half that contains `gw`, plus that half's last GW."""
    left, stop = [], None
    for name, windows in chip_halves(boot).items():
        win = next(((a, b) for a, b in windows if a <= gw <= b), None)
        if not win:
            continue
        stop = win[1] if stop is None else min(stop, win[1])
        used = any(c["name"] == name and win[0] <= c["event"] <= win[1] for c in used_chips)
        if not used:
            left.append(name)
    order = ["wildcard", "freehit", "3xc", "bboost"]
    return sorted(left, key=lambda n: order.index(n) if n in order else 9), stop


def chip_advice(squad, xi, xp_by_player, tfix, gws, left, elements):
    """Returns (chip or None, advice text, confidence)."""
    gw = gws[0]
    nfix = lambda p, g: len(tfix.get(p["team"], {}).get(g, []))
    blanks = sum(nfix(p, gw) == 0 for p in squad)
    playing = len(squad) - blanks
    doubles = sum(nfix(p, gw) >= 2 for p in squad)
    top = max(squad, key=lambda p: xp_by_player[p["id"]][gw])
    troubles = [p for p in squad if availability(p) < 0.75 or float(p.get("form") or 0) < 2.0
                or (sum(d for g in gws for d, *_ in tfix.get(p["team"], {}).get(g, [])) /
                    max(1, sum(nfix(p, g) for g in gws))) >= 4]

    if "freehit" in left and blanks >= 4:
        conf = "High" if playing < 11 else "Medium"
        return "freehit", f"PLAY Free Hit: {blanks} of your players have no game this week.", conf
    if "3xc" in left and nfix(top, gw) >= 2:
        return "3xc", f"PLAY Triple Captain on {top['web_name']}: two games this week.", "High"
    if "bboost" in left and blanks == 0 and doubles >= 8:
        return "bboost", f"PLAY Bench Boost: all 15 play and {doubles} have two games.", "High"
    if "wildcard" in left and len(troubles) >= 4:
        names = ", ".join(p["web_name"] for p in troubles[:6])
        return "wildcard", f"CONSIDER Wildcard: {len(troubles)} players are injured, out of form or have hard fixtures ({names}).", "Medium"
    # Nothing this week: look ahead for a better moment
    for g in gws[1:]:
        best3 = sorted(squad, key=lambda p: xp_by_player[p["id"]][gw], reverse=True)[:3]
        dbl = [p for p in best3 if nfix(p, g) >= 2]
        if "3xc" in left and dbl:
            return None, f"SAVE. Triple Captain is better in GW{g} (double gameweek for {dbl[0]['web_name']}).", "Medium"
        if "freehit" in left and sum(nfix(p, g) == 0 for p in squad) >= 4:
            return None, f"SAVE. Free Hit looks useful in GW{g} (blank gameweek for several of your players).", "Medium"
    if "bboost" in left and blanks == 0 and doubles >= 3:
        return "bboost", f"CONSIDER Bench Boost: all 15 play and {doubles} have two games.", "Low"
    return None, "SAVE. No chip gives a clear advantage this week.", "Medium"


# ------------------------------------------------------------ group-bot extras
def difficulty_word(d):
    return {1: "very easy", 2: "easy", 3: "medium", 4: "hard", 5: "very hard"}.get(d, "medium")


def reason(p, tfix, gw, teams):
    """One short, factual line explaining a player's estimated points."""
    fx = tfix.get(p["team"], {}).get(gw, [])
    if not fx:
        return "no game this gameweek"
    games = ", ".join(f"{'H' if home else 'A'} v {teams[opp]['short_name'] if 'short_name' in teams[opp] else teams[opp]['name']} "
                      f"({difficulty_word(d)})" for d, home, opp in fx)
    bits = [f"form {float(p.get('form') or 0):.1f}"]
    if p["element_type"] in (1, 2):
        cs = p.get("clean_sheets", 0)
        bits.append(f"{cs} clean sheet{'' if cs == 1 else 's'}")
        if p["element_type"] == 2 and (p.get("goals_scored", 0) + p.get("assists", 0)):
            bits.append(f"{p.get('goals_scored', 0)}G {p.get('assists', 0)}A")
    else:
        bits.append(f"{p.get('goals_scored', 0)}G {p.get('assists', 0)}A")
    chance = p.get("chance_of_playing_next_round")
    if chance is not None and chance < 100:
        bits.append(f"⚠️ {chance}% chance to play")
    if len(fx) > 1:
        bits.append("DOUBLE GAMEWEEK")
    return f"{games} · " + " · ".join(bits)


def transfer_plans(squad_ids, elements, xp3, bank, cfg, tiers=(1, 2, 3)):
    """Best plan for each number of free transfers, worked out separately."""
    plans = {}
    for k in tiers:
        moves, _ = suggest_transfers(squad_ids, elements, xp3, bank, k,
                                     {"max_transfers": k, "hit_threshold": 999,
                                      "min_transfer_gain": cfg["min_transfer_gain"]})
        plans[k] = moves
    # Is one extra transfer worth a -4 hit on top of the 1-FT plan?
    hit_moves, _ = suggest_transfers(squad_ids, elements, xp3, bank, 1,
                                     {"max_transfers": 2, "hit_threshold": cfg["hit_threshold"],
                                      "min_transfer_gain": cfg["min_transfer_gain"]})
    plans["hit"] = hit_moves[1:] if len(hit_moves) > 1 else []
    return plans


def top_buys(elements, xp3, exclude, per_position=2, max_price=None):
    """Best expected points over the next GWs per position, for any follower's team."""
    out = {}
    for pos in (1, 2, 3, 4):
        pool = [e for e in elements.values() if e["element_type"] == pos and e["id"] not in exclude
                and e.get("status") == "a" and (max_price is None or e["now_cost"] / 10 <= max_price)]
        out[pos] = sorted(pool, key=lambda e: xp3[e["id"]], reverse=True)[:per_position]
    return out
