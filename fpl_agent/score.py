#!/usr/bin/env python3
"""Score past predictions against what actually happened.

Every run of run_week.py writes predictions/gw{N}.json. Once gameweek N is
finished, this fetches the real points from /event/{N}/live/ and compares.

The output is deliberately blunt. The point is to find out whether the model is
systematically optimistic, whether the bias sits in one position, and whether
minutes projections hold up -- not to produce a flattering summary.

    python -m fpl_agent.score --out scorecard.md
"""
import argparse, json, os, glob, statistics, urllib.request, datetime

API = 'https://fantasy.premierleague.com/api'
UA = 'Mozilla/5.0 (compatible; fpl-agent/1.0)'


def _api(path, timeout=60):
    req = urllib.request.Request(f'{API}{path}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def actuals(gw):
    """{player_id: (points, minutes)} for a finished gameweek."""
    live = _api(f'/event/{gw}/live/')
    return {el['id']: (el['stats']['total_points'], el['stats']['minutes'])
            for el in live['elements']}


def score_gw(pred, act):
    """Compare one gameweek. Returns a dict of metrics."""
    rows = []
    for pid_s, info in pred['players'].items():
        pid = int(pid_s)
        if pid not in act:
            continue
        pts, mins = act[pid]
        rows.append(dict(id=pid, name=info['name'], pos=info['pos'],
                         xp=info['xp'], xmins=info['xmins'],
                         pts=pts, mins=mins))
    if not rows:
        return None

    # Only judge players the model expected to feature. Scoring the whole
    # database rewards correctly predicting that a reserve scores nothing.
    played = [r for r in rows if r['xmins'] >= 45]
    bias = statistics.mean(r['pts'] - r['xp'] for r in played)
    mae = statistics.mean(abs(r['pts'] - r['xp']) for r in played)

    by_pos = {}
    for pos in ('GKP', 'DEF', 'MID', 'FWD'):
        sel = [r for r in played if r['pos'] == pos]
        if sel:
            by_pos[pos] = dict(
                n=len(sel),
                pred=statistics.mean(r['xp'] for r in sel),
                act=statistics.mean(r['pts'] for r in sel))

    # Minutes calibration: of those the model expected to start, how many
    # actually lasted an hour? Early substitutions cost 1 point instead of 2
    # and wipe out clean sheet and defensive contribution returns.
    starters = [r for r in played if r['xmins'] >= 70]
    short = [r for r in starters if r['mins'] < 60]
    blanked = [r for r in starters if r['mins'] == 0]

    xi = pred.get('xi') or []
    cap = pred.get('captain')
    xi_pred = sum(pred['players'][str(i)]['xp'] for i in xi
                  if str(i) in pred['players'])
    xi_act = sum(act[i][0] for i in xi if i in act)
    if cap and cap in act:
        xi_pred += pred['players'][str(cap)]['xp']
        xi_act += act[cap][0]

    return dict(gw=pred['gw'], n=len(played), bias=bias, mae=mae,
                pred_mean=statistics.mean(r['xp'] for r in played),
                act_mean=statistics.mean(r['pts'] for r in played),
                by_pos=by_pos,
                starters=len(starters), short=len(short), blanked=len(blanked),
                xi_pred=xi_pred, xi_act=xi_act,
                worst=sorted(played, key=lambda r: r['pts'] - r['xp'])[:5],
                best=sorted(played, key=lambda r: r['xp'] - r['pts'])[:3])


def render(scores):
    L = ['# Model scorecard', '',
         f'_Updated {datetime.date.today():%d %b %Y}_', '']
    if not scores:
        L.append('No finished gameweeks scored yet.')
        return '\n'.join(L)

    L.append('## Summary')
    L.append('')
    L.append('| GW | Players | Predicted avg | Actual avg | Bias | MAE | XI+C pred | XI+C actual |')
    L.append('|---|---|---|---|---|---|---|---|')
    for s in scores:
        L.append('| %d | %d | %.2f | %.2f | %+.2f | %.2f | %.1f | %d |'
                 % (s['gw'], s['n'], s['pred_mean'], s['act_mean'],
                    s['bias'], s['mae'], s['xi_pred'], s['xi_act']))

    if len(scores) >= 3:
        b = statistics.mean(s['bias'] for s in scores)
        L += ['', '## Calibration', '',
              f'Mean bias across {len(scores)} gameweeks: **{b:+.2f} points per player**.']
        if abs(b) < 0.3:
            L.append('Within noise. No adjustment justified.')
        elif b < 0:
            L.append('The model is running **optimistic**. If this holds for '
                     'another two or three gameweeks it is calibration, not '
                     'variance, and the attacking and clean-sheet components '
                     'are where to look first.')
        else:
            L.append('The model is running **pessimistic**. Check whether the '
                     'shrinkage constants are pulling too hard toward priors.')
    else:
        L += ['', '## Calibration', '',
              f'Only {len(scores)} gameweek(s) scored. Too few to separate bias '
              'from variance -- do not tune anything yet. Five or six is the '
              'point at which this becomes readable.']

    L += ['', '## Minutes', '',
          '| GW | Expected to start | Played under 60 | Did not play |',
          '|---|---|---|---|']
    for s in scores:
        L.append('| %d | %d | %d | %d |'
                 % (s['gw'], s['starters'], s['short'], s['blanked']))
    L.append('')
    L.append('Early substitutions are expensive: 1 appearance point instead of '
             '2, no clean sheet, and usually no defensive contribution. If this '
             'column stays high the minutes model is the problem, not the '
             'attacking projections.')

    last = scores[-1]
    L += ['', f'## Biggest misses, GW{last["gw"]}', '',
          '| Player | Predicted | Actual | Error |', '|---|---|---|---|']
    for r in last['worst']:
        L.append('| %s | %.2f | %d | %+.2f |'
                 % (r['name'], r['xp'], r['pts'], r['pts'] - r['xp']))
    L += ['', '**By position, latest gameweek**', '',
          '| Pos | n | Predicted avg | Actual avg |', '|---|---|---|---|']
    for pos, d in last['by_pos'].items():
        L.append('| %s | %d | %.2f | %.2f |' % (pos, d['n'], d['pred'], d['act']))
    return '\n'.join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--predictions', default='./predictions')
    ap.add_argument('--out', default='scorecard.md')
    ap.add_argument('--store', default='./predictions/scores.json')
    a = ap.parse_args()

    boot = _api('/bootstrap-static/')
    finished = {e['id'] for e in boot['events'] if e['finished'] and e['data_checked']}

    store = {}
    if os.path.exists(a.store):
        store = json.load(open(a.store))

    for path in sorted(glob.glob(os.path.join(a.predictions, 'gw*.json'))):
        pred = json.load(open(path))
        gw = pred['gw']
        if gw not in finished or str(gw) in store:
            continue
        try:
            s = score_gw(pred, actuals(gw))
        except Exception as exc:
            print(f'could not score GW{gw}: {exc}')
            continue
        if s:
            store[str(gw)] = s
            print(f'scored GW{gw}: bias {s["bias"]:+.2f}, MAE {s["mae"]:.2f}')

    os.makedirs(os.path.dirname(a.store) or '.', exist_ok=True)
    json.dump(store, open(a.store, 'w'), indent=1)
    scores = [store[k] for k in sorted(store, key=int)]
    with open(a.out, 'w') as f:
        f.write(render(scores))
    print(f'wrote {a.out} ({len(scores)} gameweek(s))')


if __name__ == '__main__':
    main()
