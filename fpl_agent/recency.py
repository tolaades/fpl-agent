"""Per-gameweek minutes, weighted toward the most recent match.

Season totals cannot distinguish "started GW1, benched GW2" from "benched GW1,
started GW2". For predicting the next lineup those are opposite signals, and
the ratio of starts to matches treats them identically.

This pulls each player's match-by-match minutes from the element-summary
endpoint and weights them so the last match matters most. A player who has just
broken into the XI stops being scored as a rotation risk, and one who has just
lost his place stops being scored as nailed.
"""
import json, time, urllib.request
from collections import defaultdict

API = 'https://fantasy.premierleague.com/api'
UA = 'Mozilla/5.0 (compatible; fpl-agent/1.0)'

DECAY = 0.55        # weight of each match relative to the one after it
FULL_MATCH = 60     # minutes that count as a genuine start


def fetch_recent_minutes(player_ids, pause=0.05, timeout=30):
    """{player_id: [minutes, ...]} oldest first. Failures are skipped, not fatal."""
    out = {}
    for pid in player_ids:
        try:
            req = urllib.request.Request(f'{API}/element-summary/{pid}/',
                                         headers={'User-Agent': UA})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = json.loads(r.read())
            per_gw = defaultdict(int)
            for h in data.get('history', []):
                per_gw[h['round']] += h['minutes']
            if per_gw:
                out[pid] = [per_gw[k] for k in sorted(per_gw)]
        except Exception:
            continue
        time.sleep(pause)
    return out


def weighted_start_rate(minutes_list):
    """Recency-weighted (start probability, minutes share) from match history."""
    if not minutes_list:
        return None
    n = len(minutes_list)
    weights = [DECAY ** (n - 1 - i) for i in range(n)]
    total_w = sum(weights)
    started, share = 0.0, 0.0
    for w, m in zip(weights, minutes_list):
        # A substitute appearance is partial evidence of a start, not none.
        started += w * (1.0 if m >= FULL_MATCH else (m / FULL_MATCH) * 0.5)
        share += w * min(1.0, m / 90.0)
    return started / total_w, share / total_w
