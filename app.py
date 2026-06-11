import json, pandas as pd, streamlit as st
from src.chartmetric import chartmetric_status
from src.cyanite import cyanite_status,normalize_cyanite_tags
from src.database import init_db,get_curator_profiles,get_all_playlists,add_outreach_event,update_playlist_status,get_email_queue,update_email_queue_status,save_song_fit_targets,get_song_fit_targets
from src.ingest_playlists import load_playlists_from_text,playlists_from_links,save_raw_json
from src.pipeline import process_playlists
from src.settings import DB_PATH,LOCAL_DATA_DIR
from src.song_analyzer import analyze_song_fit,score_spotify_playlist_candidates
from src.spotify_api import SpotifyAPI,fetch_spotify_track,fetch_spotify_tracks,search_spotify_playlists
from src.web_enricher import enrich_playlist_from_url,enrich_track_from_url
st.set_page_config(page_title='Streambase',page_icon='🎛️',layout='wide')
st.title('🎛️ Streambase')
st.caption('Playlist intelligence, curator contact stack, and outreach CRM for independent music growth.')
init_db()
with st.sidebar:
    spotify=SpotifyAPI(); cm=chartmetric_status(); cy=cyanite_status()
    st.header('Settings'); do_web=st.toggle('Fetch public contact info',value=True); do_spotify=st.toggle('Use Spotify API connector',value=spotify.configured,disabled=not spotify.configured); queue_email=st.toggle('Queue emails for approval',value=True)
    st.markdown('#### Connector status')
    st.write(f"Spotify API: {'connected' if spotify.configured else 'not connected'}")
    st.write(f"Chartmetric: {'connected' if cm['configured']=='yes' else 'not connected'}")
    st.write(f"Cyanite: {'connected' if cy['configured']=='yes' else 'not connected'}")
    st.markdown('#### Local data')
    st.caption(f"Private data dir: {LOCAL_DATA_DIR}")
    st.caption(f"SQLite: {DB_PATH}")
    st.caption('Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to enable full playlist metadata, genres, and track matching.')
    st.divider(); st.write('Outreach stack: Email -> Instagram DM -> Submission page')
tab_import,tab_song,tab_results,tab_curators,tab_email=st.tabs(['Import & Analyze','Song Fit','Playlist Results','Curator CRM','Email Queue'])
if 'playlists' not in st.session_state: st.session_state.playlists=[]
if 'report' not in st.session_state: st.session_state.report=None
if 'song_fit' not in st.session_state: st.session_state.song_fit=None
if 'song_spotify' not in st.session_state: st.session_state.song_spotify={}
if 'reference_spotify_tracks' not in st.session_state: st.session_state.reference_spotify_tracks=[]
if 'spotify_playlist_candidates' not in st.session_state: st.session_state.spotify_playlist_candidates=[]
def df_session():
    df=pd.DataFrame(st.session_state.playlists) if st.session_state.playlists else pd.DataFrame(columns=['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description'])
    for col in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description']:
        if col not in df.columns: df[col]=0 if col=='follower_count' else ''
    return df
