"""Selection under FPL's real constraints.

best_eleven and rank_transfers work on the squad you already own.
optimise solves for a whole squad from scratch and needs pulp; it is only
used for wildcard and free hit planning, so the import is deferred.
"""
from collections import defaultdict
from itertools import product, combinations

SQUAD_LIMITS = {1: 2, 2: 5, 3: 5, 4: 3}
XI_MIN = {1: 1, 2: 3, 3: 2, 4: 1}
XI_MAX = {1: 1, 2: 5, 3: 5, 4: 3}


def best_eleven(e, squad, gw_index=0):
    """Highest-scoring legal XI from 15, plus bench order and captain."""
    def by(t):
        return sorted([s for s in squad if s[0]['element_type'] == t],
                      key=lambda s: -s[1]['per'][gw_index]['xp'])
    gk, df, md, fw = by(1), by(2), by(3), by(4)
    best = None
    for d, m, f in product(range(3, 6), range(2, 6), range(1, 4)):
        if 1 + d + m + f != 11:
            continue
        if not gk or len(df) < d or len(md) < m or len(fw) < f:
            continue
        xi = [gk[0]] + df[:d] + md[:m] + fw[:f]
        score = sum(s[1]['per'][gw_index]['xp'] for s in xi)
        if best is None or score > best['score']:
            best = dict(xi=xi, score=score, formation=f'{d}-{m}-{f}')
    if best is None:
        return None
    chosen = {s[0]['id'] for s in best['xi']}
    best['bench'] = sorted(
        [s for s in squad if s[0]['id'] not in chosen],
        key=lambda s: (s[0]['element_type'] == 1, -s[1]['per'][gw_index]['xp']))
    best['captain'] = max(best['xi'], key=lambda s: s[1]['per'][gw_index]['xp'])
    return best


def rank_transfers(e, squad, bank, limit=200):
    """Single swaps ranked by gain across the whole horizon.

    Selling price is approximated by current price, which is right unless a
    player has risen since you bought him.
    """
    owned = {p['id'] for p, _ in squad}
    club = defaultdict(int)
    for p, _ in squad:
        club[p['team']] += 1
    out = []
    for p, pr in squad:
        budget = p['now_cost'] + int(round(bank * 10))
        for c in e.B['elements']:
            if c['id'] in owned or c['element_type'] != p['element_type']:
                continue
            if c['now_cost'] > budget or c['status'] in ('u', 'n'):
                continue
            if club[c['team']] - (1 if c['team'] == p['team'] else 0) >= 3:
                continue
            gain = e.PROJ[c['id']]['total'] - pr['total']
            if gain <= 0.5:
                continue
            out.append(dict(out=p, into=c, gain=gain,
                            cost=c['now_cost'] - p['now_cost']))
    out.sort(key=lambda r: -r['gain'])
    # keep only the best destination for each incoming player
    seen, keep = set(), []
    for r in out:
        if r['into']['id'] in seen:
            continue
        seen.add(r['into']['id'])
        keep.append({'out': r['out'], 'in': r['into'],
                     'gain': r['gain'], 'cost': r['cost']})
        if len(keep) >= limit:
            break
    return keep


def optimise(e, budget, horizon_weeks=1, bench_weight=0.12, min_xmins=25):
    """Exact best 15 for a wildcard or free hit. Requires pulp."""
    import pulp
    pool = [p for p in e.B['elements']
            if p['status'] not in ('u', 'n')
            and e.PROJ[p['id']]['prof']['xmins'] >= min_xmins]

    def value(pid):
        return sum(g['xp'] for g in e.PROJ[pid]['per'][:horizon_weeks])

    prob = pulp.LpProblem('fpl', pulp.LpMaximize)
    s = {p['id']: pulp.LpVariable(f"s{p['id']}", cat='Binary') for p in pool}
    x = {p['id']: pulp.LpVariable(f"x{p['id']}", cat='Binary') for p in pool}
    c = {p['id']: pulp.LpVariable(f"c{p['id']}", cat='Binary') for p in pool}
    prob += pulp.lpSum(value(p['id']) * (bench_weight * s[p['id']]
                                         + (1 - bench_weight) * x[p['id']]
                                         + c[p['id']]) for p in pool)
    prob += pulp.lpSum(p['now_cost'] * s[p['id']] for p in pool) <= budget
    prob += pulp.lpSum(s.values()) == 15
    prob += pulp.lpSum(x.values()) == 11
    prob += pulp.lpSum(c.values()) == 1
    for p in pool:
        prob += x[p['id']] <= s[p['id']]
        prob += c[p['id']] <= x[p['id']]
    for t, n in SQUAD_LIMITS.items():
        prob += pulp.lpSum(s[p['id']] for p in pool
                           if p['element_type'] == t) == n
    for t in XI_MIN:
        sel = [x[p['id']] for p in pool if p['element_type'] == t]
        prob += pulp.lpSum(sel) >= XI_MIN[t]
        prob += pulp.lpSum(sel) <= XI_MAX[t]
    for cl in set(p['team'] for p in pool):
        prob += pulp.lpSum(s[p['id']] for p in pool if p['team'] == cl) <= 3
    prob.solve(pulp.PULP_CBC_CMD(msg=0))
    if pulp.LpStatus[prob.status] != 'Optimal':
        return None
    squad = [i for i in s if s[i].value() > 0.5]
    return dict(squad=squad,
                xi=[i for i in x if x[i].value() > 0.5],
                captain=[i for i in c if c[i].value() > 0.5][0],
                cost=sum(e.EL[i]['now_cost'] for i in squad))
