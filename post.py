"""FPL group bot. Run: python post.py --dry-run --force

Runs a few times a day (GitHub Actions) and posts, at most once each:
 - the LINEUP post about 30 hours before each FPL deadline: our XI with a reason and
   estimated points per player, captain, bench, transfer plans for 1/2/3 free transfers,
   and top buys by position for followers whose teams differ;
 - the HOW WE DID post after each gameweek: our points vs the average, and how the
   estimates compared with real points.
It only reads public FPL data and never changes any FPL team.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from fplbot import fpl_api as api, model as fm
from fplbot.telegram import send, esc

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "data" / "state.json"
POS = {1: "GK", 2: "DEF", 3: "MID", 4: "FWD"}


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s):
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(s, indent=2, sort_keys=True))


def when(iso, tz):
    return dt.datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(tz)


def squad_for_next(team_id, cur_gw):
    """The squad that will play the next GW (after a Free Hit, the week before's)."""
    p = api.picks(team_id, cur_gw)
    if p.get("active_chip") == "freehit" and cur_gw > 1:
        prev = api.picks(team_id, cur_gw - 1)
        prev["entry_history"] = p["entry_history"]
        return prev
    return p


def lineup_post(boot, fixtures, picks, gw_event, cfg, tz):
    elements = {e["id"]: e for e in boot["elements"]}
    teams = {t["id"]: t for t in boot["teams"]}
    gw = gw_event["id"]
    gws = [g for g in range(gw, gw + cfg["lookahead_gws"]) if g <= len(boot["events"])]
    finished = sum(1 for e in boot["events"] if e.get("finished"))
    tfix = fm.team_fixtures(fixtures, set(gws))
    xp = {pid: fm.expected_points(e, tfix, gws, finished) for pid, e in elements.items()}
    xp3 = {pid: sum(v.values()) for pid, v in xp.items()}
    xp_next = {pid: v[gw] for pid, v in xp.items()}

    squad_ids = [p["element"] for p in picks["picks"]]
    squad = [elements[i] for i in squad_ids]
    bank = ((picks.get("entry_history") or {}).get("bank") or 0) / 10
    xi, bench = fm.best_xi(squad, xp_next)
    cap, vice = sorted(xi, key=lambda p: xp_next[p["id"]], reverse=True)[:2]
    plans = fm.transfer_plans(squad_ids, elements, xp3, bank, cfg, tuple(cfg["transfer_tiers"]))
    buys = fm.top_buys(elements, xp3, set(squad_ids), cfg["top_buys_per_position"])

    n = lambda p: f"<b>{esc(p['web_name'])}</b>"
    deadline = when(gw_event["deadline_time"], tz)
    total = sum(xp_next[p["id"]] for p in xi) + xp_next[cap["id"]]  # captain counts double
    L = [f"⚽ <b>{esc(cfg['brand_name'])} – Gameweek {gw}</b> · deadline {deadline:%a %d %b %H:%M}", "",
         "<b>📋 Our team this week</b>"]
    for pos in (1, 2, 3, 4):
        for p in sorted((q for q in xi if q["element_type"] == pos), key=lambda q: -xp_next[q["id"]]):
            tag = " ©️" if p is cap else " (V)" if p is vice else ""
            L.append(f"<b>{POS[pos]}</b> {n(p)}{tag} · {xp_next[p['id']]:.1f} pts")
            L.append(f"   <i>{esc(fm.reason(p, tfix, gw, teams))}</i>")
    L += ["", f"<b>©️ Captain:</b> {n(cap)} · <b>Vice:</b> {esc(vice['web_name'])}",
          "<b>🪑 Bench:</b> " + esc(", ".join(p["web_name"] for p in bench)),
          f"<b>Team total:</b> {total:.1f} expected pts (captain doubled)", "",
          "<b>🔁 Transfer plans – pick the one that matches your free transfers</b>"]

    def moves_text(moves):
        return "; ".join(f"OUT {esc(elements[m['out']]['web_name'])} → IN {n(elements[m['in']])} "
                         f"(£{elements[m['in']]['now_cost'] / 10:.1f}m)" for m in moves)
    for k in cfg["transfer_tiers"]:
        mv = plans.get(k) or []
        if mv:
            L.append(f"<b>{k} FT:</b> {moves_text(mv)} · <i>+{sum(m['gain'] for m in mv):.1f} pts over {len(gws)} GWs</i>")
        else:
            L.append(f"<b>{k} FT:</b> <i>no move worth making – roll the transfer</i>")
    if plans.get("hit"):
        L.append(f"<b>Taking a -4 hit?</b> {moves_text(plans['hit'])} · <i>+{plans['hit'][0]['gain']:.1f} pts – worth it</i>")
    else:
        L.append("<b>Taking a -4 hit?</b> <i>not worth it this week</i>")
    L += ["", "<b>💡 Don't own these? Top buys by position</b> (next %d GWs)" % len(gws)]
    for pos in (1, 2, 3, 4):
        L.append(f"<b>{POS[pos]}</b> " + " · ".join(f"{esc(p['web_name'])} £{p['now_cost'] / 10:.1f}m ({xp3[p['id']]:.1f})"
                                                for p in buys[pos]))
    L += ["", "<i>Estimates, not guarantees. Based on our own team – adjust to yours.</i>"]
    predicted = {str(p["id"]): round(xp_next[p["id"]], 2) for p in xi}
    return "\n".join(L), {"captain": cap["id"], "predicted": predicted}


def result_post(gw, boot, hist, live, saved, cfg):
    cur = {h["event"]: h for h in hist.get("current", [])}
    h = cur.get(gw)
    if not h:
        return None
    elements = {e["id"]: e for e in boot["elements"]}
    ev = next((e for e in boot["events"] if e["id"] == gw), {})
    pts = {e["id"]: e["stats"]["total_points"] for e in live.get("elements", [])}
    L = [f"📊 <b>{esc(cfg['brand_name'])} – Gameweek {gw} result</b>", "",
         f"<b>Our points:</b> {h['points'] - (h.get('event_transfers_cost') or 0)}"
         + (f" · average {ev['average_entry_score']}" if ev.get("average_entry_score") else "")]
    if cfg.get("show_rank") and h.get("overall_rank"):
        L.append(f"<b>Overall rank:</b> {h['overall_rank']:,}")
    if saved:
        cap = saved.get("captain")
        if cap:
            L.append(f"<b>Our captain:</b> {esc(elements.get(cap, {}).get('web_name', '?'))} – "
                     f"{pts.get(cap, 0)} pts ({pts.get(cap, 0) * 2} doubled)")
        pred = saved.get("predicted") or {}
        if pred:
            est = sum(pred.values())
            real = sum(pts.get(int(i), 0) for i in pred)
            L.append(f"<b>Estimate check:</b> starting XI predicted {est:.0f} pts, scored {real} pts")
            best = sorted(pred, key=lambda i: pts.get(int(i), 0), reverse=True)[:3]
            L.append("<b>Top scorers:</b> " + ", ".join(
                f"{esc(elements.get(int(i), {}).get('web_name', '?'))} {pts.get(int(i), 0)}" for i in best))
    L += ["", "<i>Estimates, not guarantees.</i>"]
    return "\n".join(L)


def run(args, cfg):
    tz = ZoneInfo(cfg["timezone"])
    team = cfg["fpl_team_id"]
    state = load_state()
    boot, fixtures, hist = api.bootstrap(), api.fixtures(), api.history(team)
    events = boot["events"]
    cur = next((e for e in events if e.get("is_current")), None)
    nxt = next((e for e in events if e.get("is_next")), None)
    now = dt.datetime.now(dt.timezone.utc)
    changed = False

    if cur and cur.get("finished") and cur.get("data_checked") and state.get("result_gw") != cur["id"]:
        msg = result_post(cur["id"], boot, hist, api.live(cur["id"]), state.get("gw", {}).get(str(cur["id"])), cfg)
        if msg and send(msg, args.dry_run):
            state["result_gw"], changed = cur["id"], True

    if nxt and cur:
        hours = (when(nxt["deadline_time"], dt.timezone.utc) - now).total_seconds() / 3600
        due = 0 < hours <= cfg["lineup_hours_before"] and state.get("lineup_gw") != nxt["id"]
        if due or args.force:
            msg, saved = lineup_post(boot, fixtures, squad_for_next(team, cur["id"]), nxt, cfg, tz)
            if send(msg, args.dry_run):
                state["lineup_gw"], changed = nxt["id"], True
                state.setdefault("gw", {})[str(nxt["id"])] = saved
        else:
            print(f"Next deadline in {hours:.0f} hours – lineup not due yet.")
    if changed and not args.dry_run:
        save_state(state)
    return 0


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true", help="print instead of posting")
    p.add_argument("--force", action="store_true", help="post this week's lineup now")
    args = p.parse_args(argv)
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text())
    try:
        return run(args, cfg)
    except api.FplError as e:
        print(f"FPL data problem: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