with tab_import:
    st.subheader('Import playlist data')
    mode=st.radio('Choose input method',['Paste Spotify playlist links','Upload CSV'],horizontal=True)
    if mode=='Paste Spotify playlist links':
        raw=st.text_area('Spotify playlist links',height=160,placeholder='https://open.spotify.com/playlist/...')
        c1,c2=st.columns(2)
        with c1:
            if st.button('Load pasted links',use_container_width=True): st.session_state.playlists=playlists_from_links(raw); st.success(f"Loaded {len(st.session_state.playlists)} playlist links.")
        with c2:
            if st.button('Fetch Spotify Details',use_container_width=True):
                if not st.session_state.playlists: st.error('Load playlist links first.')
                else:
                    updated=[]; prog=st.progress(0)
                    for i,row in enumerate(st.session_state.playlists):
                        row=dict(row); meta=enrich_playlist_from_url(row.get('playlist_url',''))
                        if meta.get('playlist_name') and not row.get('playlist_name'): row['playlist_name']=meta['playlist_name']
                        if meta.get('curator_name') and not row.get('curator_name'): row['curator_name']=meta['curator_name']
                        if meta.get('spotify_description'): row['spotify_description']=meta['spotify_description']
                        updated.append(row); prog.progress((i+1)/max(len(st.session_state.playlists),1))
                    st.session_state.playlists=updated; st.success('Spotify details fetched where available.')
    else:
        up=st.file_uploader('Choose CSV file',type=['csv'])
        if up: st.session_state.playlists=load_playlists_from_text(up.read().decode('utf-8-sig')); st.success(f"Loaded {len(st.session_state.playlists)} playlists from CSV.")
    if st.session_state.playlists:
        st.markdown('#### Edit details before analysis')
        st.caption('For a useful score, add related artists like `MGMT; LCD Soundsystem; Tame Impala` and follower counts if you know them.')
        edited=st.data_editor(df_session(),use_container_width=True,num_rows='dynamic')
        st.session_state.playlists=edited.fillna('').to_dict(orient='records')
        c1,c2=st.columns(2)
        with c1:
            if st.button('Analyze & Save to CRM',type='primary',use_container_width=True):
                with st.spinner('Scoring playlists, finding contacts, and saving curator profiles...'):
                    save_raw_json(st.session_state.playlists); st.session_state.report=process_playlists(st.session_state.playlists,do_web_enrichment=do_web,do_spotify_api=do_spotify,queue_email_approval=queue_email)
                st.success('Analysis complete. Curator CRM updated.')
        with c2:
            if st.button('Clear Import',use_container_width=True): st.session_state.playlists=[]; st.session_state.report=None; st.rerun()
