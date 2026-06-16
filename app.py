import importlib, json, time, pandas as pd, streamlit as st
from src.audio_analysis import save_uploaded_song_file
from src.campaigns import prepare_campaign_plan
from src.chartmetric import chartmetric_status
from src.chartmetric_mining import run_chartmetric_mining
from src.cyanite import cyanite_status,fetch_cyanite_analysis,upload_song_audio_to_cyanite
from src.database import init_db,get_all_playlists,add_outreach_event,update_playlist_status,queue_email,playlist_outreach_guard,get_song_fit_targets,bulk_upsert_artist_songs,get_artist_songs,save_artist_sound_profile,get_artist_sound_profile,bulk_upsert_release_songs,get_release_songs,save_release_campaign_brief,get_release_campaigns,backup_song_profiles_json,bulk_upsert_artist_references,get_artist_references,get_mining_jobs,get_mined_playlists
from src.ingest_playlists import load_playlists_from_text,playlists_from_links,save_raw_json
from src.pipeline import process_playlists
from src.settings import DB_PATH,LOCAL_DATA_DIR,local_data_path
from src.song_analyzer import analyze_song_fit,score_spotify_playlist_candidates
import src.playlist_discovery as playlist_discovery
from src.spotify_api import ENGLISH_SPOTIFY_MARKETS,SpotifyAPI,fetch_spotify_track,search_spotify_playlists_multi_market
from src.web_enricher import enrich_playlist_from_url,enrich_track_from_url
playlist_discovery=importlib.reload(playlist_discovery)
discover_catalog_song_playlists=playlist_discovery.discover_catalog_song_playlists
discover_released_track_playlists=playlist_discovery.discover_released_track_playlists
st.set_page_config(page_title='streambase',page_icon='🎛️',layout='wide')
st.title('🎛️ streambase')
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
    playlist_cooldown_days=st.number_input('Playlist pitch cooldown days',min_value=0,max_value=180,value=30,step=1,help='Prevents streambase from queueing another song to the same playlist too soon.')
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
if 'home_playlist_searches' not in st.session_state: st.session_state.home_playlist_searches=[]
if 'home_spotify_playlist_candidates' not in st.session_state: st.session_state.home_spotify_playlist_candidates=[]
if 'batch_playlist_candidates' not in st.session_state: st.session_state.batch_playlist_candidates=[]
if 'batch_playlist_log' not in st.session_state: st.session_state.batch_playlist_log=[]
if 'campaign_plan' not in st.session_state: st.session_state.campaign_plan={}
if 'campaign_copy_edits' not in st.session_state: st.session_state.campaign_copy_edits={}
if 'pitch_release_type' not in st.session_state: st.session_state.pitch_release_type='new_release'
if 'pitch_spotify_url' not in st.session_state: st.session_state.pitch_spotify_url=''
if 'pitch_spotify_meta' not in st.session_state: st.session_state.pitch_spotify_meta={}
def load_latest_report():
    if st.session_state.report:
        return st.session_state.report
    path=local_data_path('report.json')
    if not path.exists():
        return {}
    try:
        report=json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError,OSError):
        return {}
    st.session_state.report=report
    return report
def df_session():
    df=pd.DataFrame(st.session_state.playlists) if st.session_state.playlists else pd.DataFrame(columns=['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description'])
    for col in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description']:
        if col not in df.columns: df[col]=0 if col=='follower_count' else ''
    return df[['playlist_name','playlist_url','follower_count','curator_name','related_artists','last_updated','spotify_description']]
def merge_playlist_editor_rows(original_rows, edited_rows):
    merged=[]
    for idx,edited in enumerate(edited_rows):
        base=dict(original_rows[idx]) if idx<len(original_rows) else {}
        base.update(edited)
        merged.append(base)
    return merged
def catalog_playlist_summary(catalog_rows, targets):
    def clean(value):
        return str(value or '').strip().lower()
    def primary_genre(song):
        tags=[tag.strip() for tag in str(song.get('genre_tags') or '').split(';') if tag.strip()]
        return tags[0] if tags else ''
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
            'primary_genre':primary_genre(song),
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

