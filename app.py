import json, time, pandas as pd, streamlit as st
import re
from src.audio_analysis import cyanite_ready_note,save_uploaded_song_file
from src.chartmetric import chartmetric_status
from src.chartmetric_mining import run_chartmetric_mining
from src.cyanite import cyanite_status,fetch_cyanite_analysis,normalize_cyanite_tags,upload_song_audio_to_cyanite
from src.database import init_db,get_curator_profiles,get_all_playlists,add_outreach_event,update_playlist_status,get_email_queue,update_email_queue_status,save_song_fit_targets,get_song_fit_targets,bulk_upsert_artist_songs,get_artist_songs,save_artist_sound_profile,get_artist_sound_profile,bulk_upsert_release_songs,get_release_songs,save_release_campaign_brief,get_release_campaigns,backup_song_profiles_json,bulk_upsert_artist_references,get_artist_references,get_mining_jobs,get_mined_playlists
from src.ingest_playlists import load_playlists_from_text,playlists_from_links,save_raw_json
from src.pipeline import process_playlists
from src.release_prep import CAMPAIGN_STATUSES,RELEASE_STATUSES,build_campaign_brief,campaign_readiness,infer_playlist_categories,save_release_prep_upload
from src.settings import DB_PATH,LOCAL_DATA_DIR
from src.sound_profile import build_artist_sound_profile
from src.song_analyzer import analyze_song_fit,score_spotify_playlist_candidates,suggest_reference_song_searches
from src.spotify_api import ENGLISH_SPOTIFY_MARKETS,SpotifyAPI,fetch_spotify_track,fetch_spotify_tracks_result,search_spotify_playlists,search_spotify_playlists_multi_market,search_spotify_tracks
from src.web_enricher import enrich_playlist_from_url,enrich_track_from_url
st.set_page_config(page_title='Streambase',page_icon='🎛️',layout='wide')
st.title('🎛️ Streambase')
st.caption('Playlist intelligence, curator contact stack, and outreach CRM for independent music growth.')
st.markdown(
    """
    <style>
    :root {
        --streambase-bg: #050506;
        --streambase-panel: #111113;
        --streambase-panel-soft: #18181b;
        --streambase-red: #f04444;
        --streambase-red-dark: #8f171f;
        --streambase-gold: #d8b45f;
        --streambase-text: #f6f3ec;
        --streambase-muted: #a6a09a;
        --streambase-border: rgba(216, 180, 95, 0.22);
    }
    .stApp {
        background: var(--streambase-bg);
        color: var(--streambase-text);
    }
    [data-testid="stSidebar"] {
        background: #17171d;
        border-right: 1px solid rgba(216, 180, 95, 0.14);
    }
    [data-testid="stHeader"] {
        background: rgba(5, 5, 6, 0.86);
        backdrop-filter: blur(18px);
    }
    h1, h2, h3 {
        letter-spacing: 0;
        color: var(--streambase-text);
    }
    h1 {
        font-weight: 760;
    }
    p, label, span {
        letter-spacing: 0;
    }
    [data-testid="stVerticalBlockBorderWrapper"] {
        border-color: var(--streambase-border);
        background: linear-gradient(180deg, rgba(24, 24, 27, 0.92), rgba(12, 12, 14, 0.96));
        border-radius: 8px;
    }
    [data-testid="stMetric"] {
        background: #111113;
        border: 1px solid var(--streambase-border);
        border-radius: 8px;
        padding: 14px 16px;
    }
    [data-testid="stMetricLabel"] {
        color: var(--streambase-muted);
    }
    [data-testid="stMetricValue"] {
        color: var(--streambase-gold);
    }
    .stButton > button,
    [data-testid="stBaseButton-secondary"],
    [data-testid="stBaseButton-primary"] {
        border-radius: 8px;
        border: 1px solid rgba(216, 180, 95, 0.34);
        background: #151519;
        color: var(--streambase-text);
        box-shadow: none;
    }
    [data-testid="stBaseButton-primary"] {
        background: linear-gradient(180deg, #ff4d4d, #b51f2b);
        border-color: rgba(216, 180, 95, 0.46);
    }
    .stButton > button:hover,
    [data-testid="stBaseButton-secondary"]:hover,
    [data-testid="stBaseButton-primary"]:hover {
        border-color: var(--streambase-gold);
        color: #fff7df;
    }
    [data-testid="stTabs"] button[aria-selected="true"] {
        color: var(--streambase-gold);
        border-bottom-color: var(--streambase-red);
    }
    [data-testid="stDataFrame"] {
        border: 1px solid var(--streambase-border);
        border-radius: 8px;
        overflow: hidden;
    }
    input, textarea {
        border-radius: 8px !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)
init_db()
with st.sidebar:
    spotify=SpotifyAPI(); cm=chartmetric_status(); cy=cyanite_status()
    st.header('Settings'); do_web=st.toggle('Fetch public contact info',value=True); do_spotify=st.toggle('Use Spotify API connector',value=spotify.configured,disabled=not spotify.configured); queue_email=st.toggle('Queue emails for approval',value=True)
    playlist_cooldown_days=st.number_input('Playlist pitch cooldown days',min_value=0,max_value=180,value=30,step=1,help='Prevents Streambase from queueing another song to the same playlist too soon.')
    minimum_queue_score=st.number_input('Minimum score to queue email',min_value=0,max_value=100,value=50,step=1,help='Lower-scoring playlists can still be saved, but they will not enter email approval automatically.')
    st.markdown('#### Connector status')
    st.write(f"Spotify API: {'connected' if spotify.configured else 'not connected'}")
    st.write(f"Chartmetric: {'connected' if cm['configured']=='yes' else 'not connected'}")
    st.write(f"Cyanite: {'connected' if cy['configured']=='yes' else 'not connected'}")
    st.markdown('#### Local data')
    st.caption(f"Private data dir: {LOCAL_DATA_DIR}")
    st.caption(f"SQLite: {DB_PATH}")
    st.caption('Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET to enable full playlist metadata, genres, and track matching.')
    st.divider(); st.write('Outreach stack: Email -> Instagram DM -> Submission page')
if 'playlists' not in st.session_state: st.session_state.playlists=[]
if 'report' not in st.session_state: st.session_state.report=None
if 'artist_sound_profile' not in st.session_state: st.session_state.artist_sound_profile={}
if 'catalog_campaign_brief' not in st.session_state: st.session_state.catalog_campaign_brief={}
if 'release_campaign_brief' not in st.session_state: st.session_state.release_campaign_brief={}
if 'song_fit' not in st.session_state: st.session_state.song_fit=None
if 'song_spotify' not in st.session_state: st.session_state.song_spotify={}
if 'reference_spotify_tracks' not in st.session_state: st.session_state.reference_spotify_tracks=[]
if 'generated_reference_tracks' not in st.session_state: st.session_state.generated_reference_tracks=[]
if 'cyanite_upload_result' not in st.session_state: st.session_state.cyanite_upload_result={}
if 'cyanite_analysis_result' not in st.session_state: st.session_state.cyanite_analysis_result={}
if 'spotify_playlist_candidates' not in st.session_state: st.session_state.spotify_playlist_candidates=[]
if 'chartmetric_mining_result' not in st.session_state: st.session_state.chartmetric_mining_result={}
if 'home_cyanite_upload_result' not in st.session_state: st.session_state.home_cyanite_upload_result={}
if 'home_cyanite_analysis_result' not in st.session_state: st.session_state.home_cyanite_analysis_result={}
if 'home_saved_song_path' not in st.session_state: st.session_state.home_saved_song_path=''
if 'home_song_fit' not in st.session_state: st.session_state.home_song_fit=None
if 'home_spotify_playlist_candidates' not in st.session_state: st.session_state.home_spotify_playlist_candidates=[]
if 'pitch_release_type' not in st.session_state: st.session_state.pitch_release_type='new_release'
if 'pitch_spotify_url' not in st.session_state: st.session_state.pitch_spotify_url=''
if 'pitch_spotify_meta' not in st.session_state: st.session_state.pitch_spotify_meta={}
def df_session():
    df=pd.DataFrame(st.session_state.playlists) if st.session_state.playlists else pd.DataFrame(columns=['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description'])
    for col in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description']:
        if col not in df.columns: df[col]=0 if col=='follower_count' else ''
    return df
def catalog_playlist_summary(catalog_rows, targets):
    def clean(value):
        return str(value or '').strip().lower()
    targets_by_song={}
    for target in targets:
        title_key=clean(target.get('song_title'))
        if not title_key:
            continue
        targets_by_song.setdefault(title_key,[]).append(target)
    rows=[]
    detail={}
    for song in catalog_rows:
        title=song.get('title') or song.get('file_name') or 'Untitled'
        song_targets=targets_by_song.get(clean(title),[])
        unique={}
        for target in song_targets:
            key=target.get('playlist_url') or target.get('playlist_name') or str(target.get('id',''))
            if key and key not in unique:
                unique[key]=target
        playlist_rows=list(unique.values())
        detail[int(song.get('id') or 0)]=playlist_rows
        rows.append({
            'id':int(song.get('id') or 0),
            'title':title,
            'file_name':song.get('file_name') or '',
            'release_status':song.get('release_status') or '',
            'playlists_added':len(playlist_rows),
            'last_updated':song.get('updated_at') or song.get('created_at') or '',
        })
    return rows,detail
def catalog_tag_summary(catalog_rows):
    def split_tags(value):
        return [tag.strip() for tag in str(value or '').split(';') if tag.strip()]
    counts={}
    for song in catalog_rows:
        for tag in split_tags(song.get('genre_tags')):
            key=tag.lower()
            if key not in counts:
                counts[key]={'tag':tag,'song_count':0}
            counts[key]['song_count']+=1
    return sorted(counts.values(),key=lambda row:(-row['song_count'],row['tag'].lower()))

tab_scan,tab_catalog,tab_release,tab_import,tab_song,tab_results,tab_curators,tab_email=st.tabs(['Scan A Song','Catalog','Release Prep Library','Import & Analyze','Song Fit','Playlist Results','Curator CRM','Email Queue'])
with tab_scan:
    st.markdown('### Scan A Song')
    st.caption('Upload a WAV or MP3, scan it with Cyanite, and review the genre/mood board as soon as the analysis finishes.')
    home_scan=st.container(border=True)
    with home_scan:
        release_options=['New release','Already released']
        release_index=0 if st.session_state.pitch_release_type=='new_release' else 1
        home_release_choice=st.radio(
            'Release status',
            release_options,
            index=release_index,
            horizontal=True,
            label_visibility='collapsed',
            key='home_release_status_choice',
        )
        next_release_type='already_released' if home_release_choice=='Already released' else 'new_release'
        if next_release_type!=st.session_state.pitch_release_type:
            st.session_state.pitch_release_type=next_release_type
            st.session_state.home_song_fit=None
            st.session_state.home_spotify_playlist_candidates=[]
            if next_release_type=='new_release':
                st.session_state.pitch_spotify_url=''
                st.session_state.pitch_spotify_meta={}
                st.session_state.home_spotify_track_url=''
        pitch_is_released=st.session_state.pitch_release_type=='already_released'
        pitch_meta=st.session_state.pitch_spotify_meta or {}
        pitch_track_url=pitch_meta.get('spotify_url') or st.session_state.pitch_spotify_url.strip()
        if pitch_is_released:
            url_col,fetch_col=st.columns([3,1])
            with url_col:
                home_spotify_url=st.text_input(
                    'Spotify track URL',
                    value=st.session_state.pitch_spotify_url,
                    placeholder='https://open.spotify.com/track/...',
                    key='home_spotify_track_url',
                )
                st.session_state.pitch_spotify_url=home_spotify_url
            with fetch_col:
                st.write('')
                st.write('')
                if st.button('Fetch Metadata',use_container_width=True,key='home_fetch_spotify_meta'):
                    if not st.session_state.pitch_spotify_url.strip():
                        st.error('Paste the Spotify track URL first.')
                    else:
                        meta=fetch_spotify_track(st.session_state.pitch_spotify_url.strip()) if spotify.configured else {}
                        if not meta: meta=enrich_track_from_url(st.session_state.pitch_spotify_url.strip())
                        if meta:
                            meta['release_context']='already_released'
                            st.session_state.pitch_spotify_meta=meta
                            st.session_state.home_song_fit=None
                            st.session_state.home_spotify_playlist_candidates=[]
                            st.success(f"Loaded Spotify metadata for {meta.get('title') or 'track'}.")
                        else:
                            st.error('Could not load Spotify metadata for that link.')
            pitch_meta=st.session_state.pitch_spotify_meta or {}
            pitch_track_url=pitch_meta.get('spotify_url') or st.session_state.pitch_spotify_url.strip()
            if pitch_meta:
                st.caption(f"Loaded: {pitch_meta.get('title','track')} · {pitch_meta.get('artist','artist')}")
            allowed_audio_types=['wav','mp3']
        else:
            allowed_audio_types=['wav']
        home_audio=st.file_uploader('Upload WAV' if not pitch_is_released else 'Upload WAV/MP3',type=allowed_audio_types,key='home_cyanite_audio')
        home_title=''
        if home_audio:
            home_title=home_audio.name.rsplit('.',1)[0].replace('_',' ').replace('-',' ').title()
            st.write(f"Selected song: {home_audio.name}")
        scan_disabled=not bool(home_audio) or cy.get('configured')!='yes'
        if cy.get('configured')!='yes':
            st.warning('Cyanite is not connected. Add CYANITE_API_KEY to scan audio.')
        if st.button('Scan for Genre with Cyanite',type='primary',use_container_width=True,disabled=scan_disabled):
            st.session_state.home_cyanite_upload_result={}
            st.session_state.home_cyanite_analysis_result={}
            st.session_state.home_song_fit=None
            st.session_state.home_spotify_playlist_candidates=[]
            with st.status('Uploading audio to Cyanite...',expanded=True) as status:
                upload_result=upload_song_audio_to_cyanite(home_audio,home_title,'')
                st.session_state.home_cyanite_upload_result=upload_result
                if not upload_result.get('ok'):
                    status.update(label='Cyanite upload failed.',state='error')
                    st.error(upload_result.get('error') or 'Cyanite upload failed.')
                else:
                    library_track_id=upload_result.get('library_track_id','')
                    status.update(label='Cyanite is analyzing the song...',state='running')
                    analysis={}
                    for attempt in range(36):
                        analysis=fetch_cyanite_analysis(library_track_id)
                        st.write(f"Check {attempt+1}/36: {analysis.get('status','unknown')}")
                        if analysis.get('ok'):
                            break
                        if analysis.get('status') not in {'processing','finished',''} and analysis.get('status') not in {'not_found'}:
                            break
                        time.sleep(5)
                    st.session_state.home_cyanite_analysis_result=analysis
                    if analysis.get('ok'):
                        status.update(label='Cyanite scan complete.',state='complete')
                        saved=save_uploaded_song_file(home_audio)
                        if saved.get('ok'):
                            row={
                                'title':analysis.get('title') or saved.get('title',''),
                                'file_name':saved.get('file_name',''),
                                'file_path':saved.get('file_path',''),
                                'release_status':'released' if pitch_is_released else 'unreleased',
                                'planned_release_date':'',
                                'campaign_status':'profile_ready',
                                'bpm':analysis.get('bpm',''),
                                'genre_tags':'; '.join(analysis.get('genres',[])),
                                'mood_tags':'; '.join(analysis.get('moods',[])),
                                'energy':analysis.get('energy',''),
                                'danceability':'',
                                'instrumentation':'; '.join(analysis.get('instruments',[])),
                                'vocal_style':analysis.get('voice',''),
                                'source':'cyanite',
                                'analysis_source':'cyanite',
                                'notes':analysis.get('caption',''),
                                'raw_analysis_json':json.dumps(analysis.get('raw') or analysis,ensure_ascii=True),
                            }
                            bulk_upsert_release_songs([row])
                            st.session_state.home_saved_song_path=saved.get('file_path','')
                            backup_song_profiles_json()
                        st.session_state.home_song_fit=analyze_song_fit(
                            None,
                            title=analysis.get('title') or pitch_meta.get('title') or home_title,
                            artist=pitch_meta.get('artist',''),
                            reference_artists='',
                            descriptors=analysis.get('descriptors',''),
                            saved_playlists=get_all_playlists(),
                            spotify_track=(pitch_meta or {'release_context':'already_released','spotify_url':pitch_track_url}) if pitch_is_released else {'release_context':'new_release'},
                            reference_tracks=[],
                            cyanite_profile=analysis,
                        )
                    else:
                        status.update(label='Cyanite analysis is not complete yet.',state='error')
                        st.info(analysis.get('error') or 'Cyanite is still processing. Try scanning again or fetch later from Song Fit.')
        home_analysis=st.session_state.home_cyanite_analysis_result
        if home_analysis:
            st.markdown('#### Cyanite Mood Board')
            if home_analysis.get('ok'):
                st.success('Analysis complete.')
                if st.session_state.home_saved_song_path:
                    st.caption(f"Saved locally: {st.session_state.home_saved_song_path}")
                board=st.container(border=True)
                with board:
                    g1,g2,g3=st.columns(3)
                    g1.metric('Energy',home_analysis.get('energy') or '—')
                    g2.metric('BPM',home_analysis.get('bpm') or '—')
                    g3.metric('Status',home_analysis.get('status','finished'))
                    tag_rows=[
                        {'category':'Genres','tags':'; '.join(home_analysis.get('genres',[]))},
                        {'category':'Moods','tags':'; '.join(home_analysis.get('moods',[]))},
                        {'category':'Instruments','tags':'; '.join(home_analysis.get('instruments',[]))},
                        {'category':'Voice','tags':home_analysis.get('voice','')},
                        {'category':'Movement','tags':home_analysis.get('movement','')},
                        {'category':'Descriptors','tags':home_analysis.get('descriptors','')},
                    ]
                    st.dataframe(pd.DataFrame(tag_rows),use_container_width=True,hide_index=True)
                    if home_analysis.get('caption'):
                        st.write(home_analysis.get('caption'))
                if st.session_state.home_song_fit is None:
                    st.session_state.home_song_fit=analyze_song_fit(
                        None,
                        title=home_analysis.get('title','') or pitch_meta.get('title',''),
                        artist=pitch_meta.get('artist',''),
                        reference_artists='',
                        descriptors=home_analysis.get('descriptors',''),
                        saved_playlists=get_all_playlists(),
                        spotify_track=(pitch_meta or {'release_context':'already_released','spotify_url':pitch_track_url}) if pitch_is_released else {'release_context':'new_release'},
                        reference_tracks=[],
                        cyanite_profile=home_analysis,
                    )
                home_fit=st.session_state.home_song_fit or {}
                searches=home_fit.get('discovery_searches') or []
                if searches:
                    st.markdown('#### Spotify Playlist Search')
                    st.caption('Search breadth is controlled here. Streambase runs a limited number of Song DNA keyword searches, asks Spotify for a limited number of results per search, removes duplicates, then scores candidates.')
                    search_df=pd.DataFrame(searches)
                    st.dataframe(search_df,use_container_width=True,hide_index=True)
                    hs1,hs2,hs3=st.columns(3)
                    with hs1:
                        home_query_limit=st.number_input('Spotify searches to run',min_value=1,max_value=len(searches),value=min(3,len(searches)),step=1,key='home_query_limit')
                    with hs2:
                        home_per_query=st.number_input('Spotify results per search',min_value=1,max_value=10,value=5,step=1,key='home_per_query')
                    with hs3:
                        home_markets=st.multiselect('Spotify markets',options=ENGLISH_SPOTIFY_MARKETS+['ZA','SG','PH'],default=ENGLISH_SPOTIFY_MARKETS,key='home_markets')
                    estimated_max=int(home_query_limit)*int(home_per_query)*max(1,len(home_markets))
                    st.caption(f"Maximum raw Spotify results this run: {estimated_max}. Streambase dedupes across markets, so final candidates may be lower.")
                    if st.button('Find Spotify Playlists From This Song DNA',use_container_width=True,disabled=not spotify.configured):
                        selected_queries=[s.get('search_query','') for s in searches[:int(home_query_limit)] if s.get('search_query')]
                        result=search_spotify_playlists_multi_market(selected_queries,int(home_per_query),home_markets or ENGLISH_SPOTIFY_MARKETS)
                        if not result.get('ok'):
                            st.error(result.get('error') or 'Spotify playlist search failed.')
                        candidates=score_spotify_playlist_candidates(home_fit,result.get('playlists',[]),get_all_playlists())
                        st.session_state.home_spotify_playlist_candidates=candidates
                        st.success(f"Found {len(candidates)} scored playlist candidate(s).")
                    if not spotify.configured:
                        st.info('Connect Spotify API credentials to search Spotify playlists.')
                home_candidates=st.session_state.home_spotify_playlist_candidates or []
                if home_candidates:
                    st.markdown('#### Playlist Candidates')
                    cand_df=pd.DataFrame(home_candidates)
                    cols=[c for c in ['candidate_fit_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','matched_lanes','matched_descriptors','related_artists','playlist_url'] if c in cand_df.columns]
                    st.dataframe(cand_df[cols],use_container_width=True,hide_index=True)
                    fresh=[c for c in home_candidates if not c.get('already_in_crm')]
                    sc1,sc2=st.columns(2)
                    with sc1:
                        if st.button('Stage Candidates in Import Queue',use_container_width=True,key='home_stage_candidates'):
                            st.session_state.playlists=[
                                {k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id']}
                                for c in fresh
                            ]
                            st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Import & Analyze.")
                    with sc2:
                        if st.button('Analyze & Save Candidates to CRM',use_container_width=True,key='home_save_candidates'):
                            song_context={
                                'title':(st.session_state.home_song_fit or {}).get('song',{}).get('title') or pitch_meta.get('title',''),
                                'artist':(st.session_state.home_song_fit or {}).get('song',{}).get('artist') or pitch_meta.get('artist',''),
                                'spotify_url':pitch_track_url if pitch_is_released else '',
                                'release_status':'released' if pitch_is_released else 'unreleased',
                                'release_age_label':((st.session_state.home_song_fit or {}).get('release_guidance') or {}).get('release_age_label',''),
                            }
                            rows=[
                                {**{k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id']},'song_context':song_context}
                                for c in fresh
                            ]
                            if rows:
                                save_raw_json(rows)
                                st.session_state.report=process_playlists(rows,do_web_enrichment=do_web,do_spotify_api=False,queue_email_approval=queue_email,song_context=song_context,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
                                st.success(f"Analyzed and saved {len(rows)} playlist candidate(s).")
                            else:
                                st.info('No new candidates to save.')
            else:
                st.warning(home_analysis.get('error') or f"Cyanite status: {home_analysis.get('status','unknown')}")
                st.json({k:v for k,v in home_analysis.items() if k!='raw'},expanded=False)
with tab_catalog:
    st.subheader('Catalog')
    st.caption('Uploaded songs, playlist placements, and Cyanite genre tags.')
    catalog_rows=get_release_songs()
    if catalog_rows:
        catalog_by_id={int(row.get('id') or 0):row for row in catalog_rows}
        catalog_display_rows,catalog_playlist_details=catalog_playlist_summary(catalog_rows,get_song_fit_targets())
        total_playlist_adds=sum(row.get('playlists_added',0) for row in catalog_display_rows)
        cm1,cm2=st.columns(2)
        cm1.metric('Uploaded Songs',len(catalog_display_rows))
        cm2.metric('Playlist Adds',total_playlist_adds)
        all_genres=catalog_tag_summary(catalog_rows)
        st.markdown('#### All Catalog Genres')
        if all_genres:
            st.dataframe(
                pd.DataFrame(all_genres),
                use_container_width=True,
                hide_index=True,
                column_config={
                    'tag':st.column_config.TextColumn('Genre'),
                    'song_count':st.column_config.NumberColumn('Songs',format='%d'),
                },
            )
        else:
            st.info('No Cyanite genre tags are saved across the catalog yet.')
        st.markdown('#### Uploaded Catalog')
        st.caption('Click a song row to see every playlist saved for it.')
        catalog_df=pd.DataFrame(catalog_display_rows)
        catalog_view=catalog_df[['title','file_name','release_status','playlists_added','last_updated']]
        selected_catalog=st.dataframe(
            catalog_view,
            use_container_width=True,
            hide_index=True,
            on_select='rerun',
            selection_mode='single-row',
            column_config={
                'title':st.column_config.TextColumn('Song'),
                'file_name':st.column_config.TextColumn('File'),
                'release_status':st.column_config.TextColumn('Release'),
                'playlists_added':st.column_config.NumberColumn('Playlists',format='%d'),
                'last_updated':st.column_config.TextColumn('Last Updated'),
            },
        )
        selected_rows=(selected_catalog.selection.rows if selected_catalog and selected_catalog.selection else [])
        if selected_rows:
            selected_row=catalog_df.iloc[selected_rows[0]].to_dict()
            selected_song=catalog_by_id.get(int(selected_row.get('id') or 0),{})
            playlists=catalog_playlist_details.get(int(selected_row.get('id') or 0),[])
            st.markdown(f"#### Playlists for {selected_row.get('title','Selected Song')}")
            if playlists:
                playlist_df=pd.DataFrame(playlists)
                for col in ['playlist_name','curator_name','fit_score','status','playlist_url','created_at']:
                    if col not in playlist_df.columns:
                        playlist_df[col]=''
                st.dataframe(
                    playlist_df[['playlist_name','curator_name','fit_score','status','playlist_url','created_at']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'curator_name':st.column_config.TextColumn('Curator'),
                        'fit_score':st.column_config.NumberColumn('Fit',format='%.0f'),
                        'status':st.column_config.TextColumn('Status'),
                        'playlist_url':st.column_config.LinkColumn('Spotify URL'),
                        'created_at':st.column_config.TextColumn('Added'),
                    },
                )
            else:
                st.info('No playlists have been saved for this song yet.')
            st.markdown('#### Cyanite Genres')
            genre_tags=[tag.strip() for tag in str(selected_song.get('genre_tags') or '').split(';') if tag.strip()]
            mood_tags=[tag.strip() for tag in str(selected_song.get('mood_tags') or '').split(';') if tag.strip()]
            instrument_tags=[tag.strip() for tag in str(selected_song.get('instrumentation') or '').split(';') if tag.strip()]
            tag_rows=[]
            tag_rows.extend({'category':'Genre','tag':tag} for tag in genre_tags)
            tag_rows.extend({'category':'Mood','tag':tag} for tag in mood_tags)
            tag_rows.extend({'category':'Instrument','tag':tag} for tag in instrument_tags)
            if tag_rows:
                st.dataframe(pd.DataFrame(tag_rows),use_container_width=True,hide_index=True)
            else:
                st.info('No Cyanite tags are saved for this song yet.')
        else:
            st.info('Select a song above to view its playlists.')
    else:
        st.info('No uploaded songs yet. Songs appear here after they are uploaded from Scan A Song or Release Prep.')
    st.caption(f"Audio folder: data/audio_uploads · Song profile backup: data/song_profiles.json")
with tab_release:
    st.subheader('Release Prep Library')
    st.caption('Prepare unreleased songs before scheduling: profile the audio, plan Chartmetric mining, and draft campaign briefs.')
    release_uploads=st.file_uploader('Upload unreleased songs',type=['wav','mp3'],accept_multiple_files=True,key='release_prep_uploads')
    if release_uploads and st.button('Add to Release Prep Library',use_container_width=True):
        rows=[]; errors=[]
        for up in release_uploads:
            result=save_release_prep_upload(up)
            if result.get('ok'): rows.append(result)
            else: errors.append(result.get('error','Upload failed.'))
        if rows:
            bulk_upsert_release_songs(rows); st.success(f"Added {len(rows)} unreleased song(s).")
        for err in errors: st.error(err)
    release_rows=get_release_songs()
    if release_rows:
        st.markdown('#### Filters')
        f1,f2,f3,f4=st.columns(4)
        with f1:
            status_filter=st.selectbox('Release status',['all']+RELEASE_STATUSES)
        with f2:
            campaign_filter=st.selectbox('Campaign readiness',['all']+CAMPAIGN_STATUSES)
        with f3:
            genre_filter=st.text_input('Genre contains')
        with f4:
            ref_filter=st.text_input('Reference artist contains')
        filtered=[]
        for row in release_rows:
            if status_filter!='all' and row.get('release_status')!=status_filter: continue
            if campaign_filter!='all' and row.get('campaign_status')!=campaign_filter: continue
            if genre_filter and genre_filter.lower() not in str(row.get('genre_tags','')).lower(): continue
            if ref_filter and ref_filter.lower() not in str(row.get('reference_artists','')).lower(): continue
            filtered.append(row)
        if not filtered:
            st.info('No release prep songs match those filters.')
        columns=['id','title','file_path','release_status','planned_release_date','campaign_status','bpm','key','genre_tags','mood_tags','energy','danceability','instrumentation','vocal_style','lyrical_theme_notes','reference_artists','recommended_playlist_categories','recommended_chartmetric_targets','analysis_source','notes']
        df=pd.DataFrame(filtered)
        for col in columns:
            if col not in df.columns: df[col]=''
        st.markdown('#### Unreleased song records')
        st.caption('Manual override is expected for now. Use semicolons for multi-value fields.')
        edited=st.data_editor(
            df[columns],
            use_container_width=True,
            hide_index=True,
            column_config={
                'release_status':st.column_config.SelectboxColumn('release_status',options=RELEASE_STATUSES),
                'campaign_status':st.column_config.SelectboxColumn('campaign_status',options=CAMPAIGN_STATUSES),
                'planned_release_date':st.column_config.TextColumn('planned_release_date',help='YYYY-MM-DD when known'),
            },
        )
        cprep1,cprep2,cprep3=st.columns(3)
        with cprep1:
            if st.button('Save Release Prep Edits',use_container_width=True):
                rows=edited.fillna('').to_dict(orient='records')
                for row in rows:
                    if not row.get('recommended_playlist_categories'):
                        row['recommended_playlist_categories']='; '.join(infer_playlist_categories(row))
                    row['campaign_status']=campaign_readiness(row)
                bulk_upsert_release_songs(rows); st.success('Release prep records saved.')
        with cprep2:
            if st.button('Generate Mining Targets Per Song',use_container_width=True):
                rows=edited.fillna('').to_dict(orient='records')
                for row in rows:
                    brief=build_campaign_brief(row)
                    row['recommended_playlist_categories']='; '.join(brief.get('best_playlist_keywords',[]))
                    row['recommended_chartmetric_targets']='; '.join(brief.get('best_chartmetric_mining_queries',[])[:12])
                    row['campaign_status']='mining_ready'
                bulk_upsert_release_songs(rows); st.success('Per-song mining targets generated.')
        with cprep3:
            selected_title=st.selectbox('Campaign brief song',[r.get('title','Untitled') for r in filtered] or [''])
            if st.button('Generate Campaign Brief',type='primary',use_container_width=True,disabled=not filtered):
                row=next((r for r in edited.fillna('').to_dict(orient='records') if r.get('title')==selected_title),{})
                if row:
                    brief=build_campaign_brief(row)
                    save_release_campaign_brief(row.get('id'),brief,'campaign_draft')
                    st.session_state.release_campaign_brief=brief
                    st.success('Campaign brief saved.')
        brief=st.session_state.release_campaign_brief
        campaigns=get_release_campaigns()
        if not brief and campaigns:
            brief=campaigns[0].get('campaign_brief',{})
        if brief:
            st.markdown('#### Campaign brief')
            st.json(brief,expanded=False)
        if campaigns:
            st.markdown('#### Saved release campaign briefs')
            st.dataframe(pd.DataFrame([{'song_title':c.get('song_title',''),'status':c.get('status',''),'updated_at':c.get('updated_at','')} for c in campaigns]),use_container_width=True,hide_index=True)
    else:
        st.info('Upload unreleased WAV/MP3 files to start preparing release campaigns.')
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
                    save_raw_json(st.session_state.playlists); st.session_state.report=process_playlists(st.session_state.playlists,do_web_enrichment=do_web,do_spotify_api=do_spotify,queue_email_approval=queue_email,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
                st.success('Analysis complete. Curator CRM updated.')
        with c2:
            if st.button('Clear Import',use_container_width=True): st.session_state.playlists=[]; st.session_state.report=None; st.rerun()
with tab_song:
    st.subheader('Song playlist fit')
    st.caption('Use audio for sound analysis and a Spotify link for release age, title/artist metadata, and the curator-facing pitch URL.')
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
            st.session_state.song_spotify={}; st.session_state.reference_spotify_tracks=[]; st.session_state.generated_reference_tracks=[]; st.session_state.cyanite_upload_result={}; st.session_state.song_fit=None; st.rerun()
    reference_links=st.text_area('Reference song links',height=110,placeholder='Optional: paste 3-5 Spotify track links, one per line, that sound like your song.')
    if st.button('Fetch Reference Song Metadata',use_container_width=True):
        refs=[part.strip() for part in re.split(r'[\s,]+',reference_links) if part.strip()]
        if not refs: st.error('Paste at least one Spotify reference track link first.')
        elif not spotify.configured: st.error('Spotify API credentials are required for reference song metadata.')
        else:
            result=fetch_spotify_tracks_result(refs)
            st.session_state.reference_spotify_tracks=result.get('tracks',[])
            if st.session_state.reference_spotify_tracks:
                st.success(f"Loaded {len(st.session_state.reference_spotify_tracks)} reference song(s).")
            else:
                st.error(result.get('error') or 'No reference song metadata loaded.')
            if result.get('failed'):
                st.caption('Some reference links could not be loaded.')
                st.json(result.get('failed'),expanded=False)
    st.markdown('#### Song audio')
    song_file=st.file_uploader('Upload WAV or MP3 for Cyanite analysis',type=['wav','mp3'])
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
    if song_file:
        ccy1,ccy2=st.columns([1,1])
        with ccy1:
            if st.button('Prepare/Send Audio to Cyanite',use_container_width=True):
                title_for_cyanite=(spotify_meta.get('title') or song_title if 'song_title' in locals() else spotify_meta.get('title',''))
                external_id=spotify_meta.get('spotify_track_id') or song_link.strip()
                result=upload_song_audio_to_cyanite(song_file,title_for_cyanite,external_id)
                st.session_state.cyanite_upload_result=result
        with ccy2:
            st.caption('WAV files are converted to MP3 before Cyanite upload. Spotify link stays attached for release age and outreach.')
    if st.session_state.cyanite_upload_result:
        result=st.session_state.cyanite_upload_result
        if result.get('ok'):
            st.success(f"Cyanite library track created: {result.get('library_track_id') or 'created'}")
            if st.button('Fetch Cyanite Analysis',use_container_width=True):
                st.session_state.cyanite_analysis_result=fetch_cyanite_analysis(result.get('library_track_id',''))
        elif result.get('prepared'):
            st.warning(result.get('error'))
        else:
            st.error(result.get('error') or 'Cyanite audio preparation failed.')
        st.json({k:v for k,v in result.items() if k not in {'raw'}},expanded=False)
    if st.session_state.cyanite_analysis_result:
        analysis=st.session_state.cyanite_analysis_result
        if analysis.get('ok'):
            st.success('Cyanite analysis loaded into Song Fit.')
        else:
            st.info(analysis.get('error') or f"Cyanite status: {analysis.get('status','unknown')}")
        st.json({k:v for k,v in analysis.items() if k not in {'raw'}},expanded=False)
    cyanite_raw=st.text_area('Cyanite tags JSON',height=100,placeholder='Optional: paste Cyanite genre/mood/tag JSON here when available.')
    cyanite_profile=st.session_state.cyanite_analysis_result if st.session_state.cyanite_analysis_result.get('ok') else {}
    if cyanite_raw.strip():
        try:
            cyanite_profile=normalize_cyanite_tags(json.loads(cyanite_raw))
            st.success('Cyanite tags parsed.')
        except json.JSONDecodeError:
            st.error('Cyanite tags must be valid JSON.')
    cauto1,cauto2=st.columns([1,1])
    with cauto1:
        auto_limit=st.number_input('Generated reference songs per search',min_value=1,max_value=5,value=2,step=1)
    with cauto2:
        auto_market=st.text_input('Reference song market',value='US',max_chars=2)
    if st.button('Generate Reference Songs',use_container_width=True,disabled=not spotify.configured):
        seed_song={'artist':song_artist,'reference_artists':song_refs}
        seed_queries=suggest_reference_song_searches(seed_song,song_desc,cyanite_profile)
        if not seed_queries: st.error('Add descriptors, reference artists, or Cyanite tags before generating reference songs.')
        else:
            result=search_spotify_tracks([q.get('search_query','') for q in seed_queries],int(auto_limit),auto_market.upper() or 'US')
            tracks=result.get('tracks',[])
            own_ids={spotify_meta.get('spotify_track_id',''),song_link.strip()}
            tracks=[t for t in tracks if t.get('spotify_track_id') not in own_ids and t.get('spotify_url') not in own_ids]
            st.session_state.generated_reference_tracks=tracks
            if result.get('ok') and tracks: st.success(f"Generated {len(tracks)} reference song candidate(s).")
            else: st.error(result.get('error') or 'No generated reference songs found.')
    generated_refs=st.session_state.generated_reference_tracks or []
    if generated_refs:
        st.markdown('#### Generated reference songs')
        gdf=pd.DataFrame(generated_refs)
        st.dataframe(gdf[[c for c in ['title','artist','search_query','popularity','release_date','spotify_url'] if c in gdf.columns]],use_container_width=True,hide_index=True)
    combined_reference_meta=[]
    seen_ref_urls=set()
    for item in (reference_meta or []) + (generated_refs or []):
        url=item.get('spotify_url') or item.get('spotify_track_id')
        if url and url in seen_ref_urls: continue
        if url: seen_ref_urls.add(url)
        combined_reference_meta.append(item)
    if st.button('Analyze Song Fit',type='primary',use_container_width=True):
        if not song_file and not spotify_meta and not (song_title or song_artist or song_refs or song_desc): st.error('Upload a song, paste a Spotify track link, or add song details first.')
        else:
            st.session_state.song_fit=analyze_song_fit(song_file,song_title,song_artist,song_refs,song_desc,get_all_playlists(),spotify_meta,combined_reference_meta,cyanite_profile)
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
        ref_searches=fit.get('reference_song_searches') or []
        if ref_searches:
            st.markdown('#### Reference song searches')
            st.dataframe(pd.DataFrame(ref_searches),use_container_width=True,hide_index=True)
        if searches:
            st.markdown('#### Discovery searches')
            st.caption('These searches are audio-first Spotify playlist queries built from the song mood board. Contact and submission-page discovery happens after candidates are analyzed.')
            st.dataframe(pd.DataFrame(searches),use_container_width=True,hide_index=True)
            cfind1,cfind2=st.columns([1,1])
            with cfind1:
                per_query=st.number_input('Spotify results per search',min_value=1,max_value=10,value=5,step=1)
            with cfind2:
                markets=st.multiselect('Spotify markets',options=ENGLISH_SPOTIFY_MARKETS+['ZA','SG','PH'],default=ENGLISH_SPOTIFY_MARKETS,key='song_fit_markets')
            if st.button('Find Spotify Playlists',use_container_width=True,disabled=not spotify.configured):
                queries=[s.get('search_query','') for s in searches if s.get('search_query')]
                result=search_spotify_playlists_multi_market(queries,int(per_query),markets or ENGLISH_SPOTIFY_MARKETS)
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
            visible_cols=[c for c in ['candidate_fit_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','matched_lanes','matched_descriptors','related_artists','playlist_url'] if c in cand_df.columns]
            st.dataframe(cand_df[visible_cols],use_container_width=True,hide_index=True)
            fresh=[c for c in candidates if not c.get('already_in_crm')]
            csave1,csave2=st.columns(2)
            with csave1:
                if st.button('Stage Candidates in Import Queue',use_container_width=True):
                    st.session_state.playlists=[
                        {k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id']}
                        for c in fresh
                    ]
                    st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Import & Analyze.")
            with csave2:
                if st.button('Analyze & Save Candidates to CRM',use_container_width=True):
                    spotify_summary=fit.get('spotify_summary') or {}
                    song_info=fit.get('song') or {}
                    song_context={
                        'title': song_info.get('title') or spotify_summary.get('title',''),
                        'artist': song_info.get('artist') or spotify_summary.get('artist',''),
                        'spotify_url': spotify_summary.get('spotify_url',''),
                        'release_status': 'released' if spotify_summary.get('spotify_url') else 'unreleased',
                        'release_age_label': spotify_summary.get('release_age_label',''),
                    }
                    rows=[
                        {**{k:c.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id']},'song_context':song_context}
                        for c in fresh
                    ]
                    if rows:
                        save_raw_json(rows); st.session_state.report=process_playlists(rows,do_web_enrichment=do_web,do_spotify_api=False,queue_email_approval=queue_email,song_context=song_context,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
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
                st.write(f"SubmitHub verified: {'yes' if item.get('submithub_verified') else 'no'} | SubmitHub URL: {item.get('submithub_url') or 'Not found'}")
                guard=item.get('outreach_guard') or {}
                if item.get('email_queue_blocked'):
                    st.warning(item.get('email_queue_block_reason') or guard.get('reason') or 'Email queue blocked by playlist safeguard.')
                elif item.get('email_queue_id'):
                    st.success(f"Queued email approval #{item.get('email_queue_id')}")
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
            st.write(f"Song: {item.get('song_title') or 'Not saved on this draft'}")
            if item.get('song_url'):
                st.write(f"Song link: {item.get('song_url')}")
            else:
                st.warning('No song link is saved on this draft. Verify the body manually before approving; older drafts may predate the Spotify-link safeguard.')
            st.text_area('Draft body',item.get('body',''),height=180,key=f"qbody_{item['id']}")
            c1,c2,c3=st.columns(3)
            with c1:
                if st.button('Approve',key=f"approve_{item['id']}",use_container_width=True):
                    update_email_queue_status(item['id'],'approved'); st.rerun()
            with c2:
                if st.button('Mark Sent',key=f"sent_{item['id']}",use_container_width=True,disabled=item.get('status')!='approved'):
                    update_email_queue_status(item['id'],'sent'); add_outreach_event(item['curator_id'],item['playlist_id'],'email','sent',item.get('body','')); update_playlist_status(item['playlist_id'],'sent'); st.rerun()
                if item.get('status')!='approved': st.caption('Approve before marking sent.')
            with c3:
                if st.button('Reject',key=f"reject_{item['id']}",use_container_width=True):
                    update_email_queue_status(item['id'],'rejected'); st.rerun()
