# The two halves, and where each one runs

Nothing here needs your laptop awake.

| | Where it runs | When | What it does |
|---|---|---|---|
| **GitHub Actions** | GitHub's cloud | Daily, 02:30 UTC | Fetches both endpoints, runs the model, commits `brief.md` |
| **Cowork scheduled task** | Anthropic's cloud | Thu 21:00, Fri 08:00 | Reads the brief, researches team news, tells you what to change |

The split matters. Anthropic's docs are explicit that scheduled tasks run
remotely and work even when your computer is asleep, but that they can't be
tied to a folder on your computer, and a task needing local files runs locally
only. So the Python cannot live on your machine if you want this hands-off.
GitHub Actions runs it instead, and Cowork reads the result over the web.

---

## Part 1: GitHub Actions

1. Create a repository. **Public** is simplest, since Cowork then reads the
   brief without any credentials. Nothing in it is sensitive: it's your squad
   list and public FPL data.
2. Copy in `fpl_agent/`, `requirements.txt`, `squad.json`, and
   `.github/workflows/daily.yml`.
3. In the repo: **Settings → Actions → General → Workflow permissions →
   Read and write permissions.** Without this the commit step fails.
4. Go to the **Actions** tab and trigger `FPL daily brief` manually once to
   confirm it works before trusting the schedule.

Your brief is then always at:

```
https://raw.githubusercontent.com/<you>/<repo>/main/brief.md
```

Dated copies land in `snapshots/`, which is what you'll use later to check
whether the model's projections were any good.

---

## Part 2: Cowork scheduled task

Open Cowork, click **Scheduled**, then **New task**, and set it up manually.
Do **not** set a working folder — leaving it blank is what keeps the task
remote. Run it twice: **Thursday 21:00** and **Friday 08:00**.

### Prompt to paste

Replace `<you>/<repo>` with your actual path before saving.

```
Fetch https://raw.githubusercontent.com/<you>/<repo>/main/brief.md

That file is produced by a projection model that ran this morning. Treat its
numbers as given. Do not recalculate expected points, re-rank transfers, or
substitute your own judgement for its projections. Your job is the information
the model cannot see. The brief also contains a "Your plan" section with my
current chip status and standing decisions - read it, don't assume.

Research, for every club appearing in that brief:

1. Press conferences from the last 48 hours. Manager quotes on fitness, who is
   "assessed", "a doubt", or "back in training".
2. Injury and suspension updates, including anything reported after the
   model's data was pulled.
3. Predicted lineups from at least two independent sources.
4. Whether any of these clubs played a midweek European or cup fixture. If so,
   flag rotation risk explicitly - the model has no knowledge of fixture
   congestion and will overrate anyone likely to be rested.
5. Any late price changes affecting a transfer named in the plan.

Then write me:

- **Start or bench changes**: any player in the recommended XI whose start is
  now in doubt, and who should replace them from the bench.
- **Transfers**: which rows in the transfer table survive the news. Say plainly
  if the top-ranked transfer is now a bad idea. If the plan names a specific
  target, tell me whether it still holds and whether the price has moved.
- **Captain**: whether the recommended captain is still the right call.
- **Chip check**: one line against the chip status in the plan. Flag anything
  that would change the timing - in particular, any newly announced blank or
  double gameweek, since that overrides the planned Free Hit week.
- **Deadline** and how long I have.

Where the news contradicts the model, say so directly. Do not average the two
positions or hedge. I would rather see the disagreement than a blended answer.
```

---

## Why the model stays in code

The projection is deterministic: the same snapshot always produces the same
numbers. That's what makes it possible to check, in a month, whether the model
is any good, by comparing `snapshots/brief-*.md` against what actually scored.

If an agent re-derived expected points each week, you would get a different
answer every run from identical inputs, and no way to tell whether a change
came from new information or from variation in the reasoning. The agent's job
is the part that genuinely needs reading and judgement: press conferences,
rotation, and calling out when the model is confidently wrong.