with tab_song:
    st.subheader('Song playlist fit')
    song_link=st.text_input('Spotify song link',placeholder='https://open.spotify.com/track/...')
    c0a,c0b=st.columns(2)
    with c0a:
        if st.button('Fetch Spotify Song Metadata',use_container_width=True):
            if not song_link: st.error('Paste a Spotify track link first.')
            else:
                meta=fetch_spotify_track(song_link) if spotify.configured else {}
                if not meta: meta=enrich_track_from_url(song_link)
                st.session_state.song_spotify=meta
                if meta: st.success(f"Loaded metadata for {meta.get('title') or 'Spotify track'}.")
                else: st.warning('No Spotify metadata found. Add title, artist, references, and descriptors manually.')
    with c0b:
        if st.button('Clear Song Metadata',use_container_width=True):
            st.session_state.song_spotify={}; st.session_state.reference_spotify_tracks=[]; st.session_state.song_fit=None; st.rerun()
    reference_links=st.text_area('Reference song links',height=110,placeholder='Optional: paste 3-5 Spotify track links, one per line, that sound like your song.')
    if st.button('Fetch Reference Song Metadata',use_container_width=True):
        refs=[line.strip() for line in reference_links.splitlines() if line.strip()]
        if not refs: st.error('Paste at least one Spotify reference track link first.')
        elif not spotify.configured: st.error('Spotify API credentials are required for reference song metadata.')
        else:
            st.session_state.reference_spotify_tracks=fetch_spotify_tracks(refs)
            st.success(f"Loaded {len(st.session_state.reference_spotify_tracks)} reference song(s).")
    song_file=st.file_uploader('Upload song file',type=['wav','mp3','m4a','aiff','flac'])
    spotify_meta=st.session_state.song_spotify or {}
    if spotify_meta:
        st.markdown('#### Spotify metadata')
        st.json(spotify_meta,expanded=False)
    reference_meta=st.session_state.reference_spotify_tracks or []
    if reference_meta:
        st.markdown('#### Reference song metadata')
        st.dataframe(pd.DataFrame(reference_meta)[[c for c in ['title','artist','descriptors','popularity','release_date','spotify_url'] if c in pd.DataFrame(reference_meta).columns]],use_container_width=True,hide_index=True)
    c1,c2=st.columns(2)
    with c1:
        song_title=st.text_input('Song title',value=spotify_meta.get('title',''))
        song_artist=st.text_input('Artist name',value=spotify_meta.get('artist',''))
    with c2:
        song_refs=st.text_input('Reference artists',value=spotify_meta.get('reference_artists',''),placeholder='MGMT; LCD Soundsystem; Tame Impala')
        song_desc=st.text_input('Descriptors',value=spotify_meta.get('descriptors',''),placeholder='indie dance; synth; upbeat; late night')
    st.markdown('#### Audio intelligence')
    cyanite_raw=st.text_area('Cyanite tags JSON',height=100,placeholder='Optional: paste Cyanite genre/mood/tag JSON here when available.')
    cyanite_profile={}
    if cyanite_raw.strip():
        try:
            cyanite_profile=normalize_cyanite_tags(json.loads(cyanite_raw))
            st.success('Cyanite tags parsed.')
        except json.JSONDecodeError:
            st.error('Cyanite tags must be valid JSON.')
    if st.button('Analyze Song Fit',type='primary',use_container_width=True):
        if not song_file and not spotify_meta and not (song_title or song_artist or song_refs or song_desc): st.error('Upload a song, paste a Spotify track link, or add song details first.')
        else:
            st.session_state.song_fit=analyze_song_fit(song_file,song_title,song_artist,song_refs,song_desc,get_all_playlists(),spotify_meta,reference_meta,cyanite_profile)
    fit=st.session_state.song_fit
    if fit:
        summary=fit.get('audio_summary') or {}
        if summary:
            st.markdown('#### Audio summary')
            st.json(summary,expanded=False)
        spotify_summary=fit.get('spotify_summary') or {}
        if spotify_summary:
            st.markdown('#### Spotify summary')
            st.json(spotify_summary,expanded=False)
        reference_summary=fit.get('reference_track_summary') or {}
        if reference_summary:
            st.markdown('#### Reference song summary')
            st.json(reference_summary,expanded=False)
        cyanite_summary=fit.get('cyanite_summary') or {}
        if cyanite_summary:
            st.markdown('#### Cyanite summary')
            st.json(cyanite_summary,expanded=False)
        release_guidance=fit.get('release_guidance') or {}
        if release_guidance:
            st.markdown('#### Release guidance')
            if release_guidance.get('exclude_new_release_playlists'):
                st.warning(release_guidance.get('message'))
            else:
                st.info(release_guidance.get('message'))
            st.json(release_guidance,expanded=False)
        st.markdown('#### Recommended playlist lanes')
        lane_df=pd.DataFrame(fit.get('recommended_playlist_lanes',[]))
        if not lane_df.empty: st.dataframe(lane_df[['lane','score','matched_terms','pitch']],use_container_width=True,hide_index=True)
        matches=fit.get('saved_playlist_matches') or []
        st.markdown('#### Saved playlist matches')
        if matches:
            st.dataframe(pd.DataFrame(matches),use_container_width=True,hide_index=True)
            if st.button('Save Matches as Outreach Targets',use_container_width=True):
                saved=save_song_fit_targets(fit.get('song',{}),matches); st.success(f'Saved {saved} new outreach target(s).')
        else:
            st.info('No saved playlist matches yet. Add reference artists/descriptors or import more playlists to improve matching.')
        searches=fit.get('discovery_searches') or []
        if searches:
            st.markdown('#### Discovery searches')
            st.dataframe(pd.DataFrame(searches),use_container_width=True,hide_index=True)
            cfind1,cfind2=st.columns([1,1])
            with cfind1:
                per_query=st.number_input('Spotify results per search',min_value=1,max_value=10,value=5,step=1)
            with cfind2:
                market=st.text_input('Spotify market',value='US',max_chars=2)
            if st.button('Find Spotify Playlists',use_container_width=True,disabled=not spotify.configured):
                queries=[s.get('search_query','') for s in searches if s.get('search_query')]
                result=search_spotify_playlists(queries,int(per_query),market.upper() or 'US')
                if not result.get('ok'): st.error(result.get('error') or 'Spotify playlist search failed.')
                candidates=score_spotify_playlist_candidates(fit,result.get('playlists',[]),get_all_playlists())
                st.session_state.spotify_playlist_candidates=candidates
                st.success(f"Found {len(candidates)} scored playlist candidate(s).")
            if not spotify.configured:
                st.caption('Connect Spotify API credentials to search Spotify playlists from Song Fit.')
        candidates=st.session_state.spotify_playlist_candidates
        if candidates:
            st.markdown('#### Spotify playlist candidates')
            cand_df=pd.DataFrame(candidates)
            visible_cols=[c for c in ['candidate_fit_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','playlist_url','shared_reference_artists','matched_lanes'] if c in cand_df.columns]
            st.dataframe(cand_df[visible_cols],use_container_width=True,hide_index=True)
            fresh=[c for c in candidates if not c.get('already_in_crm')]
            csave1,csave2=st.columns(2)
            with csave1:
                if st.button('Stage Candidates in Import Queue',use_container_width=True):
                    st.session_state.playlists=[
                        {k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description']}
                        for c in fresh
                    ]
                    st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Import & Analyze.")
            with csave2:
                if st.button('Analyze & Save Candidates to CRM',use_container_width=True):
                    rows=[
                        {k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description']}
                        for c in fresh
                    ]
                    if rows:
                        save_raw_json(rows); st.session_state.report=process_playlists(rows,do_web_enrichment=do_web,do_spotify_api=False,queue_email_approval=queue_email)
                        st.success(f"Analyzed and saved {len(rows)} Spotify playlist candidate(s).")
                    else:
                        st.info('No new candidates to save.')
        st.markdown('#### Next steps')
        for step in fit.get('next_steps',[]): st.write(f"- {step}")
    targets=get_song_fit_targets()
    if targets:
        st.markdown('#### Saved song outreach targets')
        st.dataframe(pd.DataFrame(targets),use_container_width=True,hide_index=True)
with tab_results:
    st.subheader('Playlist results')
    rep=st.session_state.report; rows=get_all_playlists()
    if rep:
        a,b,c=st.columns(3); a.metric('Processed',rep['total_playlists_processed']); b.metric('Contactable',rep['contactable_curators_count']); c.metric('% contactable',f"{rep['contactable_curators_percent']}%")
    if rows:
        df=pd.DataFrame(rows); st.dataframe(df,use_container_width=True,hide_index=True)
        st.download_button('Download CRM Playlists CSV',df.to_csv(index=False).encode('utf-8'),'streambase_playlists.csv','text/csv')
    else: st.info('No playlists saved yet.')
    if rep:
        st.subheader('Outreach drafts from latest run')
        for item in sorted(rep['processed_playlists'],key=lambda x:x.get('final_score',0),reverse=True)[:10]:
            with st.expander(f"{item.get('playlist_name') or 'Unnamed'} — {item.get('final_score')}"):
                st.write(f"Curator: {item.get('curator_name') or 'Unknown'}")
                st.write(f"Similarity: {item.get('similarity_score')} | Intersection: {item.get('intersection_score')} | Contact confidence: {item.get('contact_confidence')}")
                st.write(f"Email: {item.get('email') or 'Not found'} | Instagram: {item.get('instagram') or 'Not found'} | Submission: {item.get('submission_page') or 'Not found'}")
                ix=item.get('intersection_breakdown') or {}
                if ix: st.json(ix,expanded=False)
                st.text_area('Email',item.get('email_message',''),height=160,key=f"e_{item.get('playlist_url')}")
                st.text_area('Instagram DM',item.get('instagram_dm',''),height=90,key=f"d_{item.get('playlist_url')}")
                st.text_area('Submission note',item.get('submission_note',''),height=90,key=f"s_{item.get('playlist_url')}")
with tab_curators:
    st.subheader('Curator CRM')
    curators=get_curator_profiles()
    if not curators: st.info('No curators saved yet.')
    for cur in curators:
        playlists=cur.get('playlists',[]); methods=cur.get('contact_methods',[]); events=cur.get('outreach_events',[]); best=max([p.get('final_score') or 0 for p in playlists],default=0)
        with st.expander(f"{cur['display_name']} · {len(playlists)} playlist(s) · best score {best}"):
            l,r=st.columns([1,1])
            with l:
                st.markdown('#### Playlists'); st.dataframe(pd.DataFrame(playlists),use_container_width=True,hide_index=True) if playlists else st.caption('No playlists.')
                st.markdown('#### Contact methods'); st.dataframe(pd.DataFrame(methods),use_container_width=True,hide_index=True) if methods else st.caption('No contact methods found.')
            with r:
                top=playlists[0] if playlists else {}; pid=int(top.get('id') or 0); cid=int(cur['id'])
                st.markdown('#### Outreach actions')
                em=next((m for m in methods if m['type']=='email'),None); ig=next((m for m in methods if m['type']=='instagram'),None); sub=next((m for m in methods if m['type']=='submission_page'),None)
                if em: st.link_button('Open Email',f"mailto:{em['value']}",use_container_width=True)
                if ig: st.link_button('Open Instagram',ig['value'],use_container_width=True)
                if sub: st.link_button('Open Submission Page',sub['value'],use_container_width=True)
                ch=st.selectbox('Log outreach channel',['email','instagram','submission_page','website'],key=f'ch_{cid}')
                ev=st.selectbox('Log event',['drafted','sent','replied','submitted','added_song','ignored'],key=f'ev_{cid}')
                msg=st.text_area('Notes/message',key=f'msg_{cid}',height=100)
                if st.button('Log Outreach Event',key=f'log_{cid}',use_container_width=True):
                    add_outreach_event(cid,pid,ch,ev,msg)
                    if pid and ev in {'sent','submitted','ignored'}: update_playlist_status(pid,ev)
                    st.success('Outreach event logged.'); st.rerun()
                st.markdown('#### History'); st.dataframe(pd.DataFrame(events),use_container_width=True,hide_index=True) if events else st.caption('No outreach history yet.')
with tab_email:
    st.subheader('Email approval queue')
    q=get_email_queue()
    if not q: st.info('No queued email drafts yet.')
    for item in q:
        label=f"{item.get('status')} · {item.get('curator_name') or 'Unknown'} · {item.get('playlist_name') or 'playlist'}"
        with st.expander(label):
            st.write(f"To: {item.get('to_email')}")
            st.write(f"Subject: {item.get('subject')}")
            st.text_area('Draft body',item.get('body',''),height=180,key=f"qbody_{item['id']}")
            c1,c2,c3=st.columns(3)
            with c1:
                if st.button('Approve',key=f"approve_{item['id']}",use_container_width=True):
                    update_email_queue_status(item['id'],'approved'); st.rerun()
            with c2:
                if st.button('Mark Sent',key=f"sent_{item['id']}",use_container_width=True):
                    update_email_queue_status(item['id'],'sent'); add_outreach_event(item['curator_id'],item['playlist_id'],'email','sent',item.get('body','')); update_playlist_status(item['playlist_id'],'sent'); st.rerun()
            with c3:
                if st.button('Reject',key=f"reject_{item['id']}",use_container_width=True):
                    update_email_queue_status(item['id'],'rejected'); st.rerun()
