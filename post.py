"""Formline XI – FPL channel bot. Run: python post.py --dry-run --force

Checks every hour (GitHub Actions) and posts, each only once per gameweek:
 1. LINEUP   ~30 hours before the deadline: our 3 teams (SAFE / BALANCED / BOLD),
             team news and chip advice;
 2. REMINDER ~2 hours before the deadline: what changed since the lineup post and
             the captain check;
 3. REVIEW   after the gameweek: how each team scored vs the average, best and
             worst call, and the season record.
Only public FPL data is read. No FPL team is ever changed.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from fplbot import fpl_api as api, model as fm, squads
from fplbot.telegram import send, esc

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "state.json"
STYLES = [("safe", "🟢", "SAFE"), ("balanced", "🟡", "BALANCED"), ("bold", "🔴", "BOLD")]
FOOTER = "<i>Estimates, not guarantees. Unofficial – not linked to the Premier League or FPL.</i>"


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2, sort_keys=True))


def when(iso, tz):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)


def chance(p):
    c = p.get("chance_of_playing_next_round")
    return 100 if c is None and p.get("status") == "a" else (c if c is not None else 0)


def status_word(p):
    c, news = chance(p), str(p.get("news") or "").lower()
    if "knock" in news and c >= 75:
        return "minor knock"
    return {"i": "injured", "s": "suspended", "n": "unavailable", "u": "unavailable"}.get(p.get("status"), "doubtful")


def expected_points(boot, fixtures, gw, cfg):
    elements = {e["id"]: e for e in boot["elements"]}
    gws = [g for g in range(gw, gw + cfg["lookahead_gws"]) if g <= len(boot["events"])]
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    tfix = fm.team_fixtures(fixtures, set(gws))
    xp = {pid: fm.expected_points(e, tfix, gws, finished)[gw] for pid, e in elements.items()}
    return elements, xp


# ------------------------------------------------------------------ 1. LINEUP
def lineup_post(boot, fixtures, gw_event, cfg, tz):
    gw = gw_event["id"]
    elements, xp = expected_points(boot, fixtures, gw, cfg)
    teams = {st: squads.build(elements, xp, st, cfg["budget"]) for st, _, _ in STYLES}
    deadline = when(gw_event["deadline_time"], tz)
    most_owned = max(elements.values(), key=lambda p: float(p.get("selected_by_percent") or 0))
    nm = lambda p: esc(p["web_name"])

    L = [f"<b>⚽ FPL Gameweek {gw} – our 3 teams</b>",
         f"Deadline: <b>{deadline:%a %H:%M}</b> (Irish time)"]
    for st, icon, title in STYLES:
        t = teams[st]
        L += ["", f"<b>{icon} {title}</b> · {t['formation']} · £{t['cost']:.1f}m"]
        if st == "safe":  # the main team in full
            for pos, label in ((1, "GK"), (2, "DEF"), (3, "MID"), (4, "FWD")):
                names = []
                for p in sorted((q for q in t["xi"] if q["element_type"] == pos), key=lambda q: -xp[q["id"]]):
                    tag = " (C)" if p is t["captain"] else " (V)" if p is t["vice"] else ""
                    names.append(nm(p) + tag)
                L.append(f"{label} " + " · ".join(names))
            L.append("Bench: " + ", ".join(nm(p) for p in t["bench"]))
        else:
            extra = f" – no {nm(most_owned)}" if st == "bold" else ""
            L.append(f"Captain {nm(t['captain'])} · Vice {nm(t['vice'])}{extra}")
        L.append(f"<i>Expected: {t['expected']:.0f} pts</i>")

    # Team news: our players and widely-owned players with a doubt
    in_xi = {p["id"] for t in teams.values() for p in t["xi"]}
    in_squad = {p["id"] for t in teams.values() for p in t["squad"]}
    popular = sorted(elements.values(), key=lambda p: -float(p.get("selected_by_percent") or 0))[:20]
    news = []
    for p in {q["id"]: q for q in popular + [elements[i] for i in in_squad]}.values():
        if chance(p) >= 100:
            continue
        action = ("bench covers him" if p["id"] in in_xi else
                  "on our bench" if p["id"] in in_squad else "left out")
        news.append(f"• {nm(p)} {status_word(p)} ({chance(p)}%) – {action}")
    L += ["", "<b>🩹 Team news</b>"] + (news[:6] or ["• No injury worries for our teams"])
    L += ["", f"<b>💡 Chips:</b> {esc(squads.chip_tip(fixtures, len(boot['teams']), gw))}", "", FOOTER]

    saved = {"posted_at": dt.datetime.now(tz).isoformat(),
             "most_owned": most_owned["id"],
             "teams": {st: {"xi": [p["id"] for p in t["xi"]], "bench": [p["id"] for p in t["bench"]],
                            "captain": t["captain"]["id"], "vice": t["vice"]["id"]} for st, t in teams.items()},
             "xp": {str(i): round(xp[i], 2) for i in in_squad},
             "chance": {str(i): chance(elements[i]) for i in in_squad}}
    return "\n".join(L), saved


# ---------------------------------------------------------------- 2. REMINDER
def reminder_post(boot, gw_event, saved, tz, now):
    elements = {e["id"]: e for e in boot["elements"]}
    deadline = when(gw_event["deadline_time"], tz)
    hours = max(1, round((deadline - now.astimezone(tz)).total_seconds() / 3600))
    since = dt.datetime.fromisoformat(saved["posted_at"]).strftime("%A")
    safe = saved["teams"]["safe"]
    our_xi = {i for t in saved["teams"].values() for i in t["xi"]}
    changes = []
    for i, before in saved["chance"].items():
        p = elements.get(int(i))
        if not p:
            continue
        now_c = chance(p)
        if before < 100 <= now_c:
            changes.append(f"• {esc(p['web_name'])} now <b>fit</b> – keep him")
        elif now_c < before:
            if now_c == 0:
                changes.append(f"• {esc(p['web_name'])} <b>out</b> – " +
                               ("swap him with your bench" if int(i) in our_xi else "not in our starting teams"))
            else:
                changes.append(f"• {esc(p['web_name'])} <b>{status_word(p)}</b> ({now_c}%) – check your bench order")
    cap, vice = elements[safe["captain"]], elements[safe["vice"]]
    L = [f"<b>⏰ FPL deadline in {hours} hour{'s' if hours != 1 else ''}</b> ({deadline:%H:%M})", "",
         f"<b>Changes since {since}:</b>"] + (changes or ["• None – our teams stand as posted"]) + [""]
    if chance(cap) < 75:
        L.append(f"Captain: switch to <b>{esc(vice['web_name'])}</b> 🅲 ({esc(cap['web_name'])} is a doubt)")
    else:
        L.append(f"Captain still: <b>{esc(cap['web_name'])}</b> 🅲")
    L += ["", "Don't forget to save your team!"]
    return "\n".join(L)


# ------------------------------------------------------------------ 3. REVIEW
def team_points(t, pts, mins, keepers):
    """Points with simple auto-subs (non-playing starter -> first bench player who
    played, keeper for keeper) and the vice taking over a non-playing captain."""
    xi, bench = list(t["xi"]), list(t["bench"])
    for i in list(xi):
        if mins.get(i, 0) == 0:
            sub = next((b for b in bench if mins.get(b, 0) > 0 and ((b in keepers) == (i in keepers))), None)
            if sub:
                bench.remove(sub)
                xi[xi.index(i)] = sub
    cap = t["captain"] if mins.get(t["captain"], 0) > 0 else t["vice"]
    return sum(pts.get(i, 0) for i in xi) + pts.get(cap, 0)


def review_post(gw, boot, live, saved, season):
    elements = {e["id"]: e for e in boot["elements"]}
    ev = next((e for e in boot["events"] if e["id"] == gw), {})
    stats = {e["id"]: e["stats"] for e in live.get("elements", [])}
    pts = {i: s["total_points"] for i, s in stats.items()}
    mins = {i: s.get("minutes", 0) for i, s in stats.items()}
    keepers = {i for i, p in elements.items() if p["element_type"] == 1}
    score = {st: team_points(saved["teams"][st], pts, mins, keepers) for st, _, _ in STYLES}
    avg = ev.get("average_entry_score")
    L = [f"<b>📊 GW{gw} review – how our teams did</b>", ""]
    for st, icon, title in STYLES:
        L.append(f"{icon} {title.title()}: <b>{score[st]} pts</b>")
    if avg is not None:
        L.append(f"Average manager: {avg} pts")

    caps = {saved["teams"][st]["captain"] for st, _, _ in STYLES}
    best = max(caps, key=lambda i: pts.get(i, 0))
    L += ["", f"<b>✅ Best call:</b> {esc(elements[best]['web_name'])} captain "
              f"({pts.get(best, 0)} pts → {2 * pts.get(best, 0)})"]
    left_out = saved.get("most_owned")
    if left_out and min(score, key=score.get) == "bold" and pts.get(left_out, 0) >= 8:
        worst = (f"Bold team without {esc(elements[left_out]['web_name'])} – it didn't pay off this week")
    else:
        starters = {i for t in saved["teams"].values() for i in t["xi"]}
        miss = max(starters, key=lambda i: saved["xp"].get(str(i), 0) - pts.get(i, 0))
        worst = (f"{esc(elements[miss]['web_name'])} – expected {saved['xp'].get(str(miss), 0):.0f} pts, "
                 f"scored {pts.get(miss, 0)}")
    L.append(f"<b>❌ Worst call:</b> {worst}")
    if avg is not None:
        season["gws"] = season.get("gws", 0) + 1
        season["safe_ahead"] = season.get("safe_ahead", 0) + (1 if score["safe"] > avg else 0)
        L += ["", f"<b>Season so far:</b> Safe team is ahead of the average in "
                  f"{season['safe_ahead']} of {season['gws']} gameweek{'s' if season['gws'] != 1 else ''}."]
    L += ["", FOOTER]
    return "\n".join(L)


# --------------------------------------------------------------------- main
def run(args, cfg):
    tz = ZoneInfo(cfg["timezone"])
    state = load_state()
    boot, fixtures = api.bootstrap(), api.fixtures()
    events = boot["events"]
    cur = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False

    # 3. review of the gameweek that just finished
    if cur and cur.get("finished") and cur.get("data_checked") and state.get("result_gw") != cur["id"]:
        saved = state.get("gw", {}).get(str(cur["id"]))
        if saved and "teams" in saved:  # weeks posted in the old single-team format are skipped
            season = state.setdefault("season", {})
            if send(review_post(cur["id"], boot, api.live(cur["id"]), saved, season), args.dry_run):
                state["result_gw"], changed = cur["id"], True
        else:
            state["result_gw"], changed = cur["id"], True  # nothing posted that week: skip

    if nxt:
        hours = (when(nxt["deadline_time"], dt.timezone.utc) - now).total_seconds() / 3600
        key = str(nxt["id"])
        # 1. lineup
        if (0 < hours <= cfg["lineup_hours_before"] and state.get("lineup_gw") != nxt["id"]) or args.force:
            msg, saved = lineup_post(boot, fixtures, nxt, cfg, tz)
            if send(msg, args.dry_run):
                state["lineup_gw"], changed = nxt["id"], True
                state.setdefault("gw", {})[key] = saved
        # 2. reminder
        elif (0 < hours <= cfg["reminder_hours_before"] and state.get("reminder_gw") != nxt["id"]
              and key in state.get("gw", {})) or (args.reminder and key in state.get("gw", {})):
            if send(reminder_post(boot, nxt, state["gw"][key], tz, now), args.dry_run):
                state["reminder_gw"], changed = nxt["id"], True
        else:
            print(f"Next deadline in {hours:.1f} hours – nothing due.")
    if changed and not args.dry_run:
        save_state(state)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print instead of posting")
    p.add_argument("--force", action="store_true", help="post this week's lineup now")
    p.add_argument("--reminder", action="store_true", help="post the deadline reminder now")
    args = p.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    try:
        return run(args, cfg)
    except api.FplError as e:
        print(f"FPL data problem: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
