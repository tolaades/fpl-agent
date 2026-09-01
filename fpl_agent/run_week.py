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
from .optimise import optimise, best_eleven, rank_transfers

API = 'https://fantasy.premierleague.com/api'
HIST_URL = ('https://raw.githubusercontent.com/vaastav/Fantasy-Premier-League'
            '/master/data/{season}/players_raw.csv')
UA = 'Mozilla/5.0 (compatible; fpl-agent/1.0)'


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


def load_squad(e, path):
    """Squad file: {"entry_id": 123} or {"players": ["Haaland", ...],
    "bank": 0.4, "free_transfers": 2}."""
    cfg = json.load(open(path))
    if cfg.get('entry_id'):
        gw = e.NEXT - 1
        url = f"{API}/entry/{cfg['entry_id']}/event/{max(1, gw)}/picks/"
        req = urllib.request.Request(url, headers={'User-Agent': UA})
        picks = json.loads(urllib.request.urlopen(req, timeout=60).read())
        ids = [p['element'] for p in picks['picks']]
        bank = picks.get('entry_history', {}).get('bank', 0) / 10
        return ids, bank, cfg.get('free_transfers', 1)
    by_name = {p['web_name']: p['id'] for p in e.B['elements']}
    ids, missing = [], []
    for n in cfg['players']:
        if n in by_name:
            ids.append(by_name[n])
        else:
            missing.append(n)
    if missing:
        print(f'WARNING: could not match {missing}', file=sys.stderr)
    return ids, cfg.get('bank', 0.0), cfg.get('free_transfers', 1)


def ticker(e, proj):
    out = []
    for g in proj['per']:
        if g['blank']:
            out.append('---')
        else:
            fx = g['fx'][0]
            out.append(f"{fx['opp']}{'H' if fx['home'] else 'A'}")
    return ' '.join(out)


def brief(e, ids, bank, ft, horizon):
    L = []
    ev = [x for x in e.B['events'] if x['id'] == e.NEXT][0]
    dl = datetime.datetime.fromisoformat(ev['deadline_time'].replace('Z', '+00:00'))
    L.append(f"# Gameweek {e.NEXT} brief")
    L.append(f"\nDeadline **{dl:%a %d %b %H:%M} UTC** | bank £{bank:.1f}m "
             f"| {ft} free transfer(s) | horizon GW{e.GWS[0]}-{e.GWS[-1]}\n")

    sq = [(e.EL[i], e.PROJ[i]) for i in ids if i in e.EL]
    xi = best_eleven(e, sq)

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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--squad', required=True)
    ap.add_argument('--cache', default='./cache')
    ap.add_argument('--out', default='brief.md')
    ap.add_argument('--horizon', type=int, default=5)
    ap.add_argument('--offline', action='store_true',
                    help='use cached files instead of fetching')
    a = ap.parse_args()

    if a.offline:
        boot = os.path.join(a.cache, 'bootstrap-static.json')
        fixt = os.path.join(a.cache, 'fixtures.json')
        hist = os.path.join(a.cache, 'players_raw_2025-26.csv')
    else:
        boot, fixt, hist = refresh(a.cache)

    e = build(boot, fixt, hist, horizon=a.horizon)
    ids, bank, ft = load_squad(e, a.squad)
    text = brief(e, ids, bank, ft, a.horizon)
    with open(a.out, 'w') as f:
        f.write(text)
    print(f'wrote {a.out} for GW{e.NEXT} ({len(ids)} players)')


if __name__ == '__main__':
    main()
