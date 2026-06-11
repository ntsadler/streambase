import json
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path
def refs(path='data/band_references.json'): return json.loads(Path(path).read_text(encoding='utf-8'))
def split_terms(text): return [x.strip() for x in (text or '').replace('|',';').replace(',',';').split(';') if x.strip()]
def norm(text): return (text or '').strip().lower()
def ratio(a,b): return SequenceMatcher(None,a.lower(),b.lower()).ratio()
def matches(h,n): return n.lower() in h.lower() or ratio(h,n)>=0.82
def track_artists(playlist):
    artists=[]
    for t in playlist.get('spotify_tracks') or []:
        artists.extend(t.get('artists') or [])
    return [a for a in artists if a]
def artist_set(playlist):
    return {norm(a) for a in split_terms(str(playlist.get('related_artists',''))) + track_artists(playlist) if norm(a)}
def compute_similarity(playlist, refs_path='data/band_references.json'):
    r=refs(refs_path); hay=' '.join(str(playlist.get(k,'')) for k in ['playlist_name','curator_name','related_artists','spotify_description'])
    breakdown=[]; score=0.0
    for band,w in r.get('core_bands',{}).items():
        if matches(hay,band): pts=32*w; score+=pts; breakdown.append({'match':band,'type':'core_band','points':round(pts,2)})
    for band,w in r.get('expanded_bands',{}).items():
        if matches(hay,band): pts=22*w; score+=pts; breakdown.append({'match':band,'type':'expanded_band','points':round(pts,2)})
    for tag,w in r.get('vibe_tags',{}).items():
        if matches(hay,tag): pts=12*w; score+=pts; breakdown.append({'match':tag,'type':'vibe_tag','points':round(pts,2)})
    return {'similarity_score':min(100,round(score,2)),'breakdown':breakdown,'explanation':'Matched against reference universe.'}
def compute_intersection_score(playlist, existing_playlists=None, refs_path='data/band_references.json'):
    r=refs(refs_path); existing_playlists=existing_playlists or []
    artists=artist_set(playlist); reference={norm(a):w for a,w in {**r.get('core_bands',{}),**r.get('expanded_bands',{})}.items()}
    reference_hits=[a for a in artists if any(matches(a,ref) for ref in reference)]
    track_matches=[]
    for t in playlist.get('spotify_tracks') or []:
        names=[norm(a) for a in t.get('artists') or []]
        if any(any(matches(a,ref) for ref in reference) for a in names):
            track_matches.append({'track':t.get('name',''),'artists':t.get('artists',[])})
    overlaps=[]
    for other in existing_playlists:
        if other.get('url') and other.get('url')==playlist.get('playlist_url'): continue
        shared=artists & {norm(a) for a in split_terms(str(other.get('related_artists',''))) if norm(a)}
        if shared: overlaps.append({'playlist':other.get('name',''), 'url':other.get('url',''), 'shared_artists':sorted(shared)})
    score=min(100,len(reference_hits)*18+len(track_matches)*10+len(overlaps)*12)
    return {'intersection_score':round(score,2),'reference_artist_hits':reference_hits,'track_artist_matches':track_matches[:10],'overlapping_playlists':overlaps[:10]}
def suggest_expanded_band_candidates(playlists, refs_path='data/band_references.json'):
    r=refs(refs_path); known={*r.get('core_bands',{}),*r.get('expanded_bands',{})}; kl={k.lower() for k in known}; c=Counter()
    for p in playlists:
        if float(p.get('final_score',0) or 0)<70: continue
        for a in split_terms(str(p.get('related_artists',''))):
            if a.lower() not in kl: c[a]+=1
    return {'suggested_new_artists':[{'artist':a,'appearances_in_high_scoring_playlists':n,'confidence_score':min(100,40+n*15)} for a,n in c.most_common(20)]}
