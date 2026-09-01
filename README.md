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

or list the players by name:

```json
{
  "players": ["Lammens", "Kinsky", "Virgil", "..."],
  "bank": 0.0,
  "free_transfers": 2
}
```

The `entry_id` route is better. It returns your bank and purchase prices, which
a name list cannot.

Add `--offline` to rerun against the cached snapshot without refetching.

## Layout

| File | Role |
|---|---|
| `engine.py` | Loads a snapshot, projects every player per gameweek |
| `priors.py` | Empirical Bayes priors from last season, joined on player `code` |
| `team_strength.py` | Poisson attack/defence ratings fitted on results |
| `optimise.py` | Best XI, transfer ranking, and the full-squad ILP |
| `run_week.py` | Fetches, runs everything, writes the brief |

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
