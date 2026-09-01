# CLAUDE.md

Context for anyone, human or agent, working on this repo.

## What this is

A Fantasy Premier League projection model. It turns a snapshot of the public
FPL API into expected points per player per gameweek, then picks an XI and
ranks transfers under the game's real constraints.

Two halves, deliberately separated:

- **Deterministic code** (this repo) does fetching, projection, optimisation.
  The same snapshot must always produce the same numbers.
- **An agent** (a Cowork scheduled task, see COWORK_TASK.md) reads the output
  and adds press conference news, predicted lineups, and rotation risk.

That boundary is the core design decision. Do not move work across it. If an
agent estimated expected points, identical inputs would give different answers
each run and there would be no way to tell whether a change came from new
information or from variation in reasoning.

## Architecture

| File | Role |
|---|---|
| `engine.py` | `build()` loads a snapshot and projects every player. Returns a namespace. |
| `priors.py` | Empirical Bayes priors from last season |
| `team_strength.py` | Poisson attack/defence ratings fitted on results |
| `optimise.py` | Best XI, transfer ranking, full-squad ILP |
| `run_week.py` | Fetches, runs everything, writes `brief.md` |

## Decisions that look wrong but are not

**Player IDs are not stable across seasons. `code` is.** The historical join in
`priors.py` uses `code`. Changing it to `id` will silently match the wrong
players.

**`STAT_K` in priors.py has a different value per statistic.** Expected goals
gets 700 minutes, defensive contributions 250. This is not an oversight.
Expected goals swings wildly match to match while defensive contributions
barely move, so equal treatment let one freak match dominate a projection. A
£4.6m defender was recommended as the top transfer target off 77 minutes at 16
times his established rate. Do not collapse these into one constant.

**FDR is deliberately unused for the main adjustment.** FPL's difficulty
ratings are set before the season and never update, so they cannot know a team
has failed to score in every match. `team_strength.py` fits ratings from actual
results instead. The FDR fields are still carried in the fixture dicts for
reference and display only.

**Minutes are normalised by matches the *club* has played, not a fixed number.**
Gameweeks can be half-complete, with some clubs having played and others not.
Assuming a fixed number of rounds marks every player from a club that hasn't
played yet as a rotation risk.

**`clean_sheet_prob` is a plain Poisson.** It is known to be slightly
optimistic because real scorelines are overdispersed. Fixing it properly needs
per-gameweek history, which is a planned change, not a bug to patch with a
fudge factor.

## Known limitations

Stated plainly because the brief tells the user about them every week:

- **No lineup or rotation model.** Projections assume the last XI repeats. This
  is the single largest source of error. European fixture congestion is
  invisible to the model.
- **No press conference ingestion.** The agent half covers this.
- **Roughly a quarter of players have no prior-season record** (promoted clubs,
  new signings) and fall back to positional averages. `run_week.py` names them
  in the brief.
- **`price_change_projections` is unused.** It exists in the 2026/27 API and
  would tell you whether a transfer must happen tonight. Cheap win, not done.

## Tuning

`HIST_K` (priors.py) — minutes of last-season evidence before it outweighs the
positional average.
`STAT_K` (priors.py) — per-statistic, above.
`GAMES_K` (team_strength.py) — matches before results outweigh the preseason
baseline. Does a lot of work early in a season.

**None of these constants have been validated against outcomes.** They are set
on judgement. `snapshots/` accumulates dated briefs specifically so projections
can eventually be scored against what actually happened. Until there are five
or six gameweeks of that, treat any tuning as a guess and do not present it
otherwise.

## House style

Comments explain *why*, not *what*. Several constants here look arbitrary and
the comment next to them is the only record of the reasoning. Keep that up.
