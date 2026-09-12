#!/usr/bin/env python3
"""Weekly FPL run: fetch, project, optimise, write a brief.

Everything here is deterministic. The judgement calls that need a human or an
agent -- press conference news, rotation risk, whether to trust a hot streak --
are deliberately left out and flagged in the output instead.

    python -m fpl_agent.run_week --squad squad.json --out brief.md
"""
import argparse, json, os, sys, urllib.request, datetime
from collections import defaultdict

from .engine import build
from .recency import fetch_recent_minutes
from .team_state import fetch_state
from .optimise import optimise, best_eleven, rank_transfers

API = 'https://fantasy.premierleague.com/api'
HIST_URL = ('https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League'
            '/master/data/{season}/players_raw.csv')
UA = 'Mozilla/5.0 (compatible; fpl-agent/1.0)'


def _api(path, timeout=60):
    """GET a JSON endpoint. Returns None rather than raising on failure."""
    try:
        req = urllib.request.Request(f'{API}{path}', headers={'User-Agent': UA})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception as exc:
        print(f'warning: {path} failed ({exc})', file=sys.stderr)
        return None


def fetch(url, dest):
    req = urllib.request.Request(url, headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
    with open(dest, 'wb') as f:
        f.write(data)
    return dest


def refresh(cache, season='2025-26'):
    """Pull the two live endpoints every run; the history file only once."""
    os.makedirs(cache, exist_ok=True)
    boot = os.path.join(cache, 'bootstrap-static.json')
    fixt = os.path.join(cache, 'fixtures.json')
    hist = os.path.join(cache, f'players_raw_{season}.csv')
    fetch(f'{API}/bootstrap-static/', boot)
    fetch(f'{API}/fixtures/', fixt)
    if not os.path.exists(hist):
        fetch(HIST_URL.format(season=season), hist)
    return boot, fixt, hist


def load_squad(e, path, offline=False):
    """Resolve your team. Prefers the API; squad.json is override and fallback.

    Anything you set explicitly in squad.json wins, so you can correct the
    model when you know better. Leave a field out and it is read from FPL.
    """
    cfg = json.load(open(path))
    state_notes = []

    if cfg.get('entry_id') and not offline:
        try:
            st = fetch_state(cfg['entry_id'], e.NEXT, e.EL)
            ids = st['squad']
            bank = cfg['bank'] if cfg.get('bank') is not None else st['bank']
            ft = (cfg['free_transfers'] if cfg.get('free_transfers') is not None
                  else st['free_transfers'])
            state_notes = st['notes']
            for n in state_notes:
                print(n)
            if cfg.get('players'):
                listed = {p for p in cfg['players']}
                actual = {e.EL[i]['web_name'] for i in ids}
                drift = listed ^ actual
                if drift:
                    state_notes.append(
                        'squad.json disagrees with your actual team on: '
                        + ', '.join(sorted(drift))
                        + '. The API was used. Update or remove the players list.')
                    print(state_notes[-1], file=sys.stderr)
            return ids, bank, ft, state_notes
        except Exception as exc:
            print(f'WARNING: could not read your team ({exc}); '
                  'falling back to squad.json', file=sys.stderr)

    ids, bank, ft = _from_names(e, cfg, cfg.get('bank'), cfg.get('free_transfers'))
    return ids, bank, ft, state_notes


def _norm_name(s):
    """Compare names without accents. squad.json is hand-edited, and typing
    Gross for Groß or Joao for João silently dropped players from the squad.
    """
    import unicodedata
    s = (s or '').replace('ß', 'ss')
    s = unicodedata.normalize('NFD', s)
    return ''.join(ch for ch in s if unicodedata.category(ch) != 'Mn').lower().strip()


def _from_names(e, cfg, bank, ft):
    by_name = {}
    for p in e.B['elements']:
        by_name.setdefault(_norm_name(p['web_name']), p['id'])
    ids, missing = [], []
    for n in cfg.get('players', []):
        key = _norm_name(n)
        if key in by_name:
            ids.append(by_name[key])
        else:
            missing.append(n)
    if missing:
        print(f'WARNING: could not match {missing}', file=sys.stderr)
    return ids, bank or 0.0, ft if ft is not None else 1


def ticker(e, proj):
    out = []
    for g in proj['per']:
        if g['blank']:
            out.append('---')
        else:
            fx = g['fx'][0]
            out.append(f"{fx['opp']}{'H' if fx['home'] else 'A'}")
    return ' '.join(out)


def brief(e, ids, bank, ft, horizon, cfg_extra=None):
    cfg_extra = cfg_extra or {}
    L = []
    ev = [x for x in e.B['events'] if x['id'] == e.NEXT][0]
    dl = datetime.datetime.fromisoformat(ev['deadline_time'].replace('Z', '+00:00'))
    tzname = cfg_extra.get('timezone')
    if tzname:
        try:
            from zoneinfo import ZoneInfo
            dl = dl.astimezone(ZoneInfo(tzname))
        except Exception:
            tzname = 'UTC'
    else:
        tzname = 'UTC'
    L.append(f"# Gameweek {e.NEXT} brief")
    L.append(f"\nDeadline **{dl:%a %d %b %H:%M} {tzname}** | bank £{bank:.1f}m "
             f"| {ft} free transfer(s) | horizon GW{e.GWS[0]}-{e.GWS[-1]}\n")

    sq = [(e.EL[i], e.PROJ[i]) for i in ids if i in e.EL]
    xi = best_eleven(e, sq)
    if xi is None:
        # Happens when squad.json lists too few players, or names failed to
        # match. Say so plainly instead of dying on a NoneType.
        L.append(f'\n## Cannot pick a team\n')
        L.append(f'Only {len(sq)} of 15 players resolved, so no legal XI exists. '
                 'Check the `players` list in squad.json against your actual squad.')
        return '\n'.join(L)

    L.append(f"## Recommended XI ({xi['formation']}) "
             f"- {xi['score']:.1f} projected, {xi['score']+xi['captain'][1]['per'][0]['xp']:.1f} with captain\n")
    L.append('| Pos | Player | Club | Fixture | xGF | xGA | xPts |')
    L.append('|---|---|---|---|---|---|---|')
    for p, pr in xi['xi']:
        g = pr['per'][0]
        fx = g['fx'][0] if not g['blank'] else None
        tag = ' **(C)**' if (p, pr) == xi['captain'] else ''
        L.append(f"| {e.POS[p['element_type']]} | {p['web_name']}{tag} "
                 f"| {e.TEAMS[p['team']]['short_name']} "
                 f"| {fx['opp']}{'(H)' if fx['home'] else '(A)'} "
                 f"| {fx['xgf']:.2f} | {fx['xga']:.2f} | {g['xp']:.2f} |")
    L.append('\n**Bench:** ' + ', '.join(
        f"{p['web_name']} ({pr['per'][0]['xp']:.1f})" for p, pr in xi['bench']))

    L.append(f'\n## Transfers ({ft} free)\n')
    L.append('| Out | In | Club | Price | Gain over horizon |')
    L.append('|---|---|---|---|---|')
    for t in rank_transfers(e, sq, bank)[:8]:
        L.append(f"| {t['out']['web_name']} | {t['in']['web_name']} "
                 f"| {e.TEAMS[t['in']['team']]['short_name']} "
                 f"| £{t['in']['now_cost']/10:.1f}m | +{t['gain']:.2f} |")

    flagged = [p for p, _ in sq if p['news'] or p['status'] != 'a']
    L.append('\n## Risk in your squad\n')
    if not flagged:
        L.append('No flags on any of your 15.')
    for p in flagged:
        ch = p['chance_of_playing_next_round']
        L.append(f"- **{p['web_name']}** ({e.TEAMS[p['team']]['name']}) - "
                 f"{p['news'] or 'flagged, no detail'}"
                 + (f" | {ch}% to play" if ch is not None else ''))

    chips = cfg_extra.get('chips') or {}
    notes = (cfg_extra.get('_state') or []) + (cfg_extra.get('notes') or [])
    if chips or notes:
        L.append('\n## Your plan\n')
        for k, v in chips.items():
            L.append(f"- **{k.replace('_', ' ').title()}**: {v}")
        for note in notes:
            L.append(f'- {note}')

    L.append('\n## What this model cannot see\n')
    L.append('- Press conferences and predicted lineups. Projections assume the '
             'last XI repeats. Check team news before the deadline.')
    L.append('- European fixture congestion and rotation.')
    low = [p['web_name'] for p, _ in sq
           if e.PRIORS[p['id']]['source'] == 'positional']
    if low:
        L.append(f"- No prior-season record for: {', '.join(low)}. "
                 'Their numbers rest on this season alone and are the least reliable.')
    return '\n'.join(L)


def save_roster(e, path='players.json'):
    """Publish a small roster so a browser can resolve player names.

    bootstrap-static sends no CORS headers and is ~1.6MB, so a web page cannot
    read it. This is the same data trimmed to what name-matching needs, small
    enough to fetch from the repo.
    """
    rows = [dict(id=p['id'], name=p['web_name'],
                 team=e.TEAMS[p['team']]['short_name'],
                 pos=e.POS[p['element_type']], cost=p['now_cost'] / 10.0)
            for p in e.B['elements']]
    with open(path, 'w') as f:
        json.dump(dict(gw=e.NEXT, players=rows), f, ensure_ascii=False)
    return len(rows)


def save_predictions(e, xi, path='./predictions'):
    """Write this gameweek's projections so score.py can grade them later.

    Recorded before the gameweek is played, so the comparison cannot be
    retrofitted. This is the only way to find out whether the model's constants
    are set correctly rather than merely plausible.
    """
    os.makedirs(path, exist_ok=True)
    players = {}
    for p in e.B['elements']:
        pr = e.PROJ[p['id']]
        if pr['per'][0]['xp'] <= 0 and pr['prof']['xmins'] < 45:
            continue
        players[str(p['id'])] = dict(
            name=p['web_name'], pos=e.POS[p['element_type']],
            xp=round(pr['per'][0]['xp'], 3),
            xmins=round(pr['prof']['xmins'], 1))
    out = dict(gw=e.NEXT,
               generated=datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
               xi=[p['id'] for p, _ in xi['xi']],
               captain=xi['captain'][0]['id'],
               players=players)
    dest = os.path.join(path, f'gw{e.NEXT}.json')
    with open(dest, 'w') as f:
        json.dump(out, f)
    return dest, len(players)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--squad', required=True)
    ap.add_argument('--cache', default='./cache')
    ap.add_argument('--out', default='brief.md')
    ap.add_argument('--horizon', type=int, default=5)
    ap.add_argument('--offline', action='store_true',
                    help='use cached files instead of fetching')
    ap.add_argument('--no-recency', action='store_true',
                    help='skip the per-match minutes pass (faster, less accurate)')
    a = ap.parse_args()

    if a.offline:
        boot = os.path.join(a.cache, 'bootstrap-static.json')
        fixt = os.path.join(a.cache, 'fixtures.json')
        hist = os.path.join(a.cache, 'players_raw_2025-26.csv')
    else:
        boot, fixt, hist = refresh(a.cache)

    e = build(boot, fixt, hist, horizon=a.horizon)
    ids, bank, ft, state_notes = load_squad(e, a.squad, offline=a.offline)

    # Second pass with per-match minutes. Season totals cannot tell a player
    # who has just won his place from one who has just lost it, and that
    # distinction is worth several points a week on rotation-risk players.
    if not a.offline and not a.no_recency:
        shortlist = set(ids)
        for t in (1, 2, 3, 4):
            ranked = sorted((p for p in e.B['elements']
                             if p['element_type'] == t and p['status'] == 'a'),
                            key=lambda p: -e.PROJ[p['id']]['total'])
            shortlist.update(p['id'] for p in ranked[:40])
        print(f'fetching per-match minutes for {len(shortlist)} players...')
        recent = fetch_recent_minutes(sorted(shortlist))
        print(f'  got {len(recent)}')
        e = build(boot, fixt, hist, horizon=a.horizon, recent=recent)
    text = brief(e, ids, bank, ft, a.horizon, cfg_extra=dict(json.load(open(a.squad)), _state=state_notes))

    sq = [(e.EL[i], e.PROJ[i]) for i in ids if i in e.EL]
    xi = best_eleven(e, sq)
    if xi is None:
        # Happens when squad.json lists too few players, or names failed to
        # match. Say so plainly instead of dying on a NoneType.
        L.append(f'\n## Cannot pick a team\n')
        L.append(f'Only {len(sq)} of 15 players resolved, so no legal XI exists. '
                 'Check the `players` list in squad.json against your actual squad.')
        return '\n'.join(L)
    if xi:
        dest, count = save_predictions(e, xi)
        print(f'published roster of {save_roster(e)} players')
        print(f'recorded {count} projections to {dest}')
    with open(a.out, 'w') as f:
        f.write(text)
    print(f'wrote {a.out} for GW{e.NEXT} ({len(ids)} players)')


if __name__ == '__main__':
    main()
