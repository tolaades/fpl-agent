"""Empirical Bayes priors from 2025/26, joined on the stable player `code`.

Replaces the crude positional prior with each player's own established rate,
weighted by how much evidence last season actually provides.
"""
import csv, json
from collections import defaultdict

HIST_PATH = '/home/claude/hist/players_raw_2025-26.csv'

# Confidence weights, in minutes.
HIST_K = 900.0    # how much last-season evidence before we trust it over positional
# How many minutes of current-season evidence before we trust it over the prior.
# Set per statistic by how quickly each one stabilises. Expected goals swing
# wildly match to match; defensive contributions barely move.
CUR_K = 400.0
STAT_K = dict(xg=700.0, xa=700.0, dc=250.0, bps=350.0, sv=300.0, gc=300.0, yc=600.0)

# League positional fallbacks, per 90.
POSITIONAL = {
    1: dict(xg=0.005, xa=0.005, dc=0.0,  bps=18.0, sv=2.60, gc=1.35, start=0.55),
    2: dict(xg=0.050, xa=0.040, dc=9.0,  bps=17.0, sv=0.0,  gc=1.35, start=0.55),
    3: dict(xg=0.130, xa=0.110, dc=7.5,  bps=16.0, sv=0.0,  gc=1.30, start=0.55),
    4: dict(xg=0.210, xa=0.170, dc=3.5,  bps=17.0, sv=0.0,  gc=1.25, start=0.55),
}

def _f(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def load_history(path=HIST_PATH):
    """code -> per-90 rates plus a nailed-ness estimate from last season."""
    out = {}
    for r in csv.DictReader(open(path)):
        m = _f(r.get('minutes'))
        if m < 180:          # too little to be worth anything
            continue
        per90 = lambda k: _f(r.get(k)) / m * 90
        out[r['code']] = dict(
            minutes=m,
            xg=per90('expected_goals'),
            xa=per90('expected_assists'),
            gc=per90('expected_goals_conceded'),
            dc=_f(r.get('defensive_contribution')) / m * 90,
            bps=per90('bps'),
            sv=per90('saves'),
            yc=per90('yellow_cards'),
            start=min(1.0, _f(r.get('starts')) / 38.0),
            element_type=int(_f(r.get('element_type'), 3)),
            points=_f(r.get('total_points')),
            has_dc='defensive_contribution' in r,
        )
    return out


def build_priors(elements, hist):
    """For each current player, blend last season's rate with the positional mean.

    A player with 3,000 minutes last season is trusted almost entirely on his
    own record. One with 300 is pulled most of the way back to his position's
    average. One with none (promoted clubs, new signings) gets the positional
    average outright.
    """
    priors, coverage = {}, dict(own=0, none=0)
    for p in elements:
        pos = POSITIONAL[p['element_type']]
        h = hist.get(str(p['code']))
        if not h:
            priors[p['id']] = dict(pos, source='positional', hist_minutes=0.0)
            coverage['none'] += 1
            continue
        w = h['minutes'] / (h['minutes'] + HIST_K)
        blended = {k: w * h[k] + (1 - w) * pos[k] for k in
                   ('xg', 'xa', 'dc', 'bps', 'sv', 'gc', 'start')}
        priors[p['id']] = dict(blended, source='own', hist_minutes=h['minutes'],
                               hist_weight=w, hist_points=h['points'])
        coverage['own'] += 1
    return priors, coverage


def shrink_to_prior(observed_total, current_minutes, prior_rate, stat=None, k=None):
    """Blend this season's observed per-90 rate toward the player's prior."""
    if k is None:
        k = STAT_K.get(stat, CUR_K)
    obs = (observed_total / current_minutes) * 90 if current_minutes > 0 else 0.0
    w = current_minutes / (current_minutes + k)
    return w * obs + (1 - w) * prior_rate