tab_scan,tab_catalog,tab_playlists,tab_campaigns=st.tabs(['Scan A Song','Catalog','Playlists','Campaigns'])
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
            st.session_state.home_playlist_searches=[]
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
                            saved_playlists=get_all_playlists()
                            if spotify.configured:
                                discovery=discover_released_track_playlists(
                                    meta,
                                    saved_playlists=saved_playlists,
                                    query_limit=4,
                                    limit_per_query=5,
                                    markets=ENGLISH_SPOTIFY_MARKETS,
                                )
                                st.session_state.home_song_fit=discovery.get('song_fit')
                                st.session_state.home_playlist_searches=discovery.get('searches',[])
                                st.session_state.home_spotify_playlist_candidates=discovery.get('candidates',[])
                                if discovery.get('error'):
                                    st.warning(discovery.get('error'))
                                st.success(f"Loaded Spotify metadata and scored {len(st.session_state.home_spotify_playlist_candidates)} playlist candidate(s).")
                            else:
                                st.session_state.home_song_fit=analyze_song_fit(
                                    None,
                                    title=meta.get('title',''),
                                    artist=meta.get('artist',''),
                                    reference_artists=meta.get('reference_artists',''),
                                    descriptors=meta.get('descriptors',''),
                                    saved_playlists=saved_playlists,
                                    spotify_track=meta,
                                    reference_tracks=[],
                                    cyanite_profile={},
                                )
                                st.session_state.home_playlist_searches=(st.session_state.home_song_fit or {}).get('discovery_searches',[])
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
            st.session_state.home_playlist_searches=[]
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
                                'artist_name':pitch_meta.get('artist',''),
                                'spotify_url':pitch_track_url if pitch_is_released else '',
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
                        st.session_state.home_playlist_searches=(st.session_state.home_song_fit or {}).get('discovery_searches',[])
                    else:
                        status.update(label='Cyanite analysis is not complete yet.',state='error')
                        st.info(analysis.get('error') or 'Cyanite is still processing. Try scanning again from Scan A Song.')
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
                    st.session_state.home_playlist_searches=(st.session_state.home_song_fit or {}).get('discovery_searches',[])
                home_fit=st.session_state.home_song_fit or {}
                searches=st.session_state.home_playlist_searches or home_fit.get('discovery_searches') or []
                if searches:
                    st.markdown('#### Spotify Playlist Search')
                    st.caption('Search breadth is controlled here. streambase runs a limited number of Song DNA keyword searches, asks Spotify for a limited number of results per search, removes duplicates, then scores candidates.')
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
                    st.caption(f"Maximum raw Spotify results this run: {estimated_max}. streambase dedupes across markets, so final candidates may be lower.")
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
                            st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Playlists.")
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
        if not home_analysis and st.session_state.home_song_fit:
            home_fit=st.session_state.home_song_fit or {}
            searches=st.session_state.home_playlist_searches or home_fit.get('discovery_searches') or []
            if searches:
                st.markdown('#### Spotify Playlist Search')
                st.caption('streambase used the released Spotify link to build similar-artist and Song DNA searches, then scored playlist matches automatically.')
                st.dataframe(pd.DataFrame(searches),use_container_width=True,hide_index=True)
                hs1,hs2,hs3=st.columns(3)
                with hs1:
                    home_query_limit=st.number_input('Spotify searches to run',min_value=1,max_value=len(searches),value=min(3,len(searches)),step=1,key='home_query_limit')
                with hs2:
                    home_per_query=st.number_input('Spotify results per search',min_value=1,max_value=10,value=5,step=1,key='home_per_query')
                with hs3:
                    home_markets=st.multiselect('Spotify markets',options=ENGLISH_SPOTIFY_MARKETS+['ZA','SG','PH'],default=ENGLISH_SPOTIFY_MARKETS,key='home_markets')
                if st.button('Refresh Spotify Playlist Matches',use_container_width=True,disabled=not spotify.configured):
                    if pitch_is_released and pitch_meta:
                        discovery=discover_released_track_playlists(
                            pitch_meta,
                            saved_playlists=get_all_playlists(),
                            query_limit=int(home_query_limit),
                            limit_per_query=int(home_per_query),
                            markets=home_markets or ENGLISH_SPOTIFY_MARKETS,
                        )
                        if discovery.get('error'):
                            st.error(discovery.get('error') or 'Spotify playlist search failed.')
                        st.session_state.home_song_fit=discovery.get('song_fit') or st.session_state.home_song_fit
                        st.session_state.home_playlist_searches=discovery.get('searches',[])
                        candidates=discovery.get('candidates',[])
                    else:
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
                        st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Playlists.")
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
        st.markdown('#### Uploaded Catalog')
        st.caption('Click a song row to see every playlist saved for it.')
        catalog_df=pd.DataFrame(catalog_display_rows)
        catalog_view=catalog_df[['title','primary_genre','release_status','playlists_added','last_updated']]
        selected_catalog=st.dataframe(
            catalog_view,
            use_container_width=True,
            hide_index=True,
            on_select='rerun',
            selection_mode='single-row',
            column_config={
                'title':st.column_config.TextColumn('Song'),
                'primary_genre':st.column_config.TextColumn('Genre'),
                'release_status':st.column_config.TextColumn('Release'),
                'playlists_added':st.column_config.NumberColumn('Playlists',format='%d'),
                'last_updated':st.column_config.TextColumn('Last Updated'),
            },
        )
        with st.expander('View full catalog genre list',expanded=False):
            all_genres=catalog_tag_summary(catalog_rows)
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
with tab_playlists:
    st.subheader('Playlists')
    st.caption('Upload playlist CSVs, paste Spotify playlist links, analyze them, and review saved playlist ratings.')
    catalog_song_rows=get_release_songs()
    if catalog_song_rows:
        with st.expander('Fetch playlists for catalog songs',expanded=False):
            st.caption('Select one or more catalog songs, then streambase will use their Spotify metadata and Cyanite tags to find playlist candidates.')
            selector_rows=[]
            for song in catalog_song_rows:
                primary_genre=next((tag.strip() for tag in str(song.get('genre_tags') or '').split(';') if tag.strip()),'')
                selector_rows.append({
                    'select':False,
                    'id':int(song.get('id') or 0),
                    'title':song.get('title') or song.get('file_name') or 'Untitled',
                    'artist':song.get('artist_name') or '',
                    'genre':primary_genre,
                    'release':song.get('release_status') or '',
                    'spotify_url':song.get('spotify_url') or '',
                })
            selected_df=st.data_editor(
                pd.DataFrame(selector_rows),
                use_container_width=True,
                hide_index=True,
                key='catalog_song_playlist_selector',
                disabled=['id','title','artist','genre','release','spotify_url'],
                column_config={
                    'select':st.column_config.CheckboxColumn('Fetch',help='Select this song for playlist discovery.'),
                    'id':None,
                    'title':st.column_config.TextColumn('Song'),
                    'artist':st.column_config.TextColumn('Artist'),
                    'genre':st.column_config.TextColumn('Genre'),
                    'release':st.column_config.TextColumn('Release'),
                    'spotify_url':st.column_config.LinkColumn('Spotify'),
                },
            )
            selected_ids=set(selected_df.loc[selected_df['select']==True,'id'].astype(int).tolist()) if not selected_df.empty else set()
            b1,b2,b3=st.columns(3)
            with b1:
                batch_query_limit=st.number_input('Searches per song',min_value=1,max_value=8,value=4,step=1,key='batch_query_limit')
            with b2:
                batch_per_query=st.number_input('Results per search',min_value=1,max_value=10,value=5,step=1,key='batch_per_query')
            with b3:
                batch_markets=st.multiselect('Markets',options=ENGLISH_SPOTIFY_MARKETS+['ZA','SG','PH'],default=ENGLISH_SPOTIFY_MARKETS,key='batch_markets')
            if st.button('Fetch Playlists for Selected Songs',type='primary',use_container_width=True,disabled=not selected_ids or not spotify.configured,key='batch_fetch_catalog_playlists'):
                selected_songs=[song for song in catalog_song_rows if int(song.get('id') or 0) in selected_ids]
                saved_playlists=get_all_playlists()
                staged=[]
                log=[]
                seen=set()
                st.caption('Fetching playlist candidates from selected catalog songs...')
                progress=st.progress(0)
                batch_status=st.empty()
                for idx,song in enumerate(selected_songs):
                    title=song.get('title') or song.get('file_name') or 'Untitled'
                    batch_status.write(f"Searching for {title}...")
                    spotify_meta={}
                    if song.get('spotify_url') and spotify.configured:
                        spotify_meta=fetch_spotify_track(song.get('spotify_url')) or {}
                    result=discover_catalog_song_playlists(
                        song,
                        saved_playlists=saved_playlists,
                        spotify_track=spotify_meta,
                        query_limit=int(batch_query_limit),
                        limit_per_query=int(batch_per_query),
                        markets=batch_markets or ENGLISH_SPOTIFY_MARKETS,
                    )
                    song_fit=result.get('song_fit') or {}
                    song_info=song_fit.get('song') or {}
                    song_context={
                        'title':song_info.get('title') or title,
                        'artist':song_info.get('artist') or song.get('artist_name',''),
                        'spotify_url':(spotify_meta or {}).get('spotify_url') or song.get('spotify_url',''),
                        'release_status':song.get('release_status') or '',
                        'release_age_label':((song_fit.get('release_guidance') or {}).get('release_age_label') or ''),
                        'catalog_song_id':int(song.get('id') or 0),
                    }
                    fresh_count=0
                    for candidate in result.get('candidates',[]):
                        key=(candidate.get('playlist_url') or candidate.get('spotify_playlist_id') or candidate.get('playlist_name',''),song_context['title'])
                        if key in seen:
                            continue
                        seen.add(key)
                        row={k:candidate.get(k,'') for k in ['playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id']}
                        row['song_context']=song_context
                        staged.append(row)
                        fresh_count+=1
                    log.append({'song':title,'queries_run':len(result.get('queries_run',[])),'candidates':fresh_count,'error':result.get('error','')})
                    progress.progress((idx+1)/max(len(selected_songs),1))
                st.session_state.batch_playlist_candidates=staged
                st.session_state.batch_playlist_log=log
                st.session_state.playlists=staged
                batch_status.success(f"Fetched {len(staged)} playlist candidate(s) from {len(selected_songs)} song(s).")
                st.success(f"Staged {len(staged)} playlist candidate(s) below for review.")
            if not spotify.configured:
                st.info('Connect Spotify API credentials before batch fetching playlist candidates.')
            if st.session_state.batch_playlist_log:
                st.markdown('#### Latest batch')
                st.dataframe(pd.DataFrame(st.session_state.batch_playlist_log),use_container_width=True,hide_index=True)
    with st.expander('Add playlists',expanded=not bool(get_all_playlists())):
        mode=st.radio('Choose input method',['Upload CSV','Paste Spotify playlist links'],horizontal=True,key='playlist_add_mode')
        if mode=='Paste Spotify playlist links':
            raw=st.text_area('Spotify playlist links',height=140,placeholder='https://open.spotify.com/playlist/...',key='playlist_paste_links')
            c1,c2=st.columns(2)
            with c1:
                if st.button('Load Pasted Links',use_container_width=True):
                    st.session_state.playlists=playlists_from_links(raw)
                    st.success(f"Loaded {len(st.session_state.playlists)} playlist link(s).")
            with c2:
                if st.button('Fetch Spotify Details',use_container_width=True):
                    if not st.session_state.playlists:
                        st.error('Load playlist links first.')
                    else:
                        updated=[]; prog=st.progress(0)
                        for i,row in enumerate(st.session_state.playlists):
                            row=dict(row); meta=enrich_playlist_from_url(row.get('playlist_url',''))
                            if meta.get('playlist_name') and not row.get('playlist_name'): row['playlist_name']=meta['playlist_name']
                            if meta.get('curator_name') and not row.get('curator_name'): row['curator_name']=meta['curator_name']
                            if meta.get('spotify_description'): row['spotify_description']=meta['spotify_description']
                            updated.append(row); prog.progress((i+1)/max(len(st.session_state.playlists),1))
                        st.session_state.playlists=updated
                        st.success('Spotify details fetched where available.')
        else:
            up=st.file_uploader('Choose playlist CSV',type=['csv'],key='playlist_csv_upload')
            if up:
                st.session_state.playlists=load_playlists_from_text(up.read().decode('utf-8-sig'))
                st.success(f"Loaded {len(st.session_state.playlists)} playlist(s) from CSV.")
        if st.session_state.playlists:
            st.markdown('#### Review before saving')
            st.caption('Scores improve when rows include playlist title, follower count, related artists, and description.')
            original_playlist_rows=[dict(row) for row in st.session_state.playlists]
            edited=st.data_editor(df_session(),use_container_width=True,num_rows='dynamic')
            st.session_state.playlists=merge_playlist_editor_rows(original_playlist_rows,edited.fillna('').to_dict(orient='records'))
            c1,c2=st.columns(2)
            with c1:
                if st.button('Analyze & Save Playlists',type='primary',use_container_width=True):
                    with st.spinner('Scoring playlists, finding contacts, and saving curator profiles...'):
                        save_raw_json(st.session_state.playlists)
                        st.session_state.report=process_playlists(st.session_state.playlists,do_web_enrichment=do_web,do_spotify_api=do_spotify,queue_email_approval=queue_email,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
                    st.success('Analysis complete. Playlists saved.')
            with c2:
                if st.button('Clear Loaded Playlists',use_container_width=True):
                    st.session_state.playlists=[]; st.session_state.report=None; st.rerun()

    rep=load_latest_report()
    rows=get_all_playlists()
    if rep:
        a,b,c=st.columns(3)
        a.metric('Processed',rep['total_playlists_processed'])
        b.metric('Contactable',rep['contactable_curators_count'])
        c.metric('% Contactable',f"{rep['contactable_curators_percent']}%")
    if rows:
        df=pd.DataFrame(rows)
        display=df.copy()
        if 'name' in display.columns and 'playlist_name' not in display.columns:
            display['playlist_name']=display['name']
        if 'url' in display.columns and 'playlist_url' not in display.columns:
            display['playlist_url']=display['url']
        display['rating_confidence']=0
        display['rating_evidence']=''
        if 'scoring_notes' in display.columns:
            for idx,note in display['scoring_notes'].fillna('').items():
                try:
                    parsed=json.loads(note) if note else {}
                except json.JSONDecodeError:
                    parsed={}
                display.at[idx,'rating_confidence']=parsed.get('confidence_score',0)
                display.at[idx,'rating_evidence']='; '.join(parsed.get('evidence',[]))
        if 'priority' in display.columns:
            display['priority']=display.apply(
                lambda row: 'needs review' if str(row.get('priority','')).lower()=='ignore' and float(row.get('rating_confidence') or 0)<35 else 'low fit' if str(row.get('priority','')).lower()=='ignore' else row.get('priority',''),
                axis=1,
            )
        for col in ['playlist_name','curator_name','final_score','priority','rating_confidence','rating_evidence','followers','similarity_score','intersection_score','status','playlist_url']:
            if col not in display.columns:
                display[col]=''
        display=display.sort_values('final_score',ascending=False)
        st.markdown('#### Saved Playlists')
        st.dataframe(
            display[['playlist_name','final_score','priority','rating_confidence','rating_evidence','followers','curator_name','similarity_score','intersection_score','status','playlist_url']],
            use_container_width=True,
            hide_index=True,
            column_config={
                'playlist_name':st.column_config.TextColumn('Playlist'),
                'final_score':st.column_config.ProgressColumn('Rating',min_value=0,max_value=100,format='%.0f'),
                'priority':st.column_config.TextColumn('Decision'),
                'rating_confidence':st.column_config.ProgressColumn('Confidence',min_value=0,max_value=100,format='%.0f'),
                'rating_evidence':st.column_config.TextColumn('Evidence'),
                'followers':st.column_config.NumberColumn('Followers',format='%d'),
                'curator_name':st.column_config.TextColumn('Curator'),
                'similarity_score':st.column_config.NumberColumn('Similarity',format='%.0f'),
                'intersection_score':st.column_config.NumberColumn('Overlap',format='%.0f'),
                'status':st.column_config.TextColumn('Status'),
                'playlist_url':st.column_config.LinkColumn('Spotify URL'),
            },
        )
        st.download_button('Download Playlists CSV',df.to_csv(index=False).encode('utf-8'),'streambase_playlists.csv','text/csv')
    else:
        st.info('No playlists saved yet. Upload a CSV or paste Spotify playlist links above.')
    if rep:
        st.subheader('Outreach drafts from latest run')
        for item in sorted(rep['processed_playlists'],key=lambda x:x.get('final_score',0),reverse=True)[:10]:
            with st.expander(f"{item.get('playlist_name') or 'Unnamed'} · {item.get('final_score')} · {item.get('priority')}"):
                st.write(f"Curator: {item.get('curator_name') or 'Unknown'}")
                st.write(f"Similarity: {item.get('similarity_score')} | Overlap: {item.get('intersection_score')} | Contact confidence: {item.get('contact_confidence')}")
                st.write(f"Email: {item.get('email') or 'Not found'} | Instagram: {item.get('instagram') or 'Not found'} | Submission: {item.get('submission_page') or 'Not found'}")
                st.write(f"SubmitHub verified: {'yes' if item.get('submithub_verified') else 'no'} | SubmitHub URL: {item.get('submithub_url') or 'Not found'}")
                breakdown=(item.get('similarity_breakdown') or {})
                if item.get('rating_confidence') is not None:
                    st.write(f"Rating confidence: {item.get('rating_confidence')} | Evidence: {'; '.join(item.get('rating_evidence') or []) or 'limited evidence'}")
                guard=item.get('outreach_guard') or {}
                if item.get('email_queue_blocked'):
                    st.warning(item.get('email_queue_block_reason') or guard.get('reason') or 'Email queue blocked by playlist safeguard.')
                elif item.get('email_queue_id'):
                    st.success(f"Queued email approval #{item.get('email_queue_id')}")
                if breakdown:
                    st.json(breakdown,expanded=False)
                ix=item.get('intersection_breakdown') or {}
                if ix: st.json(ix,expanded=False)
                st.text_area('Email',item.get('email_message',''),height=160,key=f"e_{item.get('playlist_url')}")
                st.text_area('Instagram DM',item.get('instagram_dm',''),height=90,key=f"d_{item.get('playlist_url')}")
                st.text_area('Submission note',item.get('submission_note',''),height=90,key=f"s_{item.get('playlist_url')}")
with tab_campaigns:
    st.subheader('Campaigns')
    st.caption('Prepare one clean outreach plan from the latest analyzed playlist candidates. streambase chooses the best song per playlist and avoids duplicate curator blasts.')
    latest_report=load_latest_report()
    processed_candidates=latest_report.get('processed_playlists',[])
    if processed_candidates:
        c1,c2=st.columns([1,1])
        with c1:
            if st.button('Prepare Campaign',type='primary',use_container_width=True):
                st.session_state.campaign_plan=prepare_campaign_plan(
                    processed_candidates,
                    cooldown_days=int(playlist_cooldown_days),
                    guard_fn=playlist_outreach_guard,
                )
                st.session_state.campaign_copy_edits={}
        with c2:
            st.caption(f"Latest analyzed candidates: {len(processed_candidates)}")
    else:
        saved_count=len(get_all_playlists())
        if saved_count:
            st.info(f"{saved_count} playlist(s) are saved, but no latest song-specific analysis report was found. Run Analyze & Save Playlists from the Playlists tab once, then Campaigns will load the generated emails, DMs, and submission links here.")
        else:
            st.info('Analyze and save playlists first. Campaigns are built from the latest playlist analysis so emails and DMs have song-specific context.')

    plan=st.session_state.campaign_plan or {}
    campaign_rows=plan.get('rows',[])
    if campaign_rows:
        m1,m2,m3,m4=st.columns(4)
        m1.metric('Ready',plan.get('ready_count',0))
        m2.metric('Worth Considering',plan.get('worth_considering_count',0))
        m3.metric('Wait',plan.get('wait_count',0))
        m4.metric('Unique Playlists',plan.get('unique_playlist_count',0))
        table_rows=[
            {
                'send':row.get('send',False),
                'status':row.get('status',''),
                'playlist_name':row.get('playlist_name',''),
                'curator_name':row.get('curator_name',''),
                'selected_song':row.get('selected_song',''),
                'fit_score':row.get('fit_score',0),
                'email':row.get('email',''),
                'instagram':row.get('instagram',''),
                'submission_page':row.get('submission_page',''),
                'reason':row.get('reason',''),
            }
            for row in campaign_rows
        ]
        edited_campaign=st.data_editor(
            pd.DataFrame(table_rows),
            use_container_width=True,
            hide_index=True,
            key='campaign_review_editor',
            disabled=['status','playlist_name','curator_name','selected_song','fit_score','email','instagram','submission_page','reason'],
            column_config={
                'send':st.column_config.CheckboxColumn('Send'),
                'status':st.column_config.TextColumn('Status'),
                'playlist_name':st.column_config.TextColumn('Playlist'),
                'curator_name':st.column_config.TextColumn('Curator'),
                'selected_song':st.column_config.TextColumn('Song'),
                'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                'email':st.column_config.TextColumn('Email'),
                'instagram':st.column_config.LinkColumn('Instagram'),
                'submission_page':st.column_config.LinkColumn('Submission'),
                'reason':st.column_config.TextColumn('Reason'),
            },
        )
        send_flags=edited_campaign['send'].tolist() if not edited_campaign.empty else []
        for idx,flag in enumerate(send_flags):
            if idx<len(campaign_rows):
                campaign_rows[idx]['send']=bool(flag)
        labels=[f"{i+1}. {row.get('playlist_name') or 'playlist'} · {row.get('selected_song') or 'song'} · {row.get('status')}" for i,row in enumerate(campaign_rows)]
        selected_label=st.selectbox('Review campaign copy',labels,key='campaign_copy_selector') if labels else ''
        selected_idx=labels.index(selected_label) if selected_label in labels else 0
        row=campaign_rows[selected_idx]
        edit_key=row.get('playlist_url') or f"campaign_{selected_idx}"
        st.markdown('#### Campaign Copy')
        st.caption(row.get('reason',''))
        if row.get('status')=='Worth considering':
            st.warning(row.get('cooldown_note') or 'This is inside the cooldown window, but the fit is unusually strong.')
        if row.get('alternates'):
            st.caption('Other matching songs: '+', '.join([f"{alt.get('song')} ({alt.get('fit_score')})" for alt in row.get('alternates',[])]))
        existing_edit=st.session_state.campaign_copy_edits.get(edit_key,{})
        email_body=st.text_area('Email draft',existing_edit.get('email_message') or row.get('email_message',''),height=220,key=f"campaign_email_{selected_idx}")
        dm_body=st.text_area('Instagram DM draft',existing_edit.get('instagram_dm') or row.get('instagram_dm',''),height=110,key=f"campaign_dm_{selected_idx}")
        submission_body=st.text_area('Submission note',existing_edit.get('submission_note') or row.get('submission_note',''),height=110,key=f"campaign_submission_{selected_idx}")
        st.session_state.campaign_copy_edits[edit_key]={'email_message':email_body,'instagram_dm':dm_body,'submission_note':submission_body}
        l1,l2,l3=st.columns(3)
        with l1:
            if row.get('email'):
                st.link_button('Open Email',f"mailto:{row.get('email')}",use_container_width=True)
        with l2:
            if row.get('instagram'):
                st.link_button('Open Instagram',row.get('instagram'),use_container_width=True)
        with l3:
            if row.get('submission_page'):
                st.link_button('Open Submission',row.get('submission_page'),use_container_width=True)
        if st.button('Approve Selected Emails',type='primary',use_container_width=True):
            queued=0
            skipped=0
            for idx,item in enumerate(campaign_rows):
                if not item.get('send') or not item.get('email'):
                    skipped+=1
                    continue
                raw=item.get('raw') or {}
                raw_key=item.get('playlist_url') or f"campaign_{idx}"
                edits=st.session_state.campaign_copy_edits.get(raw_key,{})
                body=edits.get('email_message') or item.get('email_message','')
                song_context=raw.get('song_context') if isinstance(raw.get('song_context'),dict) else {}
                queue_id=queue_email(
                    int(raw.get('curator_id') or 0),
                    int(raw.get('playlist_id') or 0),
                    item.get('email',''),
                    f"Submission for {item.get('playlist_name') or 'your playlist'}",
                    body,
                    song_context=song_context,
                    cooldown_days=int(playlist_cooldown_days),
                    enforce_cooldown=item.get('status')!='Worth considering',
                )
                if queue_id:
                    queued+=1
                    add_outreach_event(int(raw.get('curator_id') or 0),int(raw.get('playlist_id') or 0),'email','drafted',body)
                else:
                    skipped+=1
            st.success(f"Approved {queued} email draft(s). Skipped {skipped}.")
    elif processed_candidates:
        st.info('Click Prepare Campaign to build the review table.')
