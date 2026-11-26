# Formline XI – FPL channel bot

Posts to a Telegram channel or group, each once per gameweek:

| When | Post |
| --- | --- |
| ~30 hours before the deadline | **Our 3 teams** – 🟢 SAFE (shown in full), 🟡 BALANCED and 🔴 BOLD, each a legal £100m squad with formation, captain, vice and expected points; **team news**; **chip advice** |
| ~2 hours before the deadline | **Reminder** – what changed since the lineup post (injuries, returns) and the captain check |
| After the gameweek | **Review** – each team's points vs the average manager, best and worst call, and the season record |

The three styles: **SAFE** leaves out anyone with an injury doubt and prefers widely-owned regular
starters; **BALANCED** simply maximises expected points; **BOLD** leaves out the most-owned player and
favours low-ownership picks. Squads are chosen exactly with a free optimiser (PuLP) under the FPL rules
(2/5/5/3, max 3 per club, budget, legal formation).

It uses only the free public FPL data, never logs into FPL and never changes any team.
It is separate from the private EdgeFinder betting bot.

## Setup (once)
1. **Bot:** in Telegram, message **@BotFather** → `/newbot`. Copy the token (keep it private).
2. **Channel/group:** create it, then add the bot as an **admin** with "Post messages".
3. **Channel ID:** for a public channel use `@yourchannelname`. For a private channel or a group,
   ask Claude Code to help you find the numeric ID (it starts with `-100`).
4. **Secrets:** this repo → **Settings → Secrets and variables → Actions → New repository secret**:
   - `TELEGRAM_BOT_TOKEN` – the token from step 1
   - `TELEGRAM_CHANNEL_ID` – from step 3
5. **Test:** **Actions → FPL group posts → Run workflow**, tick **"Post this week's 3 teams now"**
   (or **"Post the deadline reminder now"**). Tick **"Only print"** to see a post in the log without sending it.

## Settings (`config.yaml`, edit with the ✏️ pencil)
- `budget` – £m for each of the 3 teams (default 100.0)
- `lineup_hours_before` – how long before the deadline "our 3 teams" goes out (default 30)
- `reminder_hours_before` – when the deadline reminder goes out (default 2.5)

## How the estimates work
Expected points per player for the next gameweek = recent form and points per game, adjusted for
fixture difficulty, home/away, how often the player starts and their injury status. Reviews use
simple auto-subs (a non-playing starter is replaced from the bench, keeper for keeper) and the vice
takes over a non-playing captain. They are estimates, not guarantees.

*Not affiliated with the Premier League or Fantasy Premier League.*
