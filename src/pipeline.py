import json
import ast
from collections import Counter
from pathlib import Path
from src.database import init_db, upsert_playlist, get_or_create_curator, upsert_contact_method, get_playlist_scoring_context, queue_email, playlist_outreach_guard
from src.outreach_generator import generate_outreach
from src.scorer import score_playlist
from src.similarity_engine import compute_similarity, compute_intersection_score, split_terms, suggest_expanded_band_candidates
from src.spotify_api import fetch_spotify_playlist
from src.settings import local_data_path
from src.web_enricher import enrich_contact_info
def merge_if_empty(target, source, keys):
    for k in keys:
        if source.get(k) and not target.get(k): target[k]=source[k]
def normalize_song_context(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    if isinstance(value, str):
        text=value.strip()
        if not text:
            return {}
        for parser in (json.loads, ast.literal_eval):
            try:
                parsed=parser(text)
            except (ValueError, SyntaxError, json.JSONDecodeError, TypeError):
                continue
            if isinstance(parsed, dict):
                return parsed
    return {}
def _num(value, default=0.0):
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default
def _nonempty_list(value):
    return value if isinstance(value, list) else []
def apply_discovery_targeting_score(scored, playlist):
    candidate_fit=_num(playlist.get('candidate_fit_score'))
    curator_target=_num(playlist.get('curator_target_score'))
    if not candidate_fit and not curator_target:
        return scored
    original=_num(scored.get('final_score'))
    target_adjusted=max(0,min(100,candidate_fit+(curator_target*.2)))
    final=max(original,target_adjusted)
    evidence=list(scored.get('evidence') or [])
    if _nonempty_list(playlist.get('discovery_intent_hits')):
        evidence.append('emerging artist discovery intent')
    if _nonempty_list(playlist.get('submission_ready_hits')):
        evidence.append('submission-friendly playlist language')
    if _nonempty_list(playlist.get('curator_identity_hits')):
        evidence.append('curator identity signal')
    if _nonempty_list(playlist.get('passive_context_hits')):
        evidence.append('passive context warning')
    scored={**scored,'final_score':round(final,2),'evidence':list(dict.fromkeys(evidence))}
    scored['priority']='strong fit' if final>=80 and scored.get('confidence_score',0)>=35 else scored.get('priority')
    scored['breakdown']={**(scored.get('breakdown') or {}),'song_specific_playlist_fit':round(candidate_fit,2),'curator_target_score':round(curator_target,2)}
    return scored
def process_playlists(playlists, do_web_enrichment=True, do_spotify_api=False, queue_email_approval=True, song_context=None, playlist_cooldown_days=30, minimum_queue_score=50):
    init_db(); processed=[]; related=Counter(); existing=get_playlist_scoring_context()
    for playlist in playlists:
        playlist=dict(playlist); contact={}
        if do_spotify_api and playlist.get('playlist_url'):
            spot=fetch_spotify_playlist(playlist.get('playlist_url',''))
            merge_if_empty(playlist,spot,['spotify_playlist_id','playlist_name','curator_name','spotify_description','related_artists','follower_count'])
            if spot.get('spotify_tracks'): playlist['spotify_tracks']=spot['spotify_tracks']
        if do_web_enrichment: contact=enrich_contact_info(playlist.get('playlist_name',''),playlist.get('curator_name',''),playlist.get('playlist_url',''))
        if contact.get('playlist_name_found') and not playlist.get('playlist_name'): playlist['playlist_name']=contact['playlist_name_found']
        if contact.get('curator_name_found') and not playlist.get('curator_name'): playlist['curator_name']=contact['curator_name_found']
        if contact.get('spotify_description') and not playlist.get('spotify_description'): playlist['spotify_description']=contact['spotify_description']
        active_song_context=normalize_song_context(song_context or playlist.get('song_context') or {})
        sim=compute_similarity(playlist); ix=compute_intersection_score(playlist,existing); scored=score_playlist(sim['similarity_score'],playlist.get('follower_count',0),playlist.get('last_updated',''),contact,ix['intersection_score']); scored=apply_discovery_targeting_score(scored,playlist); msg=generate_outreach(playlist,sim,active_song_context)
        notes=json.dumps({'score_breakdown':scored['breakdown'],'confidence_score':scored.get('confidence_score',0),'evidence':scored.get('evidence',[]),'intersection':ix,'submithub_verified':contact.get('submithub_verified',False),'submithub_url':contact.get('submithub_url','')},ensure_ascii=True)
        rec={**playlist,'similarity_score':sim['similarity_score'],'intersection_score':ix['intersection_score'],'intersection_breakdown':ix,'similarity_breakdown':sim['breakdown'],'final_score':scored['final_score'],'priority':scored['priority'],'rating_confidence':scored.get('confidence_score',0),'rating_evidence':scored.get('evidence',[]),'email':contact.get('email'),'instagram':contact.get('instagram'),'website':contact.get('website'),'submission_page':contact.get('submission_page'),'link_hub':contact.get('link_hub'),'submithub_verified':contact.get('submithub_verified',False),'submithub_url':contact.get('submithub_url',''),'submithub_confidence':contact.get('submithub_confidence',0),'contact_confidence':contact.get('confidence_score',0),'contact_methods':contact.get('contact_methods',[]),**msg}
        cid=get_or_create_curator(rec.get('curator_name') or 'Unknown Curator')
        pid=upsert_playlist({'curator':rec.get('curator_name'),'name':rec.get('playlist_name'),'url':rec.get('playlist_url'),'followers':rec.get('follower_count'),'related_artists':rec.get('related_artists'),'spotify_description':rec.get('spotify_description'),'similarity_score':rec.get('similarity_score'),'intersection_score':rec.get('intersection_score'),'final_score':rec.get('final_score'),'priority':rec.get('priority'),'spotify_playlist_id':rec.get('spotify_playlist_id',''),'submithub_verified':rec.get('submithub_verified',False),'submithub_url':rec.get('submithub_url',''),'scoring_notes':notes})
        for m in rec['contact_methods']: upsert_contact_method(cid,m)
        guard=playlist_outreach_guard(pid,active_song_context,playlist_cooldown_days)
        rec['outreach_guard']=guard
        rec['email_queue_blocked']=False
        rec['email_queue_block_reason']=''
        if queue_email_approval and rec.get('email'):
            if float(rec.get('final_score') or 0)<float(minimum_queue_score or 0):
                rec['email_queue_blocked']=True
                rec['email_queue_block_reason']=f"Score {rec.get('final_score')} is below the queue threshold of {minimum_queue_score}."
            elif guard.get('allowed'):
                rec['email_queue_id']=queue_email(cid,pid,rec['email'],f"Submission for {rec.get('playlist_name') or 'your playlist'}",rec.get('email_message',''),song_context=active_song_context,cooldown_days=playlist_cooldown_days)
            else:
                rec['email_queue_blocked']=True
                rec['email_queue_block_reason']=guard.get('reason','Playlist cooldown is active.')
        rec['curator_id']=cid; rec['playlist_id']=pid
        for a in split_terms(playlist.get('related_artists','')): related[a]+=1
        processed.append(rec)
    top=sorted(processed,key=lambda x:x.get('final_score',0),reverse=True)[:10]; contactable=[p for p in processed if p.get('email') or p.get('instagram') or p.get('website') or p.get('submission_page')]
    report={'total_playlists_processed':len(processed),'contactable_curators_count':len(contactable),'contactable_curators_percent':round((len(contactable)/len(processed))*100,2) if processed else 0,'top_10_playlists_by_score':top,'most_common_related_artists_found':related.most_common(20),'expanded_band_candidates':suggest_expanded_band_candidates(processed)['suggested_new_artists'],'processed_playlists':processed}
    local_data_path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); return report
