# FPL Agent

Weekly Fantasy Premier League projections. Deterministic model, agent-written analysis.

## What it does

Fetches the live FPL snapshot, projects every player across a rolling horizon,
and writes `brief.md` with a recommended XI, captain, bench order, ranked
transfers, and an explicit list of what the model cannot see.

The projection blends each player's current-season rates with a prior built
from last season, weighted by how much evidence each side actually carries.
Fixture difficulty comes from a Poisson team-strength model fitted on results,
not FPL's preseason difficulty ratings, which never update.

## Setup

```bash
pip install pulp                      # only needed for wildcard/free-hit planning
python -m fpl_agent.run_week --squad squad.json --out brief.md
```

`squad.json` — either let it fetch your squad:

```json
{ "entry_id": 1234567, "free_transfers": 2 }
```

`chips` and `notes` are optional. Anything you put there is rendered into the
brief under "Your plan", which keeps your chip status and standing decisions in
one place rather than duplicated in the agent prompt.

or list the players by name:

```json
{
  "players": ["Lammens", "Kinsky", "Virgil", "..."],
  "bank": 0.0,
  "free_transfers": 2
}
```

The `entry_id` route is better. It resolves your squad automatically and
replays any transfers you have already confirmed for the upcoming gameweek.

Set `bank` and `free_transfers` explicitly anyway: FPL's API reports both as
they stood at the last deadline, so mid-week they are stale. Values in
squad.json always win.

`timezone` is an IANA name such as `America/New_York`. The deadline is rendered
in it, which matters because the job runs on a UTC machine.

Add `--offline` to rerun against the cached snapshot without refetching.

## Layout

| File | Role |
|---|---|
| `engine.py` | Loads a snapshot, projects every player per gameweek |
| `priors.py` | Empirical Bayes priors from last season, joined on player `code` |
| `team_strength.py` | Poisson attack/defence ratings fitted on results |
| `optimise.py` | Best XI, transfer ranking, and the full-squad ILP |
| `recency.py` | Per-match minutes, weighted toward the latest appearance |
| `run_week.py` | Fetches, runs everything, writes the brief |
| `score.py` | Grades past predictions against real results |

Player IDs change between seasons; the stable identifier is `code`, which is
what the historical join uses.

## Tuning

Two sets of constants carry most of the model's behaviour.

`priors.py` — `HIST_K` is how many minutes of last-season evidence before it
outweighs the positional average. `STAT_K` is per statistic: expected goals
swing wildly match to match, so 700; defensive contributions barely move, so
250. Lowering a value makes the model react faster to a hot streak.

`team_strength.py` — `GAMES_K` is how many matches before results outweigh the
preseason baseline. Early in a season this is doing a lot of work.

## What it deliberately does not do

No press conference reading, no predicted lineups, no European rotation model.
Minutes projections assume the last XI repeats, which is the single largest
source of error. The brief flags this every week rather than hiding it.
