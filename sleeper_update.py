#!/usr/bin/env python3
"""Fetch Sleeper league data and write a public, compact snapshot for analysis."""
import json, os, urllib.request, datetime, pathlib, time

LEAGUE_ID = os.getenv('SLEEPER_LEAGUE_ID', '1389390949741793280')
USERNAME = os.getenv('SLEEPER_USERNAME', 'samswallows').casefold()
BASE = 'https://api.sleeper.app/v1'
OUT = pathlib.Path('data')
OUT.mkdir(exist_ok=True)

def get(path):
    url = BASE + path
    req = urllib.request.Request(url, headers={'User-Agent':'PersonalSleeperLeagueBridge/1.0'})
    for i in range(3):
        try:
            with urllib.request.urlopen(req, timeout=35) as r:
                return json.load(r)
        except Exception:
            if i == 2: raise
            time.sleep((i+1)*3)

def read_cached_players():
    cache = OUT / 'players_cache.json'
    if cache.exists():
        age = time.time() - cache.stat().st_mtime
        if age < 23*3600:
            return json.loads(cache.read_text())
    # Sleeper recommends fetching all players no more than once per day.
    players = get('/players/nfl')
    cache.write_text(json.dumps(players, separators=(',', ':')))
    return players

league = get(f'/league/{LEAGUE_ID}')
users = get(f'/league/{LEAGUE_ID}/users')
rosters = get(f'/league/{LEAGUE_ID}/rosters')
state = get('/state/nfl')
week = int(state.get('week') or state.get('display_week') or 1)
matchups = get(f'/league/{LEAGUE_ID}/matchups/{week}')
trends = get('/players/nfl/trending/add?lookback_hours=24&limit=100')
players = read_cached_players()

me = next((u for u in users if (u.get('username') or '').casefold() == USERNAME), None)
if not me:
    profile = get('/user/'+USERNAME)
    me = next((u for u in users if str(u.get('user_id')) == str(profile.get('user_id'))), None)
if not me:
    raise RuntimeError('Username was not found among league members. Verify SLEEPER_USERNAME.')

owned = {p for r in rosters for p in (r.get('players') or [])}
my_roster = next((r for r in rosters if str(r.get('owner_id')) == str(me.get('user_id'))), None)
if not my_roster:
    raise RuntimeError('Found Sleeper user but no matching roster.')

# Include rosters + trending names, and compact active unrostered player list.
def brief_player(pid):
    p = players.get(str(pid)) or {}
    return {'id':str(pid), 'name':p.get('full_name') or ' '.join(filter(None,[p.get('first_name'),p.get('last_name')])) or str(pid),
            'position':p.get('position'), 'team':p.get('team'),
            'status':p.get('status'), 'injury_status':p.get('injury_status'),
            'practice_participation':p.get('practice_participation'),
            'fantasy_positions':p.get('fantasy_positions')}

free_agents = [brief_player(pid) for pid,p in players.items()
               if pid not in owned and p.get('active') and
               set(p.get('fantasy_positions') or []).intersection({'QB','RB','WR','TE','K','DEF'})]
# Dataset is explicitly ALL active unrostered players, not speculative rankings.
snapshot = {
    'retrieved_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'source':'Sleeper public read-only API',
    'league':{'id':LEAGUE_ID,'name':league.get('name'),'season':league.get('season'),
              'status':league.get('status'),'settings':league.get('settings'),
              'scoring_settings':league.get('scoring_settings'),
              'roster_positions':league.get('roster_positions')},
    'nfl_state':state,
    'current_week':week,
    'my_user':{'username':USERNAME,'user_id':me.get('user_id'), 'roster_id':my_roster['roster_id']},
    'rosters':[
        {'roster_id':r['roster_id'], 'owner_id':r.get('owner_id'),
         'team_name':next((u.get('metadata',{}).get('team_name') or u.get('display_name') for u in users
                           if str(u.get('user_id'))==str(r.get('owner_id'))), None),
         'settings':r.get('settings'), 'starters':[brief_player(i) for i in r.get('starters') or []],
         'players':[brief_player(i) for i in r.get('players') or []],
         'reserve':[brief_player(i) for i in r.get('reserve') or []]}
         for r in rosters],
    'matchups':matchups,
    'trending_adds':[{'player':brief_player(t['player_id']), 'adds_24h':t.get('count'),
                      'available_in_league':str(t['player_id']) not in owned} for t in trends],
    'active_free_agents':free_agents,
    'notes':['Public player injury/practice fields can lag official reports. Verify with current team reports.',
             'This snapshot is a polling result, not a real-time streaming feed.',
             'Free-agent availability can change after retrieval.']
}
(OUT/'latest.json').write_text(json.dumps(snapshot, separators=(',', ':'), ensure_ascii=False))
print(f"Updated {OUT/'latest.json'}: {len(rosters)} rosters; {len(free_agents)} active free agents; week {week}.")
