# Hand this to Claude Code

Open a terminal in the folder containing this repo, run `claude`, and paste
everything in the block below.

The steps are ordered so the risky part is tested first. The live fetch against
the FPL API has never been run — it was written blind because the environment
that built it could not reach `fantasy.premierleague.com`. Verify that before
setting up any automation.

---

```
Read CLAUDE.md first for the design constraints, then set this project up.

STEP 1 - Prove the model works offline
- Create a venv and install requirements.txt.
- I have cached snapshots, or you can skip to step 2 and come back.
- Run: python -m fpl_agent.run_week --squad squad.json --out brief.md --offline
- If cache files are missing, that's expected. Move to step 2.

STEP 2 - Test the live fetch (THIS IS THE UNTESTED PART)
- Run: python -m fpl_agent.run_week --squad squad.json --out brief.md
- This hits fantasy.premierleague.com for the first time. If it fails, the
  likely causes in order are: a blocked User-Agent, a 403 needing a session
  cookie, or a redirect. Fix it in fpl_agent/run_week.py's fetch() and tell me
  exactly what you changed and why.
- Confirm brief.md contains a full XI, a captain, and a transfer table with
  real player names. If any section is empty, something upstream failed
  silently - investigate rather than papering over it.

STEP 3 - Point it at my real team
- Ask me for my FPL team ID if squad.json still has the name list.
- Rewrite squad.json as {"entry_id": <id>, "free_transfers": <n>}.
- Rerun and confirm the squad matches what I actually own.

STEP 4 - Ship it to GitHub
- git init, commit, and create a PUBLIC repo with gh (public so Cowork can
  read the brief without credentials; nothing in it is sensitive).
- Enable Actions write permission, which the workflow needs to commit:
  gh api -X PUT repos/{owner}/{repo}/actions/permissions/workflow \
    -f default_workflow_permissions=write
- Trigger the workflow by hand and watch it:
  gh workflow run "FPL daily brief"
  gh run watch
- If it fails, read the logs and fix it. Do not tell me it succeeded until
  brief.md has actually been committed by the Action.

STEP 5 - Report back
- Give me the raw URL of brief.md.
- Tell me what time the daily job runs in MY timezone.
- List anything you changed from the original and why.

Work through these in order. Stop and ask if a step fails in a way that needs
my input rather than guessing at credentials or IDs.
```

---

## What Claude Code cannot do

Two things stay manual, and both take under a minute.

**The Cowork scheduled task.** It lives in the Claude Desktop UI, not on disk.
Follow COWORK_TASK.md once the repo is live and you have the raw URL. Leave the
working folder blank so the task runs remotely.

**Your FPL team ID.** It's the number in your points page URL. Claude Code will
ask.
