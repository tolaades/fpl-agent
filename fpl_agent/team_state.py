"""Read your actual team state from FPL rather than mirroring it by hand.

Every field here used to live in squad.json, which meant editing JSON after
every transfer and hoping it stayed in sync. It didn't: a transfer that was
drafted but never confirmed left the file describing a squad that did not
exist, and the brief was built on it.

FPL knows all of this. The only things that genuinely need writing down are
your chip *plan* and your notes, because those are intentions rather than facts.
"""
import json, sys, urllib.request

API = 'https://fantasy.premierleague.com/api'
UA = 'Mozilla/5.0 (compatible; fpl-agent/1.0)'
MAX_FREE_TRANSFERS = 5


def _get(path, timeout=60):
    req = urllib.request.Request(f'{API}{path}', headers={'User-Agent': UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def derive_free_transfers(history, chips, upcoming_gw):
    """Replay the season to work out how many free transfers are banked.

    One per gameweek, accumulating to a cap of five. A wildcard or free hit
    week consumes none. This is a reconstruction, not something the public API
    exposes directly, so treat it as close rather than certain and override in
    squad.json if it disagrees with the app.
    """
    chip_by_gw = {c['event']: c['name'] for c in chips}
    ft = 1
    for row in history:
        gw = row['event']
        if gw >= upcoming_gw:
            break
        if chip_by_gw.get(gw) not in ('wildcard', 'freehit'):
            ft = max(0, ft - row.get('event_transfers', 0))
        ft = min(MAX_FREE_TRANSFERS, ft + 1)
    return ft


def fetch_state(entry_id, upcoming_gw, elements_by_id=None):
    """Everything about your team, read from source.

    Returns squad ids (with this week's confirmed transfers already applied),
    bank in millions, free transfers, chips used, and a list of human-readable
    notes about what was found.
    """
    notes = []
    hist = _get(f'/entry/{entry_id}/history/')
    past = hist.get('current', [])
    chips = hist.get('chips', [])

    bank = (past[-1]['bank'] / 10.0) if past else 0.0
    value = (past[-1]['value'] / 10.0) if past else 0.0

    last_gw = max(1, upcoming_gw - 1)
    picks = _get(f'/entry/{entry_id}/event/{last_gw}/picks/')
    ids = [p['element'] for p in picks['picks']]

    # Transfers confirmed for the upcoming gameweek are not yet in picks.
    pending = [t for t in _get(f'/entry/{entry_id}/transfers/') or []
               if t.get('event') == upcoming_gw]
    for t in reversed(pending):
        if t['element_out'] in ids:
            ids[ids.index(t['element_out'])] = t['element_in']
            bank += (t['element_out_cost'] - t['element_in_cost']) / 10.0

    if pending and elements_by_id:
        moves = ', '.join(
            f"{elements_by_id[t['element_out']]['web_name']} -> "
            f"{elements_by_id[t['element_in']]['web_name']}"
            for t in reversed(pending))
        notes.append(f'{len(pending)} confirmed transfer(s) this week: {moves}')
    elif not pending:
        notes.append('No transfers confirmed for this gameweek yet. If you have '
                     'a move drafted in the app, it has not been submitted.')

    ft = derive_free_transfers(past, chips, upcoming_gw)
    ft = max(0, ft - len(pending))

    used = {c['name']: c['event'] for c in chips}
    if used:
        notes.append('Chips used: ' + ', '.join(
            f'{k} (GW{v})' for k, v in sorted(used.items(), key=lambda x: x[1])))

    return dict(squad=ids, bank=round(bank, 1), free_transfers=ft,
                chips_used=used, squad_value=value, notes=notes,
                pending=len(pending))
