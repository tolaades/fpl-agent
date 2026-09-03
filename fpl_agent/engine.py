"""Projection engine: turns an FPL snapshot into per-gameweek expected points."""
import json, math
from collections import defaultdict

from .priors import load_history, build_priors, shrink_to_prior
from .recency import weighted_start_rate
from .team_strength import (build_team_strength, expected_goals,
                            clean_sheet_prob, LEAGUE_GOALS)

POS = {1: 'GKP', 2: 'DEF', 3: 'MID', 4: 'FWD'}


def build(bootstrap_path, fixtures_path, history_path, horizon=5, recent=None):
    """Load a snapshot and return a namespace with everything projected.

    recent: optional {player_id: [minutes per gameweek]} from recency.py.
    """
    recent = recent or {}
    B = json.load(open(bootstrap_path))
    FX = json.load(open(fixtures_path))
    TEAMS = {t['id']: t for t in B['teams']}
    SC = B['game_config']['scoring']
    NEXT = [e for e in B['events'] if e['is_next']][0]['id']
    GWS = list(range(NEXT, NEXT + horizon))
    ATT_R, DEF_R, _ = build_team_strength(FX, B['teams'])

    TF = defaultdict(lambda: defaultdict(list))
    for f in FX:
        if not f['event'] or f['event'] < NEXT:
            continue
        dh, da = f['team_h_difficulty'], f['team_a_difficulty']
        hs, hc = expected_goals(ATT_R, DEF_R, f['team_h'], f['team_a'], True)
        as_, ac = expected_goals(ATT_R, DEF_R, f['team_a'], f['team_h'], False)
        TF[f['team_h']][f['event']].append(dict(
            opp=TEAMS[f['team_a']]['short_name'], home=True,
            fdr=dh, gap=da - dh, xgf=hs, xga=hc))
        TF[f['team_a']][f['event']].append(dict(
            opp=TEAMS[f['team_h']]['short_name'], home=False,
            fdr=da, gap=dh - da, xgf=as_, xga=ac))

    HIST = load_history(history_path)
    PRIORS, COVERAGE = build_priors(B['elements'], HIST)

    PLAYED = {t: 0 for t in TEAMS}
    for f in FX:
        if f['started']:
            PLAYED[f['team_h']] += 1
            PLAYED[f['team_a']] += 1

    PRIOR_MIN = 260
    ATT = {1: 1.30, 2: 1.18, 3: 1.00, 4: 0.85, 5: 0.72}
    CS = {1: 0.52, 2: 0.40, 3: 0.29, 4: 0.19, 5: 0.11}
    DCT = {1: 999, 2: 10, 3: 12, 4: 12}   # defensive-contribution thresholds

    def shrink(total, mins, prior):
        obs = (total / mins) * 90 if mins > 0 else 0.0
        w = mins / (mins + PRIOR_MIN)
        return w * obs + (1 - w) * prior


    def p_tail(rate, thresh, mins):
        if thresh > 100:
            return 0.0
        lam = rate * (mins / 90)
        if lam <= 0:
            return 0.0
        cum, term = 0.0, math.exp(-lam)
        for k in range(thresh):
            cum += term
            term *= lam / (k + 1)
        return max(0.0, min(1.0, 1 - cum))


    def minutes_profile(p):
        st = p['status']
        ch = p['chance_of_playing_next_round']
        if ch is None:
            ch = 100 if st == 'a' else 0
        if st in ('u', 'n'):
            return dict(p_play=0, p_start=0, xmins=0, flag='unavailable')

        tm = max(1, PLAYED[p['team']])          # matches the CLUB has played
        rec = weighted_start_rate(recent.get(p['id']))
        if rec:
            # Per-match history available: weight the latest appearance most,
            # so a player who has just broken into the XI is not scored as a
            # rotation risk on the strength of an earlier benching.
            start_share, share = rec
            conf = min(0.88, tm / (tm + 0.6))
        else:
            # Season totals only. These cannot distinguish a recent promotion
            # from a recent demotion, so stay closer to the prior.
            share = min(1.0, p['minutes'] / (90.0 * tm))
            start_share = min(1.0, p['starts'] / tm)
            conf = tm / (tm + 1.0)              # 1 match -> 0.50, 2 -> 0.67
        raw = 0.65 * start_share + 0.35 * share
        p_start = conf * raw + (1 - conf) * PRIORS[p['id']]['start']
        p_start *= ch / 100
        p_play = min(0.98, p_start + (1 - p_start) * 0.35 * (ch / 100))
        xmins = p_start * 84 + (p_play - p_start) * 22
        flag = {'i': 'injured', 'd': 'doubt', 's': 'suspended'}.get(st)
        return dict(p_play=p_play, p_start=p_start, xmins=xmins, flag=flag)


    def project_fixture(p, fx, prof):
        et = p['element_type']; pos = POS[et]; fdr = fx['fdr']
        pr = PRIORS[p['id']]
        m = prof['xmins']
        if m <= 0:
            return 0.0, {}
        scale = m / 90
        venue = 1.07 if fx['home'] else 0.94
        # The absolute FDR says how hard your fixture is; the gap between the two
        # sides' ratings says who is actually favoured. City at home to Coventry
        # and Brentford at home to Sunderland are both "FDR 2", but the first is a
        # three-point mismatch and the second is one.
        # Attacking output scales with how many goals we expect this team to score;
        # defensive returns with how few we expect them to concede.
        xgf, xga = fx['xgf'], fx['xga']
        team_att = xgf / LEAGUE_GOALS
        cm = p['minutes']
        p60 = prof['p_start'] * 0.88
        app = (prof['p_play'] - p60) * SC['short_play'] + p60 * SC['long_play']

        xg = shrink_to_prior(float(p['expected_goals']), cm, pr['xg'], 'xg')
        xa = shrink_to_prior(float(p['expected_assists']), cm, pr['xa'], 'xa')
        adj = team_att * scale
        goals = SC['goals_scored'][pos] * xg * adj
        assists = SC['assists'] * xa * adj

        csp = min(0.75, clean_sheet_prob(xga)) * prof['p_start']
        cs = SC['clean_sheets'][pos] * csp

        gc = shrink_to_prior(float(p['expected_goals_conceded']), cm, pr['gc'], 'gc')
        conceded = SC['goals_conceded'][pos] * (min(gc, xga) * scale * 0.5)

        dcr = shrink_to_prior(p['defensive_contribution'], cm, pr['dc'], 'dc')
        dc = SC['defensive_contribution'][pos] * p_tail(dcr, DCT[et], m) * prof['p_start']

        sv = shrink_to_prior(p['saves'], cm, pr['sv'], 'sv')
        saves = (sv * scale * (xga / LEAGUE_GOALS)) / 3 if et == 1 else 0.0

        bps = shrink_to_prior(p['bps'], cm, pr['bps'], 'bps') * scale
        bonus = max(0.0, (bps - 19) / 9) * prof['p_start']

        cards = SC['yellow_cards'] * shrink_to_prior(p['yellow_cards'], cm, 0.16, 'yc') * scale

        tot = app + goals + assists + cs + conceded + dc + saves + bonus + cards
        return max(0.0, tot), dict(app=app, att=goals + assists, cs=cs + conceded,
                                   dc=dc, sv=saves, bonus=bonus, cards=cards)


    def project(p):
        prof = minutes_profile(p)
        per, parts_sum = [], defaultdict(float)
        for gw in GWS:
            fxs = TF[p['team']].get(gw, [])
            if not fxs:
                per.append(dict(gw=gw, xp=0.0, fx=[], blank=True))
                continue
            s = 0.0; det = []
            for fx in fxs:
                v, parts = project_fixture(p, fx, prof)
                s += v; det.append(dict(fx, xp=v))
                for k, val in parts.items():
                    parts_sum[k] += val
            per.append(dict(gw=gw, xp=s, fx=det, blank=False))
        ep = float(p['ep_next'] or 0)
        if per[0]['xp'] > 0 and ep > 0:
            per[0]['xp'] = 0.55 * per[0]['xp'] + 0.45 * ep
        return dict(per=per, total=sum(g['xp'] for g in per), prof=prof, parts=dict(parts_sum))



    PROJ = {p['id']: project(p) for p in B['elements']}
    EL = {p['id']: p for p in B['elements']}

    class Engine:
        pass
    e = Engine()
    for k, v in dict(B=B, FX=FX, TEAMS=TEAMS, SC=SC, NEXT=NEXT, GWS=GWS,
                     ATT_R=ATT_R, DEF_R=DEF_R, TF=TF, PRIORS=PRIORS,
                     COVERAGE=COVERAGE, PLAYED=PLAYED, PROJ=PROJ, EL=EL,
                     POS=POS, project_fixture=project_fixture,
                     expected_goals=expected_goals,
                     clean_sheet_prob=clean_sheet_prob).items():
        setattr(e, k, v)
    return e
