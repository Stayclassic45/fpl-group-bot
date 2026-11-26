# EdgeFinder Fantasy – FPL group bot

Posts to a Telegram channel or group, once per gameweek:

| When | Post |
| --- | --- |
| ~30 hours before each FPL deadline | **Lineup**: our starting XI with a reason and estimated points for every player, captain, bench, **transfer plans for 1, 2 and 3 free transfers** (plus whether a -4 hit is worth it), and **top buys by position** for followers whose teams differ |
| After each gameweek | **Result**: our points vs the average, our captain's score, and how the estimates compared with real points |

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
5. **Test:** **Actions → FPL group posts → Run workflow**, tick **"Post this week's lineup now"**.

## Settings (`config.yaml`, edit with the ✏️ pencil)
- `brand_name` – the name at the top of every post
- `fpl_team_id` – the base team (never shown in posts)
- `lineup_hours_before` – how long before the deadline the lineup goes out
- `transfer_tiers` – which free-transfer plans to show, e.g. `[1, 2, 3]`
- `show_rank` – show the team's overall rank in result posts (off by default; a rank can identify the team)

## How the estimates work
Expected points per player for the next gameweek = recent form and points per game, adjusted for
fixture difficulty, home/away, how often the player starts and their injury status. Transfer plans
pick the swaps with the biggest gain over the next 3 gameweeks within the budget, positions and the
3-per-club rule. They are estimates, not guarantees.

*Not affiliated with the Premier League or Fantasy Premier League.*
