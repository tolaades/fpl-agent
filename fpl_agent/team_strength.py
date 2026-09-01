"""Team strength from results, replacing FPL's preseason difficulty buckets.

FDR is fixed before the season and never updates, so it cannot know that
Coventry have failed to score in either match. This fits attack and defence
ratings from goals actually scored and conceded, shrunk hard toward a
preseason baseline because two matches is a very small sample, then converts
them into an expected goal count for each side of each fixture.

From those two numbers everything else follows: clean sheet probability is
the Poisson chance of zero goals against, and the attacking multiplier is the
team's expected goals relative to the league average.
"""
from collections import defaultdict

GAMES_K = 4.0          # matches of evidence before results outweigh the baseline
HOME_ADV = 1.18        # home teams score ~18% more
LEAGUE_GOALS = 1.45    # goals per team per match


def build_team_strength(fixtures, teams):
    played = defaultdict(int)
    gf = defaultdict(float)
    ga = defaultdict(float)
    for f in fixtures:
        if not f['started'] or f['team_h_score'] is None:
            continue
        h, a = f['team_h'], f['team_a']
        # strip the home advantage out before rating the teams
        gf[h] += f['team_h_score'] / HOME_ADV
        ga[h] += f['team_a_score'] * HOME_ADV
        gf[a] += f['team_a_score'] * HOME_ADV
        ga[a] += f['team_h_score'] / HOME_ADV
        played[h] += 1
        played[a] += 1

    # Preseason baseline from FPL's overall strength rating (2 = weakest,
    # 5 = strongest). Better teams score more and concede less.
    base_att, base_def = {}, {}
    for t in teams:
        s = (t['strength_overall_home'] + t['strength_overall_away']) / 2.0
        z = (s - 3.5) / 1.5                    # roughly -1 .. +1
        base_att[t['id']] = 1.0 + 0.42 * z
        base_def[t['id']] = 1.0 - 0.42 * z     # lower is a better defence

    att, dfn = {}, {}
    for t in teams:
        i = t['id']
        n = played[i]
        w = n / (n + GAMES_K)
        obs_a = (gf[i] / n) / LEAGUE_GOALS if n else 1.0
        obs_d = (ga[i] / n) / LEAGUE_GOALS if n else 1.0
        att[i] = max(0.35, w * obs_a + (1 - w) * base_att[i])
        dfn[i] = max(0.35, w * obs_d + (1 - w) * base_def[i])
    return att, dfn, played


def expected_goals(att, dfn, team, opponent, home):
    """Expected goals for `team`, and against them, in this fixture."""
    scored = LEAGUE_GOALS * att[team] * dfn[opponent] * (HOME_ADV if home else 1 / HOME_ADV)
    conceded = LEAGUE_GOALS * att[opponent] * dfn[team] * (1 / HOME_ADV if home else HOME_ADV)
    return scored, conceded


def clean_sheet_prob(conceded):
    """Poisson probability of keeping the opponent to zero."""
    import math
    return math.exp(-conceded)
