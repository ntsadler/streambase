import csv, json, re
from io import StringIO
from pathlib import Path
from typing import Any, Dict, List, Optional
from src.settings import local_data_path
COLUMN_ALIASES={
 'playlist_name':['playlist_name','name','playlist','title','playlist name'],
 'playlist_url':['playlist_url','url','spotify_url','playlist link','link','playlist url'],
 'follower_count':['follower_count','followers','saves','likes','total_followers','playlist followers'],
 'curator_name':['curator_name','curator','owner','profile_name','user','playlist owner'],
 'related_artists':['related_artists','artists','artist_names','tracks_artists','track artists'],
 'last_updated':['last_updated','updated','recency','date_updated','last updated'],}
def clean_string(v): return '' if v is None else str(v).strip()
def parse_int(v):
    raw=clean_string(v).lower().replace(',','').replace('+','')
    if not raw: return 0
    mult=1
    if raw.endswith('k'): mult=1000; raw=raw[:-1]
    elif raw.endswith('m'): mult=1000000; raw=raw[:-1]
    m=re.search(r'\d+(\.\d+)?',raw)
    return int(float(m.group(0))*mult) if m else 0
def find_column(row,target):
    norm={str(k).strip().lower():k for k in row.keys()}
    for a in COLUMN_ALIASES.get(target,[]):
        if a.lower() in norm: return norm[a.lower()]
    return None
def normalize_row(row):
    def get(t):
        c=find_column(row,t); return clean_string(row.get(c)) if c else ''
    return {'playlist_name':get('playlist_name'),'playlist_url':get('playlist_url'),'follower_count':parse_int(get('follower_count')),'curator_name':get('curator_name'),'related_artists':get('related_artists'),'last_updated':get('last_updated'),'spotify_description':''}
def normalize_rows(rows):
    out=[normalize_row(r) for r in rows]
    return [r for r in out if r['playlist_name'] or r['playlist_url']]
def load_playlists_from_text(txt): return normalize_rows(list(csv.DictReader(StringIO(txt))))
def extract_spotify_playlist_links(raw):
    text=raw or ''
    links=[]
    for match in re.finditer(r'https?://open\.spotify\.com/playlist/[A-Za-z0-9]+(?:\?[^ \n\r\t<]*)?',text):
        links.append(match.group(0).split('?')[0])
    for match in re.finditer(r'spotify:playlist:([A-Za-z0-9]+)',text):
        links.append(f"https://open.spotify.com/playlist/{match.group(1)}")
    if not links:
        links=[line.strip() for line in text.splitlines() if line.strip()]
    return list(dict.fromkeys(links))
def playlists_from_links(raw):
    return [{'playlist_name':'','playlist_url':u,'follower_count':0,'curator_name':'','related_artists':'','last_updated':'','spotify_description':''} for u in extract_spotify_playlist_links(raw)]
def save_raw_json(playlists, output_path=None):
    p=Path(output_path) if output_path else local_data_path('playlists_raw.json'); p.parent.mkdir(parents=True,exist_ok=True); p.write_text(json.dumps(playlists,indent=2),encoding='utf-8')
