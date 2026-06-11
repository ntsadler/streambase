import json
from collections import Counter
from pathlib import Path
from src.database import init_db, upsert_playlist, get_or_create_curator, upsert_contact_method, get_playlist_scoring_context, queue_email
from src.outreach_generator import generate_outreach
from src.scorer import score_playlist
from src.similarity_engine import compute_similarity, compute_intersection_score, split_terms, suggest_expanded_band_candidates
from src.spotify_api import fetch_spotify_playlist
from src.settings import local_data_path
from src.web_enricher import enrich_contact_info
def merge_if_empty(target, source, keys):
    for k in keys:
        if source.get(k) and not target.get(k): target[k]=source[k]
def process_playlists(playlists, do_web_enrichment=True, do_spotify_api=False, queue_email_approval=True):
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
        sim=compute_similarity(playlist); ix=compute_intersection_score(playlist,existing); scored=score_playlist(sim['similarity_score'],playlist.get('follower_count',0),playlist.get('last_updated',''),contact,ix['intersection_score']); msg=generate_outreach(playlist,sim)
        notes=json.dumps({'score_breakdown':scored['breakdown'],'intersection':ix},ensure_ascii=True)
        rec={**playlist,'similarity_score':sim['similarity_score'],'intersection_score':ix['intersection_score'],'intersection_breakdown':ix,'similarity_breakdown':sim['breakdown'],'final_score':scored['final_score'],'priority':scored['priority'],'email':contact.get('email'),'instagram':contact.get('instagram'),'website':contact.get('website'),'submission_page':contact.get('submission_page'),'link_hub':contact.get('link_hub'),'contact_confidence':contact.get('confidence_score',0),'contact_methods':contact.get('contact_methods',[]),**msg}
        cid=get_or_create_curator(rec.get('curator_name') or 'Unknown Curator')
        pid=upsert_playlist({'curator':rec.get('curator_name'),'name':rec.get('playlist_name'),'url':rec.get('playlist_url'),'followers':rec.get('follower_count'),'related_artists':rec.get('related_artists'),'spotify_description':rec.get('spotify_description'),'similarity_score':rec.get('similarity_score'),'intersection_score':rec.get('intersection_score'),'final_score':rec.get('final_score'),'priority':rec.get('priority'),'spotify_playlist_id':rec.get('spotify_playlist_id',''),'scoring_notes':notes})
        for m in rec['contact_methods']: upsert_contact_method(cid,m)
        if queue_email_approval and rec.get('email'): rec['email_queue_id']=queue_email(cid,pid,rec['email'],f"Submission for {rec.get('playlist_name') or 'your playlist'}",rec.get('email_message',''))
        rec['curator_id']=cid; rec['playlist_id']=pid
        for a in split_terms(playlist.get('related_artists','')): related[a]+=1
        processed.append(rec)
    top=sorted(processed,key=lambda x:x.get('final_score',0),reverse=True)[:10]; contactable=[p for p in processed if p.get('email') or p.get('instagram') or p.get('website') or p.get('submission_page')]
    report={'total_playlists_processed':len(processed),'contactable_curators_count':len(contactable),'contactable_curators_percent':round((len(contactable)/len(processed))*100,2) if processed else 0,'top_10_playlists_by_score':top,'most_common_related_artists_found':related.most_common(20),'expanded_band_candidates':suggest_expanded_band_candidates(processed)['suggested_new_artists'],'processed_playlists':processed}
    local_data_path('report.json').write_text(json.dumps(report,indent=2),encoding='utf-8'); return report
