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
    """Resolve the squad you will actually field, not the one you last fielded.

    FPL only writes a picks record once a deadline passes, so between Monday
    and Friday /entry/{id}/event/{gw}/picks/ returns the previous gameweek's
    team. Any transfer made this week is invisible to it. We therefore read the
    last confirmed picks and replay any transfers already logged for the
    upcoming gameweek on top.

    Bank and free transfers from squad.json always win when present, because
    the API's values are also a gameweek behind.
    """
    cfg = json.load(open(path))
    bank = cfg.get('bank')
    ft = cfg.get('free_transfers')

    if cfg.get('entry_id') and not offline:
        eid = cfg['entry_id']
        gw = max(1, e.NEXT - 1)
        picks = _api(f'/entry/{eid}/event/{gw}/picks/')
        if not picks or not picks.get('picks'):
            # Never let an API hiccup kill the run. squad.json's name list is
            # the fallback, and the brief says which source was used.
            print('WARNING: could not fetch your squad; falling back to the '
                  'player list in squad.json', file=sys.stderr)
            return _from_names(e, cfg, bank, ft)
        ids = [p['element'] for p in picks['picks']]

        pending = [t for t in (_api(f'/entry/{eid}/transfers/') or [])
                   if t.get('event') == e.NEXT]
        for t in reversed(pending):          # oldest first
            if t['element_out'] in ids:
                ids[ids.index(t['element_out'])] = t['element_in']
        if pending:
            names = ', '.join(
                f"{e.EL[t['element_out']]['web_name']} -> {e.EL[t['element_in']]['web_name']}"
                for t in reversed(pending))
            print(f'applied {len(pending)} pending transfer(s): {names}')

        if bank is None:
            bank = picks.get('entry_history', {}).get('bank', 0) / 10
        if ft is None:
            ft = 1
        return ids, bank, ft

    return _from_names(e, cfg, bank, ft)


def _norm_name(s):
    """Compare names without accents. squad.json is hand-edited, and typing
    Gross for Gro\u00df or Joao for Jo\u00e3o silently dropped players from the squad.
    """
    import unicodedata
    s = (s or '').replace('\u00df', 'ss')
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
    notes = cfg_extra.get('notes') or []
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
    ids, bank, ft = load_squad(e, a.squad, offline=a.offline)

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
    text = brief(e, ids, bank, ft, a.horizon, cfg_extra=json.load(open(a.squad)))

    sq = [(e.EL[i], e.PROJ[i]) for i in ids if i in e.EL]
    xi = best_eleven(e, sq)
    if xi:
        dest, count = save_predictions(e, xi)
        print(f'recorded {count} projections to {dest}')
    with open(a.out, 'w') as f:
        f.write(text)
    print(f'wrote {a.out} for GW{e.NEXT} ({len(ids)} players)')


if __name__ == '__main__':
    main()
