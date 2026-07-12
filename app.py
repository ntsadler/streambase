import html, importlib, json, os, time, requests, pandas as pd, streamlit as st
import streamlit.components.v1 as components
from urllib.parse import urlencode,urlparse
from src.audio_analysis import clean_filename, save_uploaded_song_file
from src.campaigns import prepare_campaign_plan
import src.campaigns as campaigns_module
import src.database as database_module
from src.chartmetric import chartmetric_status
from src.chartmetric_mining import run_chartmetric_mining
import src.chartmetric_mining as chartmetric_mining_module
from src.viberate import viberate_status
from src.viberate_mining import run_viberate_mining
import src.viberate_mining as viberate_mining_module
from src.cyanite import cyanite_status,fetch_cyanite_analysis,upload_song_audio_to_cyanite
from src.database import init_db,get_all_playlists,add_outreach_event,get_outreach_events_for_playlists,update_playlist_status,queue_email,playlist_outreach_guard,get_song_fit_targets,bulk_upsert_artist_songs,get_artist_songs,save_artist_sound_profile,get_artist_sound_profile,bulk_upsert_release_songs,get_release_songs,save_release_campaign_brief,get_release_campaigns,backup_song_profiles_json,bulk_upsert_artist_references,get_artist_references,get_mining_jobs,get_mined_playlists,upsert_contact_method,get_email_queue,update_email_queue_status,update_email_queue_after_send
from src.email_sender import email_sender_status,send_email_via_resend
from src.ingest_playlists import load_playlists_from_text,playlists_from_links,save_raw_json
import src.mining_targets as mining_targets_module
from src.pipeline import process_playlists
import src.pipeline as pipeline_module
from src.settings import DB_PATH,LOCAL_DATA_DIR,local_data_path
from src.song_analyzer import analyze_song_fit,score_spotify_playlist_candidates
import src.song_analyzer as song_analyzer_module
import src.playlist_discovery as playlist_discovery
from src.spotify_api import ENGLISH_SPOTIFY_MARKETS,SpotifyAPI,fetch_spotify_playlist,fetch_spotify_track,search_spotify_playlists_multi_market
from src.web_enricher import enrich_playlist_from_url,enrich_track_from_url
import src.tavily_enricher as tavily_enricher_module
database_module=importlib.reload(database_module)
playlist_discovery=importlib.reload(playlist_discovery)
chartmetric_mining_module=importlib.reload(chartmetric_mining_module)
viberate_mining_module=importlib.reload(viberate_mining_module)
mining_targets_module=importlib.reload(mining_targets_module)
import src.gmail_replies as gmail_replies_module
gmail_replies_module=importlib.reload(gmail_replies_module)
campaigns_module=importlib.reload(campaigns_module)
pipeline_module=importlib.reload(pipeline_module)
song_analyzer_module=importlib.reload(song_analyzer_module)
tavily_enricher_module=importlib.reload(tavily_enricher_module)
prepare_campaign_plan=campaigns_module.prepare_campaign_plan
render_campaign_template=campaigns_module.render_campaign_template
DEFAULT_CAMPAIGN_BODY=campaigns_module.DEFAULT_CAMPAIGN_BODY
DEFAULT_CAMPAIGN_SUBJECT=campaigns_module.DEFAULT_CAMPAIGN_SUBJECT
run_chartmetric_mining=chartmetric_mining_module.run_chartmetric_mining
run_viberate_mining=viberate_mining_module.run_viberate_mining
build_catalog_mining_profile=mining_targets_module.build_catalog_mining_profile
process_playlists=pipeline_module.process_playlists
analyze_song_fit=song_analyzer_module.analyze_song_fit
score_spotify_playlist_candidates=song_analyzer_module.score_spotify_playlist_candidates
preferred_catalog_title=song_analyzer_module.preferred_catalog_title
discover_catalog_song_playlists=playlist_discovery.discover_catalog_song_playlists
discover_released_track_playlists=playlist_discovery.discover_released_track_playlists
init_db=database_module.init_db
get_all_playlists=database_module.get_all_playlists
add_outreach_event=database_module.add_outreach_event
get_outreach_events_for_playlists=database_module.get_outreach_events_for_playlists
update_playlist_status=database_module.update_playlist_status
queue_email=database_module.queue_email
playlist_outreach_guard=database_module.playlist_outreach_guard
get_song_fit_targets=database_module.get_song_fit_targets
bulk_upsert_artist_songs=database_module.bulk_upsert_artist_songs
get_artist_songs=database_module.get_artist_songs
save_artist_sound_profile=database_module.save_artist_sound_profile
get_artist_sound_profile=database_module.get_artist_sound_profile
bulk_upsert_release_songs=database_module.bulk_upsert_release_songs
get_release_songs=database_module.get_release_songs
save_release_campaign_brief=database_module.save_release_campaign_brief
get_release_campaigns=database_module.get_release_campaigns
backup_song_profiles_json=database_module.backup_song_profiles_json
bulk_upsert_artist_references=database_module.bulk_upsert_artist_references
get_artist_references=database_module.get_artist_references
get_mining_jobs=database_module.get_mining_jobs
get_mined_playlists=database_module.get_mined_playlists
import_song_seed_playlists=database_module.import_song_seed_playlists
upsert_contact_method=database_module.upsert_contact_method
get_email_queue=database_module.get_email_queue
update_email_queue_status=database_module.update_email_queue_status
update_email_queue_after_send=database_module.update_email_queue_after_send
create_outreach_campaign=database_module.create_outreach_campaign
update_outreach_campaign=database_module.update_outreach_campaign
get_outreach_campaigns=database_module.get_outreach_campaigns
save_outreach_campaign_targets=database_module.save_outreach_campaign_targets
get_outreach_campaign_targets=database_module.get_outreach_campaign_targets
update_outreach_campaign_target_status=database_module.update_outreach_campaign_target_status
sync_song_campaign_tasks=database_module.sync_song_campaign_tasks
get_song_campaign_tasks=database_module.get_song_campaign_tasks
get_song_campaign_overview=database_module.get_song_campaign_overview
update_campaign_outreach_task=database_module.update_campaign_outreach_task
get_email_replies=database_module.get_email_replies
gmail_reply_status=gmail_replies_module.gmail_reply_status
sync_gmail_replies=gmail_replies_module.sync_gmail_replies
tavily_status=tavily_enricher_module.tavily_status
enrich_playlists_with_tavily=tavily_enricher_module.enrich_playlists_with_tavily

def normalize_email(value):
    return str(value or '').strip().lower()

def split_sendable_email_drafts(rows):
    sendable=[]
    duplicate=[]
    missing=[]
    seen={}
    for row in rows or []:
        email_key=normalize_email(row.get('to_email'))
        if not email_key:
            missing.append(row)
            continue
        if email_key in seen:
            duplicate.append({**row,'duplicate_of':seen[email_key].get('playlist_name') or seen[email_key].get('subject') or email_key})
            continue
        seen[email_key]=row
        sendable.append(row)
    return sendable,duplicate,missing

def email_campaign_activity_rows(rows):
    activity=[]
    for row in rows or []:
        status=row.get('status') or ''
        if status not in {'approved','sent','failed'}:
            continue
        activity.append({
            'id':row.get('id'),
            'campaign_name':row.get('campaign_name') or 'Legacy / Unassigned',
            'status':status,
            'to_email':row.get('to_email') or '',
            'playlist_name':row.get('playlist_name') or '',
            'curator_name':row.get('curator_name') or '',
            'song_title':row.get('song_title') or '',
            'subject':row.get('subject') or '',
            'updated_at':row.get('updated_at') or row.get('created_at') or '',
            'created_at':row.get('created_at') or '',
        })
    return activity

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

def instagram_dm_url(value):
    parsed=urlparse(value or '')
    handle=parsed.path.strip('/').split('/')[0] if parsed.netloc else ''
    if not handle or handle in {'p','reel','explore','accounts','direct'}:
        return value or ''
    return f'https://ig.me/m/{handle}'

def campaign_action_link(campaign_id,playlist_id,channel):
    base=os.getenv('STREAMBASE_APP_URL','http://localhost:8501').rstrip('/')+'/'
    return f"{base}?{urlencode({'campaign_action':channel,'campaign_id':int(campaign_id),'playlist_id':int(playlist_id)})}"

def handle_campaign_action_redirect():
    channel=str(st.query_params.get('campaign_action') or '').strip().lower()
    campaign_id=int(st.query_params.get('campaign_id') or 0)
    playlist_id=int(st.query_params.get('playlist_id') or 0)
    if channel not in {'instagram','submission'} or not campaign_id or not playlist_id:
        return
    target=next((row for row in get_outreach_campaign_targets(campaign_id) if int(row.get('playlist_id') or 0)==playlist_id),None)
    if not target:
        st.error('Campaign target not found.')
        st.stop()
    destination=instagram_dm_url(target.get('instagram')) if channel=='instagram' else target.get('submission_page','')
    if not destination or not destination.startswith(('http://','https://')):
        st.error(f'No {channel} link is saved for this playlist.')
        st.stop()
    update_outreach_campaign_target_status(campaign_id,playlist_id,channel,'done')
    event_type='instagram_opened' if channel=='instagram' else 'manual_submission_opened'
    add_outreach_event(0,playlist_id,channel,event_type,destination,campaign_id=campaign_id)
    components.html(f"<script>window.top.location.replace({json.dumps(destination)});</script>",height=0)
    st.stop()

handle_campaign_action_redirect()
with st.sidebar:
    spotify=SpotifyAPI(); cm=chartmetric_status(); vb=viberate_status(); cy=cyanite_status(); tv=tavily_status()
    st.header('Settings'); do_web=st.toggle('Fetch public contact info',value=True); do_spotify=st.toggle('Use Spotify API connector',value=spotify.configured,disabled=not spotify.configured); queue_email_approval=st.toggle('Queue emails for approval',value=True)
    playlist_cooldown_days=st.number_input('Playlist pitch cooldown days',min_value=0,max_value=180,value=30,step=1,help='Prevents streambase from queueing another song to the same playlist too soon.')
    minimum_queue_score=st.number_input('Minimum score to queue email',min_value=0,max_value=100,value=50,step=1,help='Lower-scoring playlists can still be saved, but they will not enter email approval automatically.')
    st.markdown('#### Connector status')
    st.write(f"Spotify API: {'connected' if spotify.configured else 'not connected'}")
    st.write(f"Chartmetric: {'connected' if cm['configured']=='yes' else 'not connected'}")
    st.write(f"Viberate: {'connected' if vb['configured']=='yes' else 'not connected'}")
    st.write(f"Cyanite: {'connected' if cy['configured']=='yes' else 'not connected'}")
    st.write(f"Tavily enrichment: {'connected' if tv['configured'] else 'not connected'}")
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
if 'campaign_plan_version' not in st.session_state: st.session_state.campaign_plan_version=0
if 'active_campaign_id' not in st.session_state: st.session_state.active_campaign_id=0
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
def copy_button(label, text, key):
    safe_label=html.escape(label)
    safe_text=json.dumps(text or '')
    components.html(
        f"""
        <button id="copy-{key}" style="width:100%;border-radius:8px;border:1px solid rgba(216,180,95,.38);background:#151519;color:#f6f3ec;padding:10px 12px;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;cursor:pointer;">{safe_label}</button>
        <script>
        const btn = document.getElementById("copy-{key}");
        btn.addEventListener("click", async () => {{
            const text = {safe_text};
            try {{
                await navigator.clipboard.writeText(text);
                btn.textContent = "Copied";
            }} catch (err) {{
                const area = document.createElement("textarea");
                area.value = text;
                document.body.appendChild(area);
                area.select();
                document.execCommand("copy");
                document.body.removeChild(area);
                btn.textContent = "Copied";
            }}
            setTimeout(() => btn.textContent = "{safe_label}", 1400);
        }});
        </script>
        """,
        height=46,
    )
def copy_and_open_button(label, text, url, key):
    safe_label=html.escape(label)
    safe_text=json.dumps(text or '')
    safe_url=json.dumps(url or '')
    components.html(
        f"""
        <button id="copy-open-{key}" style="width:100%;border-radius:8px;border:1px solid rgba(216,180,95,.38);background:#151519;color:#f6f3ec;padding:10px 12px;font:14px -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;cursor:pointer;">{safe_label}</button>
        <script>
        const btn = document.getElementById("copy-open-{key}");
        btn.addEventListener("click", async () => {{
            const text = {safe_text};
            const url = {safe_url};
            try {{
                await navigator.clipboard.writeText(text);
                btn.textContent = "Copied + Opening";
            }} catch (err) {{
                const area = document.createElement("textarea");
                area.value = text;
                document.body.appendChild(area);
                area.select();
                document.execCommand("copy");
                document.body.removeChild(area);
                btn.textContent = "Copied + Opening";
            }}
            if (url) {{
                const opened = window.open(url, "_blank", "noopener,noreferrer");
                if (!opened) {{
                    window.location.href = url;
                }}
            }}
            setTimeout(() => btn.textContent = "{safe_label}", 1600);
        }});
        </script>
        """,
        height=46,
    )
CANDIDATE_FIELD_KEYS=[
    'playlist_name','playlist_url','follower_count','curator_name','related_artists','spotify_description','spotify_playlist_id',
    'candidate_fit_score','curator_target_score','matched_lanes','matched_descriptors','discovery_intent_hits',
    'submission_ready_hits','curator_identity_hits','passive_context_hits','search_query',
]
def candidate_payload(candidate):
    return {k:candidate.get(k,'') for k in CANDIDATE_FIELD_KEYS}
def import_spotify_playlist_links_from_text(raw_text, song_fit, spotify_configured):
    rows=playlists_from_links(raw_text)
    if not rows:
        return []
    enriched=[]
    seen=set()
    for row in rows:
        url=row.get('playlist_url','')
        if not url or url in seen:
            continue
        seen.add(url)
        meta=fetch_spotify_playlist(url) if spotify_configured else {}
        enriched.append({**row,**meta,'source':'cyanite_suggested_playlist','search_query':'Cyanite similar playlist'})
    return score_spotify_playlist_candidates(song_fit or {},enriched,get_all_playlists())
def render_cyanite_playlist_link_import(song_fit, spotify_configured, key_prefix):
    st.markdown('#### Cyanite Suggested Playlist Links')
    raw_links=st.text_area(
        'Paste Cyanite Spotify playlist links',
        height=96,
        placeholder='Paste the Cyanite playlist section or one Spotify playlist URL per line.',
        key=f'{key_prefix}_cyanite_playlist_links',
    )
    if st.button('Import Cyanite Playlist Links',use_container_width=True,key=f'{key_prefix}_import_cyanite_links'):
        candidates=import_spotify_playlist_links_from_text(raw_links,song_fit,spotify_configured)
        if candidates:
            existing={c.get('playlist_url') for c in st.session_state.home_spotify_playlist_candidates if c.get('playlist_url')}
            st.session_state.home_spotify_playlist_candidates.extend([c for c in candidates if c.get('playlist_url') not in existing])
            st.success(f"Imported {len(candidates)} Cyanite playlist candidate(s).")
        else:
            st.info('No Spotify playlist links found to import.')
def cyanite_seed_playlists_from_text(raw_text, spotify_configured):
    rows=load_playlists_from_text(raw_text)
    if not rows:
        rows=playlists_from_links(raw_text)
    enriched=[]
    seen=set()
    for row in rows:
        url=row.get('playlist_url') or row.get('url') or ''
        if not url or url in seen:
            continue
        seen.add(url)
        spotify_meta=fetch_spotify_playlist(url) if spotify_configured else {}
        related_artists=spotify_meta.get('related_artists') or row.get('related_artists','')
        enriched.append({
            **row,
            **spotify_meta,
            'playlist_url':spotify_meta.get('playlist_url') or url,
            'playlist_name':spotify_meta.get('playlist_name') or row.get('playlist_name',''),
            'curator_name':spotify_meta.get('curator_name') or row.get('curator_name',''),
            'follower_count':spotify_meta.get('follower_count') or row.get('follower_count') or 0,
            'related_artists':related_artists,
            'source':'cyanite_seed',
            'fit_score':85,
            'raw':{'cyanite_import_row':row,'spotify_meta':spotify_meta},
        })
    return enriched
def terms_from_text(*values):
    words=[]
    stop={'the','and','for','with','music','playlist','songs','best','new','old','mix','hits','this','that','from','your'}
    for value in values:
        text=str(value or '').lower()
        cleaned=''.join(ch if ch.isalnum() else ' ' for ch in text)
        words.extend([word for word in cleaned.split() if len(word)>2 and word not in stop])
    return set(words)
def song_context_from_catalog_song(song):
    return {
        'title':song.get('title') or song.get('file_name') or 'Untitled',
        'artist':song.get('artist_name') or '',
        'spotify_url':song.get('spotify_url') or '',
        'release_status':song.get('release_status') or '',
        'release_age_label':'',
        'catalog_song_id':int(song.get('id') or 0),
    }
def playlist_relevance_for_song(song, playlist, saved_targets):
    song_id=int(song.get('id') or 0)
    playlist_url=playlist.get('url') or playlist.get('playlist_url') or ''
    target=saved_targets.get((song_id,playlist_url),{})
    target_score=float(target.get('fit_score') or 0)
    seed_match_count=int(playlist.get('seed_match_count') or target.get('seed_match_count') or 0)
    best_seed_rank=int(playlist.get('best_seed_rank') or target.get('best_seed_rank') or 0)
    song_terms=terms_from_text(song.get('title'),song.get('artist_name'),song.get('genre_tags'),song.get('mood_tags'),song.get('instrumentation'),song.get('vocal_style'),song.get('notes'))
    playlist_terms=terms_from_text(
        playlist.get('name'),
        playlist.get('playlist_name'),
        playlist.get('curator_name'),
        playlist.get('related_artists'),
        playlist.get('spotify_description'),
        playlist.get('query'),
        playlist.get('matched_terms'),
        playlist.get('best_song_titles'),
        playlist.get('fit_reason'),
    )
    overlap=len(song_terms & playlist_terms)
    overlap_score=min(35,overlap*7)
    base_score=max(float(playlist.get('final_score') or 0),float(playlist.get('fit_score') or 0))*0.45
    target_component=target_score*0.45 if target_score else 0
    seed_overlap_bonus=min(28,max(0,seed_match_count-1)*14)
    seed_rank_bonus=max(0,12-best_seed_rank) if best_seed_rank else 0
    contact_bonus=8 if playlist.get('email') else 7 if playlist.get('instagram') else 6 if playlist.get('submission_page') else 0
    relevance=min(100,base_score+target_component+overlap_score+seed_overlap_bonus+seed_rank_bonus+contact_bonus)
    reasons=[]
    if target_score:
        reasons.append(f"song fit {target_score:.0f}")
    if seed_match_count:
        seed_text='seed artist' if seed_match_count==1 else 'seed artists'
        reasons.append(f"{seed_match_count} Cyanite {seed_text}")
    if best_seed_rank:
        reasons.append(f"best seed rank {best_seed_rank}")
    if overlap:
        reasons.append(f"{overlap} matching tag/artist term(s)")
    if playlist.get('source') in {'viberate','chartmetric'}:
        reasons.append(f"{playlist.get('source')} mined fit {float(playlist.get('fit_score') or 0):.0f}")
    if contact_bonus:
        reasons.append('contact available')
    return round(relevance,2), '; '.join(reasons) or 'ranked by saved playlist rating'
def target_playlist_candidate(target, saved_playlist=None):
    saved_playlist=saved_playlist or {}
    follower_count=int(saved_playlist.get('followers') or saved_playlist.get('follower_count') or target.get('follower_count') or 0)
    source=target.get('source') or saved_playlist.get('source') or 'song_target'
    return {
        **saved_playlist,
        'id':int(saved_playlist.get('id') or 0),
        'playlist_id':int(saved_playlist.get('id') or 0),
        'song_target_id':int(target.get('id') or 0),
        'name':saved_playlist.get('name') or target.get('playlist_name') or '',
        'playlist_name':saved_playlist.get('playlist_name') or saved_playlist.get('name') or target.get('playlist_name') or '',
        'url':saved_playlist.get('url') or target.get('playlist_url') or '',
        'playlist_url':saved_playlist.get('playlist_url') or saved_playlist.get('url') or target.get('playlist_url') or '',
        'curator_name':saved_playlist.get('curator_name') or target.get('curator_name') or '',
        'followers':follower_count,
        'follower_count':follower_count,
        'spotify_description':saved_playlist.get('spotify_description') or '',
        'final_score':float(saved_playlist.get('final_score') or target.get('fit_score') or 0),
        'fit_score':float(target.get('fit_score') or saved_playlist.get('fit_score') or saved_playlist.get('final_score') or 0),
        'related_artists':target.get('cyanite_seed_artists') or target.get('related_artists') or saved_playlist.get('related_artists') or '',
        'source':source,
        'status':saved_playlist.get('status') or target.get('status') or 'target',
        'seed_match_count':int(target.get('seed_match_count') or 0),
        'cyanite_seed_artists':target.get('cyanite_seed_artists') or '',
        'best_seed_rank':int(target.get('best_seed_rank') or 0),
        'notes':target.get('notes') or '',
    }
def mined_playlist_candidate(row):
    return {
        'id':0,
        'playlist_id':0,
        'mined_playlist_id':int(row.get('id') or 0),
        'name':row.get('playlist_name') or '',
        'playlist_name':row.get('playlist_name') or '',
        'url':row.get('playlist_url') or '',
        'playlist_url':row.get('playlist_url') or '',
        'curator_name':row.get('curator_name') or '',
        'followers':int(row.get('follower_count') or 0),
        'follower_count':int(row.get('follower_count') or 0),
        'spotify_description':row.get('spotify_description') or '',
        'final_score':float(row.get('fit_score') or 0),
        'fit_score':float(row.get('fit_score') or 0),
        'fit_reason':row.get('fit_reason') or '',
        'query':row.get('query') or '',
        'matched_terms':row.get('matched_terms') or '',
        'best_song_titles':row.get('best_song_titles') or '',
        'source':row.get('source') or 'mined',
        'status':row.get('status') or 'mined',
    }
def build_song_target_candidates(selected_songs, saved_playlists, targets, limit=100, mined_playlists=None):
    saved_targets={}
    target_urls_by_song={}
    title_lookup={(str(song.get('title') or '').strip().lower(),str(song.get('artist_name') or '').strip().lower()):int(song.get('id') or 0) for song in selected_songs}
    for target in targets or []:
        url=target.get('playlist_url') or ''
        song_id=int(target.get('song_id') or 0)
        if not song_id:
            song_id=title_lookup.get((str(target.get('song_title') or '').strip().lower(),str(target.get('artist_name') or '').strip().lower()),0)
        if song_id and url:
            saved_targets[(song_id,url)]=target
            target_urls_by_song.setdefault(song_id,set()).add(url)
    playlists_by_url={row.get('url') or row.get('playlist_url') or '':{**row,'source':row.get('source') or 'saved'} for row in saved_playlists}
    mined_candidates=[mined_playlist_candidate(row) for row in (mined_playlists or [])]
    rows=[]
    for song in selected_songs:
        song_id=int(song.get('id') or 0)
        song_context=song_context_from_catalog_song(song)
        target_urls=target_urls_by_song.get(song_id,set())
        playlist_pool=[]
        if target_urls:
            for url in target_urls:
                target=saved_targets.get((song_id,url),{})
                playlist_pool.append(target_playlist_candidate(target,playlists_by_url.get(url)))
        else:
            playlist_pool=list(playlists_by_url.values())
        seen_urls={playlist.get('url') or playlist.get('playlist_url') or '' for playlist in playlist_pool}
        combined_pool=list(playlist_pool)+[playlist for playlist in mined_candidates if (playlist.get('playlist_url') or playlist.get('url') or '') not in seen_urls]
        for playlist in combined_pool:
            relevance,reason=playlist_relevance_for_song(song,playlist,saved_targets)
            is_saved_target=bool(saved_targets.get((song_id,playlist.get('url') or playlist.get('playlist_url') or '')))
            row={
                **playlist,
                'select':is_saved_target or (playlist.get('source') not in {'viberate','chartmetric'} and relevance>=55),
                'playlist_id':int(playlist.get('id') or 0),
                'playlist_name':playlist.get('name') or playlist.get('playlist_name') or '',
                'playlist_url':playlist.get('url') or playlist.get('playlist_url') or '',
                'selected_song':song_context.get('title',''),
                'artist':song_context.get('artist',''),
                'song_context':song_context,
                'relevance_score':max(relevance,float(saved_targets.get((song_id,playlist.get('url') or playlist.get('playlist_url') or ''),{}).get('fit_score') or 0)),
                'final_score':max(relevance,float(saved_targets.get((song_id,playlist.get('url') or playlist.get('playlist_url') or ''),{}).get('fit_score') or 0)),
                'reason':reason,
            }
            rows.append(row)
    return sorted(rows,key=lambda item:(-float(item.get('relevance_score') or 0),item.get('playlist_name','')))[:int(limit or 100)]
def run_contact_enrichment_api(playlists):
    tavily_key=os.getenv('TAVILY_API_KEY','').strip()
    if tavily_key:
        batch=enrich_playlists_with_tavily(playlists,tavily_key)
        saved=0
        for row,result in zip(playlists,batch.get('results') or []):
            curator_id=int(row.get('curator_id') or 0)
            if not curator_id:
                continue
            for contact_method in result.get('contact_methods') or []:
                upsert_contact_method(curator_id,contact_method)
                saved+=1
        errors=batch.get('errors') or []
        return {
            'ok':not errors or saved>0,
            'error':'; '.join(dict.fromkeys(errors)),
            'saved':saved,
            'credits':batch.get('credits',0),
            'provider':'Tavily',
        }
    api_url=os.getenv('CONTACT_ENRICHMENT_API_URL','').strip()
    if not api_url:
        return {'ok':False,'error':'Set TAVILY_API_KEY to enable Tavily contact enrichment.','saved':0}
    payload={
        'playlists':[
            {
                'playlist_id':row.get('id'),
                'playlist_name':row.get('name') or row.get('playlist_name',''),
                'playlist_url':row.get('url') or row.get('playlist_url',''),
                'curator_id':row.get('curator_id'),
                'curator_name':row.get('curator_name',''),
                'spotify_description':row.get('spotify_description',''),
                'existing_contacts':{
                    'email':row.get('email',''),
                    'instagram':row.get('instagram',''),
                    'submission_page':row.get('submission_page',''),
                    'website':row.get('website',''),
                    'link_hub':row.get('link_hub',''),
                },
            }
            for row in playlists
        ]
    }
    try:
        resp=requests.post(api_url,json=payload,timeout=45)
        resp.raise_for_status()
        data=resp.json()
    except Exception as exc:
        return {'ok':False,'error':str(exc),'saved':0}
    contacts=data.get('contacts') if isinstance(data,dict) else []
    by_url={(row.get('url') or row.get('playlist_url') or ''):row for row in playlists}
    saved=0
    for contact in contacts or []:
        playlist_url=contact.get('playlist_url','')
        base=by_url.get(playlist_url) or {}
        curator_id=int(contact.get('curator_id') or base.get('curator_id') or 0)
        if not curator_id:
            continue
        source=contact.get('source_url') or contact.get('evidence_url') or api_url
        confidence=int(contact.get('confidence_score') or contact.get('confidence') or 70)
        for contact_type,key in [('email','email'),('instagram','instagram'),('submission_page','submission_page'),('website','website'),('link_hub','link_hub')]:
            value=(contact.get(key) or '').strip()
            if value:
                upsert_contact_method(curator_id,{'type':contact_type,'value':value,'source_url':source,'confidence_score':confidence,'status':'new'})
                saved+=1
    return {'ok':True,'error':'','saved':saved,'raw':data}
def saved_cyanite_analysis_for_upload(uploaded_file, fallback_title=''):
    if not uploaded_file:
        return {}
    file_name=clean_filename(getattr(uploaded_file,'name','') or '')
    title=fallback_title or file_name.rsplit('.',1)[0].replace('_',' ').replace('-',' ').title()
    for row in get_release_songs():
        same_file=file_name and row.get('file_name')==file_name
        same_title=title and str(row.get('title') or '').strip().lower()==title.strip().lower()
        if not (same_file or same_title):
            continue
        if row.get('analysis_source')!='cyanite' and row.get('source')!='cyanite':
            continue
        raw={}
        try:
            raw=json.loads(row.get('raw_analysis_json') or '{}')
        except json.JSONDecodeError:
            raw={}
        return {
            'ok':True,
            'status':'finished',
            'source':'saved_cyanite_profile',
            'library_track_id':raw.get('library_track_id','') if isinstance(raw,dict) else '',
            'title':row.get('title') or title,
            'genres':[x.strip() for x in str(row.get('genre_tags') or '').split(';') if x.strip()],
            'moods':[x.strip() for x in str(row.get('mood_tags') or '').split(';') if x.strip()],
            'instruments':[x.strip() for x in str(row.get('instrumentation') or '').split(';') if x.strip()],
            'voice':row.get('vocal_style',''),
            'movement':raw.get('movement','') if isinstance(raw,dict) else '',
            'energy':row.get('energy',''),
            'bpm':row.get('bpm',''),
            'caption':row.get('notes',''),
            'descriptors':'; '.join([x for x in [row.get('genre_tags',''),row.get('mood_tags',''),row.get('instrumentation',''),row.get('vocal_style',''),row.get('notes','')] if x]),
            'raw':raw or row,
        }
    return {}
def clear_campaign_copy_state():
    for key in list(st.session_state.keys()):
        if str(key).startswith(('campaign_email_','campaign_dm_','campaign_submission_')):
            del st.session_state[key]
def campaign_status_mark(row, channel):
    if channel=='Instagram':
        return '✓' if row.get('instagram_opened') or row.get('instagram_dm_pasted') else ''
    if channel=='Email':
        return '✓' if row.get('email_drafted') else ''
    if channel in {'Submission','Website'}:
        return '✓' if row.get('submission_sent') else ''
    return ''
def campaign_channel_rows(rows, channel):
    if channel=='Instagram':
        return [row for row in rows if row.get('instagram') and row.get('status')!='Wait']
    if channel=='Email':
        return [row for row in rows if row.get('email') and row.get('status')!='Wait']
    if channel=='Submission':
        return [row for row in rows if row.get('submission_page') and row.get('status')!='Wait']
    if channel=='Research':
        return [row for row in rows if row.get('status')=='Wait' or not (row.get('instagram') or row.get('email') or row.get('submission_page'))]
    return []
def campaign_queue_table(rows, channel):
    return pd.DataFrame([
        {
            'send':row.get('send',False) and row.get('recommended_channel')==channel,
            'done':campaign_status_mark(row,channel),
            'playlist_name':row.get('playlist_name',''),
            'fit_score':row.get('fit_score',0),
            'status':row.get('status',''),
            'contact':row.get('instagram') if channel=='Instagram' else row.get('email') if channel=='Email' else row.get('submission_page') if channel=='Submission' else row.get('website',''),
            'reason':row.get('reason',''),
        }
        for row in rows
    ])
def selected_campaign_row(rows, channel):
    if not rows:
        return None,0
    labels=[f"{campaign_status_mark(row,channel) or '○'} {i+1}. {row.get('playlist_name') or 'playlist'} · {row.get('fit_score')} · {row.get('status')}" for i,row in enumerate(rows)]
    selected=st.selectbox('Review one target',labels,key=f'campaign_{channel.lower()}_selector')
    idx=labels.index(selected) if selected in labels else 0
    return rows[idx],idx

@st.fragment(run_every=3)
def render_campaign_target_sheet(campaign_id):
    st.markdown('#### Targeted Playlists')
    target_rows=get_outreach_campaign_targets(campaign_id)
    sent_playlist_ids={
        int(row.get('playlist_id') or 0)
        for row in get_email_queue('sent')
        if int(row.get('campaign_id') or 0)==int(campaign_id)
    }
    if not target_rows:
        st.info('This campaign predates the target spreadsheet. Prepare it again to save its playlist target list.')
        return
    sheet=[]
    original_instagram_done={}
    for target in target_rows:
        playlist_id=int(target.get('playlist_id') or 0)
        email_done=playlist_id in sent_playlist_ids or target.get('email_status')=='done'
        instagram_done=target.get('instagram_status')=='done'
        submission_done=target.get('submission_status')=='done'
        original_instagram_done[playlist_id]=instagram_done
        sheet.append({
            'playlist_id':playlist_id,
            'curator_id':int(target.get('curator_id') or 0),
            'playlist_name':target.get('playlist_name',''),
            'fit_score':target.get('fit_score',0),
            'email_check':'✅' if email_done else ('—' if not target.get('email') else ''),
            'email':target.get('email',''),
            'instagram_dm_done':instagram_done,
            'instagram_action':instagram_dm_url(target.get('instagram')) if target.get('instagram') else '',
            'submission_check':'✅' if submission_done else ('—' if not target.get('submission_page') else ''),
            'submission_action':target.get('submission_page','') if target.get('submission_page') else '',
            'playlist_url':target.get('playlist_url',''),
        })
    edited_sheet=st.data_editor(
        pd.DataFrame(sheet),
        use_container_width=True,
        hide_index=True,
        disabled=['playlist_name','fit_score','email_check','email','instagram_action','submission_check','submission_action','playlist_url'],
        column_order=['instagram_dm_done','playlist_name','fit_score','email_check','email','instagram_action','submission_check','submission_action','playlist_url'],
        key=f'campaign_target_sheet_{campaign_id}',
        column_config={
            'playlist_id':None,
            'curator_id':None,
            'playlist_name':st.column_config.TextColumn('Playlist'),
            'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
            'email_check':st.column_config.TextColumn('Email ✓',width='small'),
            'email':st.column_config.TextColumn('Curator Email'),
            'instagram_dm_done':st.column_config.CheckboxColumn("IG DM'd",width='small',help="Check this after you pasted or sent the Instagram DM."),
            'instagram_action':st.column_config.LinkColumn('Instagram',display_text='Open DM'),
            'submission_check':st.column_config.TextColumn('Submit ✓',width='small'),
            'submission_action':st.column_config.LinkColumn('Submission',display_text='Open'),
            'playlist_url':st.column_config.LinkColumn('Spotify',display_text='Open'),
        },
    )
    changed=False
    for row in edited_sheet.to_dict('records'):
        playlist_id=int(row.get('playlist_id') or 0)
        if not playlist_id:
            continue
        new_done=bool(row.get('instagram_dm_done'))
        old_done=bool(original_instagram_done.get(playlist_id))
        if new_done==old_done:
            continue
        update_outreach_campaign_target_status(campaign_id,playlist_id,'instagram','done' if new_done else 'pending')
        if new_done:
            add_outreach_event(int(row.get('curator_id') or 0),playlist_id,'instagram','manual_dm_pasted','Marked complete from targeted playlist sheet.',campaign_id=campaign_id)
        changed=True
    if changed:
        st.toast('Instagram DM status updated.')
        st.rerun()
    st.caption("Email checks turn green after a successful send. Check IG DM'd when you paste/send the Instagram DM; submission checks turn green when their tracked link is opened.")

def song_campaign_task_counts(tasks):
    counts={}
    for channel in ['email','instagram','submission']:
        rows=[task for task in tasks if task.get('channel')==channel]
        counts[channel]={'total':len(rows),'completed':sum(1 for task in rows if task.get('task_status')=='completed')}
    total=len(tasks)
    completed=sum(1 for task in tasks if task.get('task_status')=='completed')
    return counts,total,completed

def song_campaign_status(total,completed):
    if total==0 or completed==0:
        return 'Campaign Not Started','🔴'
    if completed>=total:
        return 'Campaign Finished','✅'
    return 'Campaign In Progress','🟡'

def campaign_song_context(song):
    return {
        'title':song.get('title') or song.get('file_name') or '',
        'song_title':song.get('title') or song.get('file_name') or '',
        'artist_name':song.get('artist_name') or '',
        'artist':song.get('artist_name') or '',
        'spotify_url':song.get('spotify_url') or '',
        'song_url':song.get('spotify_url') or '',
    }

def default_instagram_dm(task,song):
    return f"Hi, I found your playlist, {task.get('playlist_name') or 'your playlist'}, and thought this song might be a good fit.\n\nSpotify:\n{song.get('spotify_url') or ''}\n\nThanks for checking it out."

def default_submission_note(task,song):
    title=song.get('title') or song.get('file_name') or 'this song'
    artist=song.get('artist_name') or 'Strange Hotels'
    return f"Submitting {title} by {artist} for {task.get('playlist_name') or 'your playlist'}.\n\nSpotify: {song.get('spotify_url') or ''}"

def song_campaign_playlist_funnel(song_id):
    with database_module.connect(DB_PATH) as conn:
        rows=[dict(row) for row in conn.execute("""SELECT spt.song_id,spt.playlist_url,
                  COALESCE(NULLIF(spt.playlist_name,''),p.name) AS playlist_name,
                  COALESCE(spt.fit_score,0) AS fit_score,
                  spt.source,p.id AS playlist_id,p.followers,c.display_name AS curator_name,c.name AS curator_key,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='email' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS email,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='instagram' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS instagram,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='submission_page' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS submission_page,
                  EXISTS (SELECT 1 FROM campaign_outreach_tasks t WHERE t.song_id=spt.song_id AND t.playlist_id=p.id) AS active_campaign_task
           FROM song_playlist_targets spt
           LEFT JOIN playlists p ON p.url=spt.playlist_url
           LEFT JOIN curators c ON c.id=p.curator_id
           WHERE spt.song_id=?
           ORDER BY COALESCE(spt.fit_score,0) DESC,playlist_name""",(int(song_id or 0),)).fetchall()]
    for row in rows:
        curator_key=str(row.get('curator_key') or '').strip().lower()
        row['known_curator']=bool(curator_key and curator_key not in {'unknown curator','spotify'})
        row['has_contact']=bool(row.get('email') or row.get('instagram') or row.get('submission_page'))
        row['contactable_high_fit']=bool(float(row.get('fit_score') or 0)>=70 and row['known_curator'] and row['has_contact'])
    summary={
        'matched':len({row.get('playlist_url') for row in rows if row.get('playlist_url')}),
        'high_fit':len({row.get('playlist_url') for row in rows if row.get('playlist_url') and float(row.get('fit_score') or 0)>=70}),
        'contactable_high_fit':len({row.get('playlist_url') for row in rows if row.get('playlist_url') and row.get('contactable_high_fit')}),
        'active_campaign_playlists':len({row.get('playlist_id') for row in rows if row.get('active_campaign_task') and row.get('playlist_id')}),
    }
    return summary,rows

def render_song_campaign_workspace(song):
    song_id=int(song.get('id') or 0)
    sync_song_campaign_tasks(song_id,min_fit=70)
    tasks=get_song_campaign_tasks(song_id)
    funnel,playlist_match_rows=song_campaign_playlist_funnel(song_id)
    counts,total_tasks,completed_tasks=song_campaign_task_counts(tasks)
    status_label,status_icon=song_campaign_status(total_tasks,completed_tasks)
    completion_pct=round((completed_tasks/total_tasks)*100,1) if total_tasks else 0
    st.markdown('#### Song Campaign Workspace')
    top1,top2=st.columns([3,1])
    with top1:
        st.markdown(f"### {status_icon} {song.get('title') or song.get('file_name') or 'Untitled'}")
        if song.get('artist_name'):
            st.caption(song.get('artist_name'))
        if song.get('spotify_url'):
            st.link_button('Open Spotify Track',song.get('spotify_url'),use_container_width=False)
        else:
            st.warning('No Spotify song link is saved for this catalog song yet.')
    with top2:
        st.metric('Completion',f"{completion_pct:.0f}%",f"{completed_tasks} of {total_tasks} tasks")
        st.caption(status_label)
    m1,m2,m3=st.columns(3)
    m1.metric('Emails',f"{counts['email']['completed']} of {counts['email']['total']} sent")
    m2.metric('Instagram',f"{counts['instagram']['completed']} of {counts['instagram']['total']} attempted")
    m3.metric('Submission Sites',f"{counts['submission']['completed']} of {counts['submission']['total']} submitted")
    f1,f2,f3,f4=st.columns(4)
    f1.metric('Matched Playlists',funnel.get('matched',0))
    f2.metric('High-Fit Playlists',funnel.get('high_fit',0))
    f3.metric('Contactable High-Fit',funnel.get('contactable_high_fit',0))
    f4.metric('First-Round Active',funnel.get('active_campaign_playlists',0))
    email_tasks=[task for task in tasks if task.get('channel')=='email']
    instagram_tasks=[task for task in tasks if task.get('channel')=='instagram']
    submission_tasks=[task for task in tasks if task.get('channel')=='submission']
    tab_email,tab_instagram,tab_submission,tab_matches,tab_results=st.tabs(['Email','Instagram','Submission Sites','Playlist Matches','Results'])
    with tab_email:
        st.caption('Each email address is its own task. Completing email does not complete Instagram or submission work for the same playlist.')
        active_email_routes={str(task.get('contact_destination') or '').strip().lower() for task in email_tasks}
        active_email_playlist_ids={int(task.get('playlist_id') or 0) for task in email_tasks}
        held_email_rows=[]
        for row in playlist_match_rows:
            email=str(row.get('email') or '').strip()
            if not email:
                continue
            playlist_id=int(row.get('playlist_id') or 0)
            route=email.lower()
            reason='Held from round one'
            if float(row.get('fit_score') or 0)<70:
                reason='Below high-fit threshold'
            elif not row.get('known_curator'):
                reason='Unknown or platform curator'
            elif playlist_id in active_email_playlist_ids:
                reason='Active email task'
            elif route in active_email_routes:
                reason='Same email as another stronger active playlist'
            held_email_rows.append({
                'active':'✓' if reason=='Active email task' else '',
                'playlist_name':row.get('playlist_name') or '',
                'email':email,
                'fit_score':float(row.get('fit_score') or 0),
                'reason':reason,
                'playlist_url':row.get('playlist_url') or '',
            })
        email_route_rows=[]
        if held_email_rows:
            route_groups={}
            for item in held_email_rows:
                route=str(item.get('email') or '').strip().lower()
                if not route:
                    continue
                route_groups.setdefault(route,[]).append(item)
            for route,items in route_groups.items():
                ordered=sorted(items,key=lambda item:(item.get('active')!='✓',-float(item.get('fit_score') or 0),str(item.get('playlist_name') or '').lower()))
                primary=ordered[0]
                reason=primary.get('reason') or 'Held from round one'
                if any(item.get('active')=='✓' for item in items):
                    reason='Active email route; alternates held'
                alternates=[item.get('playlist_name') or '' for item in ordered[1:7] if item.get('playlist_name')]
                email_route_rows.append({
                    'active':'✓' if any(item.get('active')=='✓' for item in items) else '',
                    'email':primary.get('email') or route,
                    'best_playlist':primary.get('playlist_name') or '',
                    'fit_score':float(primary.get('fit_score') or 0),
                    'playlist_count':len(items),
                    'reason':reason,
                    'alternates':' | '.join(alternates),
                    'playlist_url':primary.get('playlist_url') or '',
                })
        held_email_df=pd.DataFrame(email_route_rows).sort_values(['active','fit_score','email'],ascending=[False,False,True]) if email_route_rows else pd.DataFrame()
        if not email_tasks:
            st.info('No email tasks are available for this song.')
        else:
            st.dataframe(pd.DataFrame([{'done':'✓' if task.get('task_status')=='completed' else '','playlist_name':task.get('playlist_name',''),'email':task.get('contact_destination',''),'status':task.get('task_status','pending'),'outcome':task.get('outcome_status','pending'),'attempted_at':task.get('attempted_at',''),'reply':'yes' if task.get('has_email_reply') else ''} for task in email_tasks]),use_container_width=True,hide_index=True)
            if not held_email_df.empty:
                st.markdown(f"##### Email Routes ({len(held_email_df)} unique addresses, {len(held_email_rows)} playlist candidates)")
                st.caption('Grouped by email address. One inbox can control many playlists, so Streambase keeps one active first-round route and shows the rest as alternates.')
                st.dataframe(
                    held_email_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'active':st.column_config.TextColumn('Active',width='small'),
                        'email':st.column_config.TextColumn('Email'),
                        'best_playlist':st.column_config.TextColumn('Best Playlist'),
                        'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                        'playlist_count':st.column_config.NumberColumn('Playlists',format='%d'),
                        'alternates':st.column_config.TextColumn('Alternates'),
                        'playlist_url':st.column_config.LinkColumn('Spotify',display_text='Open'),
                    },
                )
            labels=[f"{'✓ ' if task.get('task_status')=='completed' else ''}{i+1}. {task.get('playlist_name')} · {task.get('contact_destination')}" for i,task in enumerate(email_tasks)]
            task=email_tasks[labels.index(st.selectbox('Review email task',labels,key=f'song_campaign_email_task_{song_id}'))]
            ctx=campaign_song_context(song)
            subject_template=st.text_input('Subject',value=DEFAULT_CAMPAIGN_SUBJECT,key=f'song_email_subject_{task.get("id")}')
            body_template=st.text_area('Email draft',value=DEFAULT_CAMPAIGN_BODY,height=220,key=f'song_email_body_{task.get("id")}')
            subject=render_campaign_template(subject_template,task.get('playlist_name'),ctx)
            body=render_campaign_template(body_template,task.get('playlist_name'),ctx)
            st.text_input('Preview subject',value=subject,disabled=True,key=f'song_email_subject_preview_{task.get("id")}')
            st.text_area('Preview email',value=body,height=180,disabled=True,key=f'song_email_body_preview_{task.get("id")}')
            already_done=task.get('task_status')=='completed'
            allow_resend=st.checkbox('Allow intentional resend for this completed email task',key=f'allow_resend_{task.get("id")}',disabled=not already_done)
            e1,e2,e3=st.columns(3)
            with e1:
                if st.button('Queue Draft',use_container_width=True,key=f'queue_song_email_{task.get("id")}',disabled=already_done and not allow_resend):
                    queue_id=queue_email(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),task.get('contact_destination',''),subject,body,song_context=ctx,campaign_id=int(task.get('campaign_id') or 0),enforce_cooldown=False)
                    if queue_id:
                        update_email_queue_status(queue_id,'approved')
                        update_campaign_outreach_task(int(task.get('id')),task_status='pending',outcome_status='pending',notes=body,email_queue_id=queue_id)
                        add_outreach_event(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),'email','drafted',body,campaign_id=int(task.get('campaign_id') or 0))
                        st.rerun()
                    else:
                        st.error('Email draft could not be queued.')
            with e2:
                sender=email_sender_status()
                if st.button('Send Now',type='primary',use_container_width=True,key=f'send_song_email_{task.get("id")}',disabled=(already_done and not allow_resend) or not sender.get('configured')):
                    result=send_email_via_resend(task.get('contact_destination',''),subject,body)
                    if result.get('ok'):
                        queue_id=queue_email(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),task.get('contact_destination',''),subject,body,song_context=ctx,campaign_id=int(task.get('campaign_id') or 0),enforce_cooldown=False)
                        if queue_id:
                            update_email_queue_after_send(queue_id,'sent',provider_id=result.get('provider_id',''))
                        update_campaign_outreach_task(int(task.get('id')),task_status='completed',outcome_status='pending',attempted=True,notes=body,email_queue_id=queue_id or int(task.get('email_queue_id') or 0))
                        add_outreach_event(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),'email','sent',body,campaign_id=int(task.get('campaign_id') or 0))
                        st.rerun()
                    else:
                        st.error(result.get('error') or 'Email send failed.')
            with e3:
                if st.button('Mark Sent',use_container_width=True,key=f'mark_song_email_{task.get("id")}',disabled=already_done and not allow_resend):
                    update_campaign_outreach_task(int(task.get('id')),task_status='completed',outcome_status='pending',attempted=True,notes=body)
                    add_outreach_event(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),'email','manual_email_sent',body,campaign_id=int(task.get('campaign_id') or 0))
                    st.rerun()
    with tab_instagram:
        if not instagram_tasks:
            st.info('No Instagram tasks are available for this song.')
        else:
            st.dataframe(pd.DataFrame([{'done':'✓' if task.get('task_status')=='completed' else '','playlist_name':task.get('playlist_name',''),'instagram':task.get('contact_destination',''),'status':task.get('task_status','pending'),'attempted_at':task.get('attempted_at','')} for task in instagram_tasks]),use_container_width=True,hide_index=True)
            labels=[f"{'✓ ' if task.get('task_status')=='completed' else ''}{i+1}. {task.get('playlist_name')} · {task.get('contact_destination')}" for i,task in enumerate(instagram_tasks)]
            task=instagram_tasks[labels.index(st.selectbox('Review Instagram task',labels,key=f'song_campaign_ig_task_{song_id}'))]
            dm=st.text_area('Instagram DM draft',value=task.get('notes') or default_instagram_dm(task,song),height=160,key=f'song_ig_dm_{task.get("id")}')
            i1,i2,i3=st.columns(3)
            with i1:
                st.link_button('Open Instagram',instagram_dm_url(task.get('contact_destination')),use_container_width=True)
            with i2:
                copy_button('Copy DM',dm,f'song-ig-copy-{task.get("id")}')
            with i3:
                if st.button('Mark Attempted',type='primary',use_container_width=True,key=f'mark_song_ig_{task.get("id")}'):
                    update_campaign_outreach_task(int(task.get('id')),task_status='completed',outcome_status='pending',attempted=True,notes=dm)
                    add_outreach_event(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),'instagram','manual_dm_pasted',dm,campaign_id=int(task.get('campaign_id') or 0))
                    st.rerun()
    with tab_submission:
        if not submission_tasks:
            st.info('No submission-site tasks are available for this song.')
        else:
            st.dataframe(pd.DataFrame([{'done':'✓' if task.get('task_status')=='completed' else '','playlist_name':task.get('playlist_name',''),'submission_site':task.get('contact_destination',''),'status':task.get('task_status','pending'),'attempted_at':task.get('attempted_at','')} for task in submission_tasks]),use_container_width=True,hide_index=True)
            labels=[f"{'✓ ' if task.get('task_status')=='completed' else ''}{i+1}. {task.get('playlist_name')} · {task.get('contact_destination')}" for i,task in enumerate(submission_tasks)]
            task=submission_tasks[labels.index(st.selectbox('Review submission task',labels,key=f'song_campaign_submission_task_{song_id}'))]
            note=st.text_area('Submission notes',value=task.get('notes') or default_submission_note(task,song),height=150,key=f'song_submission_note_{task.get("id")}')
            s1,s2,s3=st.columns(3)
            with s1:
                st.link_button('Open Submission Site',task.get('contact_destination'),use_container_width=True)
            with s2:
                copy_button('Copy Notes',note,f'song-submission-copy-{task.get("id")}')
            with s3:
                if st.button('Mark Submitted',type='primary',use_container_width=True,key=f'mark_song_submission_{task.get("id")}'):
                    update_campaign_outreach_task(int(task.get('id')),task_status='completed',outcome_status='pending',attempted=True,notes=note)
                    add_outreach_event(int(task.get('curator_id') or 0),int(task.get('playlist_id') or 0),'submission','manual_submission_sent',note,campaign_id=int(task.get('campaign_id') or 0))
                    st.rerun()
    with tab_matches:
        if playlist_match_rows:
            match_df=pd.DataFrame([
                {
                    'active':'✓' if row.get('active_campaign_task') else '',
                    'playlist_name':row.get('playlist_name') or '',
                    'fit_score':float(row.get('fit_score') or 0),
                    'curator':row.get('curator_name') or '',
                    'email':'✓' if row.get('email') else '',
                    'instagram':'✓' if row.get('instagram') else '',
                    'submission':'✓' if row.get('submission_page') else '',
                    'source':row.get('source') or '',
                    'playlist_url':row.get('playlist_url') or '',
                }
                for row in playlist_match_rows
            ])
            st.dataframe(
                match_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    'active':st.column_config.TextColumn('Round 1',width='small'),
                    'playlist_name':st.column_config.TextColumn('Playlist'),
                    'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                    'playlist_url':st.column_config.LinkColumn('Spotify',display_text='Open'),
                },
            )
        else:
            st.info('No playlist matches are saved for this song yet.')
    with tab_results:
        completed=completed_tasks
        remaining=max(0,total_tasks-completed)
        email_replies=sum(1 for task in tasks if task.get('has_email_reply'))
        added=sum(1 for task in tasks if task.get('outcome_status')=='added')
        passed=sum(1 for task in tasks if task.get('outcome_status')=='passed')
        replied=sum(1 for task in tasks if task.get('outcome_status')=='replied')+email_replies
        r1,r2,r3,r4=st.columns(4)
        r1.metric('Total Outreach Tasks',total_tasks)
        r2.metric('Completed Tasks',completed)
        r3.metric('Remaining Tasks',remaining)
        r4.metric('Response Rate',f"{((replied/max(1,completed))*100):.0f}%")
        r5,r6,r7,r8=st.columns(4)
        r5.metric('Email Replies',email_replies)
        r6.metric('Playlist Adds',added)
        r7.metric('Passes',passed)
        r8.metric('Playlist-Add Rate',f"{((added/max(1,completed))*100):.0f}%")
        if tasks:
            labels=[f"{task.get('playlist_name')} · {task.get('channel')} · {task.get('contact_destination')}" for task in tasks]
            task=tasks[labels.index(st.selectbox('Update task result',labels,key=f'song_campaign_outcome_task_{song_id}'))]
            statuses=['pending','replied','added','passed','no_response']
            current=task.get('outcome_status') if task.get('outcome_status') in statuses else 'pending'
            outcome=st.selectbox('Result',statuses,index=statuses.index(current),key=f'outcome_{task.get("id")}')
            notes=st.text_area('Result notes',value=task.get('notes') or '',height=100,key=f'outcome_notes_{task.get("id")}')
            if st.button('Save Result',use_container_width=True,key=f'save_outcome_{task.get("id")}'):
                update_campaign_outreach_task(int(task.get('id')),outcome_status=outcome,notes=notes)
                st.rerun()

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

tab_scan,tab_catalog,tab_miner,tab_playlists,tab_song_targets,tab_campaigns=st.tabs(['Scan A Song','Catalog','Playlist Miner','Playlists','Song Targets','Campaigns'])
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
        saved_home_analysis={}
        if home_audio:
            uploaded_home_title=home_audio.name.rsplit('.',1)[0].replace('_',' ').replace('-',' ').title()
            home_title=preferred_catalog_title(uploaded_home_title,'',pitch_meta,'released' if pitch_is_released else 'unreleased')
            saved_home_analysis=saved_cyanite_analysis_for_upload(home_audio,home_title)
            st.write(f"Selected song: {home_audio.name}")
            if saved_home_analysis:
                st.info('Saved Cyanite analysis found for this song. Streambase will reuse it instead of spending another Cyanite scan.')
        render_cyanite_playlist_link_import(st.session_state.home_song_fit or {},spotify.configured,'home_always')
        scan_disabled=not bool(home_audio) or (cy.get('configured')!='yes' and not saved_home_analysis)
        if cy.get('configured')!='yes' and not saved_home_analysis:
            st.warning('Cyanite is not connected. Add CYANITE_API_KEY to scan audio.')
        if st.session_state.home_spotify_playlist_candidates and not st.session_state.home_song_fit:
            st.markdown('#### Imported Playlist Candidates')
            import_df=pd.DataFrame(st.session_state.home_spotify_playlist_candidates)
            import_cols=[c for c in ['candidate_fit_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','playlist_url'] if c in import_df.columns]
            st.dataframe(import_df[import_cols],use_container_width=True,hide_index=True)
            fresh_imports=[c for c in st.session_state.home_spotify_playlist_candidates if not c.get('already_in_crm')]
            if st.button('Stage Candidates in Import Queue',use_container_width=True,key='home_always_stage_candidates'):
                st.session_state.playlists=[candidate_payload(c) for c in fresh_imports]
                st.success(f"Staged {len(st.session_state.playlists)} candidate(s) in Playlists.")
        scan_label='Load Saved Cyanite Scan' if saved_home_analysis else 'Scan for Genre with Cyanite'
        if st.button(scan_label,type='primary',use_container_width=True,disabled=scan_disabled):
            st.session_state.home_cyanite_upload_result={}
            st.session_state.home_cyanite_analysis_result={}
            st.session_state.home_song_fit=None
            st.session_state.home_playlist_searches=[]
            st.session_state.home_spotify_playlist_candidates=[]
            if saved_home_analysis:
                analysis=saved_home_analysis
                st.session_state.home_cyanite_analysis_result=analysis
                st.session_state.home_song_fit=analyze_song_fit(
                    None,
                    title=preferred_catalog_title(home_title,analysis.get('title',''),pitch_meta,'released' if pitch_is_released else 'unreleased'),
                    artist=pitch_meta.get('artist',''),
                    reference_artists='',
                    descriptors=analysis.get('descriptors',''),
                    saved_playlists=get_all_playlists(),
                    spotify_track=(pitch_meta or {'release_context':'already_released','spotify_url':pitch_track_url}) if pitch_is_released else {'release_context':'new_release'},
                    reference_tracks=[],
                    cyanite_profile=analysis,
                )
                st.session_state.home_playlist_searches=(st.session_state.home_song_fit or {}).get('discovery_searches',[])
                st.success('Loaded saved Cyanite analysis for this song.')
                st.rerun()
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
                                'title':preferred_catalog_title(saved.get('title',''),analysis.get('title',''),pitch_meta,'released' if pitch_is_released else 'unreleased'),
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
                            title=preferred_catalog_title(home_title,analysis.get('title',''),pitch_meta,'released' if pitch_is_released else 'unreleased'),
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
                        title=preferred_catalog_title(home_title,home_analysis.get('title',''),pitch_meta,'released' if pitch_is_released else 'unreleased'),
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
                    cols=[c for c in ['candidate_fit_score','curator_target_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','discovery_intent_hits','submission_ready_hits','curator_identity_hits','passive_context_hits','matched_lanes','matched_descriptors','related_artists','playlist_url'] if c in cand_df.columns]
                    st.dataframe(cand_df[cols],use_container_width=True,hide_index=True)
                    fresh=[c for c in home_candidates if not c.get('already_in_crm')]
                    sc1,sc2=st.columns(2)
                    with sc1:
                        if st.button('Stage Candidates in Import Queue',use_container_width=True,key='home_stage_candidates'):
                            st.session_state.playlists=[
                                candidate_payload(c)
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
                                {**candidate_payload(c),'song_context':song_context}
                                for c in fresh
                            ]
                            if rows:
                                save_raw_json(rows)
                                st.session_state.report=process_playlists(rows,do_web_enrichment=do_web,do_spotify_api=False,queue_email_approval=queue_email_approval,song_context=song_context,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
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
                cols=[c for c in ['candidate_fit_score','curator_target_score','already_in_crm','playlist_name','curator_name','follower_count','search_query','discovery_intent_hits','submission_ready_hits','curator_identity_hits','passive_context_hits','matched_lanes','matched_descriptors','related_artists','playlist_url'] if c in cand_df.columns]
                st.dataframe(cand_df[cols],use_container_width=True,hide_index=True)
                fresh=[c for c in home_candidates if not c.get('already_in_crm')]
                sc1,sc2=st.columns(2)
                with sc1:
                    if st.button('Stage Candidates in Import Queue',use_container_width=True,key='home_stage_candidates'):
                        st.session_state.playlists=[
                            candidate_payload(c)
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
                            {**candidate_payload(c),'song_context':song_context}
                            for c in fresh
                        ]
                        if rows:
                            save_raw_json(rows)
                            st.session_state.report=process_playlists(rows,do_web_enrichment=do_web,do_spotify_api=False,queue_email_approval=queue_email_approval,song_context=song_context,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
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
with tab_miner:
    st.subheader('Playlist Miner')
    st.caption('Mine provider lanes for small curator playlists matched to the released catalog. Default target: Spotify playlists under 1,000 followers.')
    catalog_song_rows=get_release_songs()
    cm_status=chartmetric_status()
    vb_status=viberate_status()
    provider_options={'Viberate':'viberate','Chartmetric':'chartmetric'}
    selected_provider_label=st.selectbox('Mining provider',list(provider_options.keys()),key='miner_provider')
    selected_provider=provider_options[selected_provider_label]
    provider_status=vb_status if selected_provider=='viberate' else cm_status
    follower_col,query_col,result_col=st.columns(3)
    with follower_col:
        follower_max=st.number_input('Max followers',min_value=50,max_value=50000,value=999,step=50,key='miner_follower_max')
    with query_col:
        max_queries=st.number_input('Max queries',min_value=1,max_value=50,value=12,step=1,key='miner_max_queries')
    with result_col:
        limit_per_query=st.number_input('Results per query',min_value=5,max_value=100,value=25,step=5,key='miner_results_per_query')
    dry_run_default=provider_status.get('configured')!='yes'
    dry_run=st.checkbox('Plan only',value=dry_run_default,key='miner_dry_run')
    if catalog_song_rows:
        st.markdown('#### Cyanite Playlist Seeds')
        st.caption('Copy Cyanite playlist matches for one song, then save them as song-specific seed playlists. Spotify enrichment adds the artists from each playlist when available.')
        seed_options={f"{row.get('title') or row.get('file_name') or 'Untitled'} · #{int(row.get('id') or 0)}":row for row in catalog_song_rows}
        selected_seed_label=st.selectbox('Song',list(seed_options.keys()),key='cyanite_seed_song_select')
        selected_seed_song=seed_options.get(selected_seed_label,{})
        raw_seed_text=st.text_area(
            'Cyanite playlist matches',
            height=120,
            placeholder='Paste Cyanite playlist rows, CSV, or Spotify playlist links for the selected song.',
            key='cyanite_seed_playlist_text',
        )
        seed_cols=st.columns([1,1,2])
        with seed_cols[0]:
            preview_seeds=st.button('Preview Seeds',use_container_width=True,key='preview_cyanite_seed_playlists')
        with seed_cols[1]:
            import_seeds=st.button('Import Seeds',type='primary',use_container_width=True,key='import_cyanite_seed_playlists')
        seed_rows=[]
        if preview_seeds or import_seeds:
            with st.spinner('Reading Cyanite playlist seeds...'):
                seed_rows=cyanite_seed_playlists_from_text(raw_seed_text,spotify.configured)
            if seed_rows:
                seed_df=pd.DataFrame(seed_rows)
                for col in ['playlist_name','curator_name','follower_count','related_artists','playlist_url']:
                    if col not in seed_df.columns:
                        seed_df[col]=''
                st.dataframe(
                    seed_df[['playlist_name','curator_name','follower_count','related_artists','playlist_url']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'curator_name':st.column_config.TextColumn('Curator'),
                        'follower_count':st.column_config.NumberColumn('Followers',format='%d'),
                        'related_artists':st.column_config.TextColumn('Playlist Artists'),
                        'playlist_url':st.column_config.LinkColumn('Spotify URL'),
                    },
                )
            else:
                st.info('No Spotify playlist links or playlist rows found in that paste.')
        if import_seeds and seed_rows:
            saved=import_song_seed_playlists(int(selected_seed_song.get('id') or 0),seed_rows,source='cyanite_seed')
            st.success(f"Imported {len(saved)} Cyanite seed playlist(s) for {selected_seed_song.get('title') or selected_seed_song.get('file_name')}.")
        st.divider()
        mining_profile=build_catalog_mining_profile(catalog_song_rows,follower_min=50,follower_max=int(follower_max))
        targets=mining_profile.get('chartmetric_mining_targets',{})
        metric_cols=st.columns(4)
        metric_cols[0].metric('Catalog songs',mining_profile.get('song_count',0))
        metric_cols[1].metric('Genre terms',len(mining_profile.get('core_genre_tags',[])))
        metric_cols[2].metric('Mood terms',len(mining_profile.get('core_mood_tags',[])))
        metric_cols[3].metric('References',len(mining_profile.get('strongest_reference_artists',[])))
        with st.expander('Mining lanes',expanded=False):
            lanes=targets.get('playlist_lanes',[])
            lane_rows=[{'lane':lane.get('name',''), 'terms':'; '.join(lane.get('terms',[]))} for lane in lanes]
            if lane_rows:
                st.dataframe(pd.DataFrame(lane_rows),use_container_width=True,hide_index=True)
            else:
                st.info('Add more Cyanite tags or reference artists to create stronger lanes.')
        can_run=provider_status.get('configured')=='yes' or dry_run
        button_label='Plan Playlist Mining' if dry_run else 'Run Playlist Mining'
        if st.button(button_label,type='primary',disabled=not can_run,key='run_playlist_miner'):
            runner=run_viberate_mining if selected_provider=='viberate' else run_chartmetric_mining
            with st.spinner('Planning playlist lanes...' if dry_run else f'Mining {selected_provider_label} playlists...'):
                st.session_state.chartmetric_mining_result=runner(
                    mining_profile,
                    limit_per_query=int(limit_per_query),
                    max_queries=int(max_queries),
                    dry_run=bool(dry_run),
                )
        if not can_run:
            key_name='VIBERATE_API_KEY' if selected_provider=='viberate' else 'CHARTMETRIC_REFRESH_TOKEN'
            st.warning(f'Add {key_name} to run live mining. You can still plan jobs without the token.')
        result=st.session_state.get('chartmetric_mining_result') or {}
        if result:
            st.success(result.get('message','Playlist mining finished.'))
            if result.get('queries'):
                with st.expander('Queries used',expanded=False):
                    st.dataframe(pd.DataFrame(result.get('queries')),use_container_width=True,hide_index=True)
        jobs=get_mining_jobs()
        if jobs:
            st.markdown('#### Mining Jobs')
            jobs_df=pd.DataFrame(jobs)
            st.dataframe(
                jobs_df[['id','source','profile_name','status','query_count','result_count','created_at','updated_at']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'id':st.column_config.NumberColumn('Job',format='%d'),
                    'source':st.column_config.TextColumn('Source'),
                    'profile_name':st.column_config.TextColumn('Profile'),
                    'status':st.column_config.TextColumn('Status'),
                    'query_count':st.column_config.NumberColumn('Queries',format='%d'),
                    'result_count':st.column_config.NumberColumn('Saved',format='%d'),
                    'created_at':st.column_config.TextColumn('Created'),
                    'updated_at':st.column_config.TextColumn('Updated'),
                },
            )
            latest_job=int(jobs[0].get('id') or 0)
            mined=get_mined_playlists(latest_job)
            st.markdown('#### Latest Mined Playlists')
            if mined:
                mined_df=pd.DataFrame(mined)
                for col in ['playlist_name','curator_name','follower_count','fit_score','follower_tier','fit_reason','query','playlist_url']:
                    if col not in mined_df.columns:
                        mined_df[col]=''
                st.dataframe(
                    mined_df[['playlist_name','curator_name','follower_count','fit_score','follower_tier','fit_reason','query','playlist_url']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'curator_name':st.column_config.TextColumn('Curator'),
                        'follower_count':st.column_config.NumberColumn('Followers',format='%d'),
                        'fit_score':st.column_config.NumberColumn('Fit',format='%.0f'),
                        'follower_tier':st.column_config.TextColumn('Tier'),
                        'fit_reason':st.column_config.TextColumn('Reason'),
                        'query':st.column_config.TextColumn('Query'),
                        'playlist_url':st.column_config.LinkColumn('Spotify URL'),
                    },
                )
            else:
                st.info('The latest mining job has no saved playlists yet.')
        else:
            st.info('No mining jobs yet. Start with a plan, then run live once the Chartmetric token is connected.')
    else:
        st.info('Add songs to the catalog before mining playlists.')
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
                        row=candidate_payload(candidate)
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
                        st.session_state.report=process_playlists(st.session_state.playlists,do_web_enrichment=do_web,do_spotify_api=do_spotify,queue_email_approval=queue_email_approval,playlist_cooldown_days=int(playlist_cooldown_days),minimum_queue_score=int(minimum_queue_score))
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
        for col in ['playlist_name','curator_name','email','email_confidence','instagram','instagram_confidence','submission_page','submission_confidence','website','link_hub','final_score','priority','rating_confidence','rating_evidence','followers','similarity_score','intersection_score','status','playlist_url']:
            if col not in display.columns:
                display[col]=''
        display=display.sort_values('final_score',ascending=False)
        st.markdown('#### Saved Playlists')
        contact_view=st.radio(
            'Contact view',
            ['All saved playlists','Contactable only','Needs contact'],
            horizontal=True,
            key='saved_playlists_contact_view',
        )
        table_display=display
        contact_cols=['email','instagram','submission_page']
        has_contact=display[contact_cols].fillna('').astype(str).apply(lambda row:any(value.strip() for value in row),axis=1)
        if contact_view=='Contactable only':
            table_display=display[
                has_contact
            ].copy()
        elif contact_view=='Needs contact':
            table_display=display[~has_contact].copy()
        st.dataframe(
            table_display[['playlist_name','curator_name','email','instagram','submission_page','final_score','priority','followers','playlist_url','email_confidence','instagram_confidence','submission_confidence','website','link_hub','rating_confidence','rating_evidence','similarity_score','intersection_score','status']],
            use_container_width=True,
            hide_index=True,
            column_config={
                'playlist_name':st.column_config.TextColumn('Playlist'),
                'curator_name':st.column_config.TextColumn('Curator'),
                'email':st.column_config.TextColumn('Email'),
                'instagram':st.column_config.LinkColumn('Instagram'),
                'submission_page':st.column_config.LinkColumn('Submission'),
                'final_score':st.column_config.ProgressColumn('Rating',min_value=0,max_value=100,format='%.0f'),
                'priority':st.column_config.TextColumn('Decision'),
                'followers':st.column_config.NumberColumn('Followers',format='%d'),
                'playlist_url':st.column_config.LinkColumn('Spotify URL'),
                'email_confidence':st.column_config.ProgressColumn('Email Conf.',min_value=0,max_value=100,format='%.0f'),
                'instagram_confidence':st.column_config.ProgressColumn('IG Conf.',min_value=0,max_value=100,format='%.0f'),
                'submission_confidence':st.column_config.ProgressColumn('Submit Conf.',min_value=0,max_value=100,format='%.0f'),
                'website':st.column_config.LinkColumn('Website'),
                'link_hub':st.column_config.LinkColumn('Link Hub'),
                'rating_confidence':st.column_config.ProgressColumn('Confidence',min_value=0,max_value=100,format='%.0f'),
                'rating_evidence':st.column_config.TextColumn('Evidence'),
                'similarity_score':st.column_config.NumberColumn('Similarity',format='%.0f'),
                'intersection_score':st.column_config.NumberColumn('Overlap',format='%.0f'),
                'status':st.column_config.TextColumn('Status'),
            },
        )
        c_download,c_enrich=st.columns(2)
        with c_download:
            st.download_button('Download Playlists CSV',df.to_csv(index=False).encode('utf-8'),'streambase_playlists.csv','text/csv',use_container_width=True)
        with c_enrich:
            if st.button('Enrich Contacts',use_container_width=True,key='saved_playlist_contact_enrich'):
                with st.spinner('Sending saved playlists to contact enrichment API...'):
                    result=run_contact_enrichment_api(rows)
                if result.get('ok'):
                    credit_note=f" using {result.get('credits',0)} Tavily credit(s)" if result.get('provider')=='Tavily' else ''
                    st.success(f"Saved {result.get('saved',0)} enriched contact field(s){credit_note}.")
                    st.rerun()
                else:
                    st.error(result.get('error') or 'Contact enrichment failed.')
    else:
        st.info('No playlists saved yet. Upload a CSV or paste Spotify playlist links above.')
with tab_song_targets:
    st.subheader('Song Targets')
    st.caption('Choose catalog songs, review the most relevant saved playlists, enrich contacts, and start a campaign from selected targets.')
    catalog_rows=get_release_songs()
    saved_rows=get_all_playlists()
    song_fit_rows=get_song_fit_targets()
    mined_rows=sorted(get_mined_playlists(),key=lambda row:float(row.get('fit_score') or 0),reverse=True)[:1000]
    if not catalog_rows:
        st.info('Upload or scan songs first. Catalog songs appear here after Scan A Song saves them.')
    elif not saved_rows and not song_fit_rows:
        st.info('Save playlists or mine song-specific playlist targets first.')
    else:
        song_options=[]
        for song in catalog_rows:
            song_options.append({
                'select':False,
                'id':int(song.get('id') or 0),
                'title':song.get('title') or song.get('file_name') or 'Untitled',
                'artist':song.get('artist_name') or '',
                'genre':next((tag.strip() for tag in str(song.get('genre_tags') or '').split(';') if tag.strip()),''),
                'release':song.get('release_status') or '',
                'spotify_url':song.get('spotify_url') or '',
            })
        st.markdown('#### Catalog Songs')
        song_selection=st.data_editor(
            pd.DataFrame(song_options),
            use_container_width=True,
            hide_index=True,
            key='song_targets_song_selector',
            disabled=['id','title','artist','genre','release','spotify_url'],
            column_config={
                'select':st.column_config.CheckboxColumn('Work With'),
                'id':None,
                'title':st.column_config.TextColumn('Song'),
                'artist':st.column_config.TextColumn('Artist'),
                'genre':st.column_config.TextColumn('Genre'),
                'release':st.column_config.TextColumn('Release'),
                'spotify_url':st.column_config.LinkColumn('Spotify'),
            },
        )
        selected_song_ids=set(song_selection.loc[song_selection['select']==True,'id'].astype(int).tolist()) if not song_selection.empty else set()
        selected_songs=[song for song in catalog_rows if int(song.get('id') or 0) in selected_song_ids]
        target_limit=st.number_input('Playlist targets to show',min_value=10,max_value=250,value=75,step=5,key='song_targets_limit')
        target_rows=build_song_target_candidates(selected_songs,saved_rows,song_fit_rows,target_limit,mined_rows) if selected_songs else []
        if selected_songs:
            st.markdown('#### Relevant Playlist Matches')
            target_df=pd.DataFrame(target_rows)
            if not target_df.empty:
                select_all_targets=st.checkbox('Select all displayed playlist targets',value=False,key='song_targets_select_all')
                if select_all_targets:
                    target_df['select']=True
                visible_cols=['select','selected_song','source','playlist_name','curator_name','email','instagram','submission_page','relevance_score','seed_match_count','cyanite_seed_artists','reason','followers','playlist_url']
                for col in visible_cols:
                    if col not in target_df.columns:
                        target_df[col]=''
                edited_targets=st.data_editor(
                    target_df[visible_cols],
                    use_container_width=True,
                    hide_index=True,
                    key='song_targets_playlist_selector',
                    disabled=[c for c in visible_cols if c!='select'],
                    column_config={
                        'select':st.column_config.CheckboxColumn('Use'),
                        'selected_song':st.column_config.TextColumn('Song'),
                        'source':st.column_config.TextColumn('Source'),
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'curator_name':st.column_config.TextColumn('Curator'),
                        'email':st.column_config.TextColumn('Email'),
                        'instagram':st.column_config.LinkColumn('Instagram'),
                        'submission_page':st.column_config.LinkColumn('Submit'),
                        'relevance_score':st.column_config.ProgressColumn('Relevance',min_value=0,max_value=100,format='%.0f'),
                        'seed_match_count':st.column_config.NumberColumn('Cyanite Hits',format='%d'),
                        'cyanite_seed_artists':st.column_config.TextColumn('Matched Seed Artists'),
                        'reason':st.column_config.TextColumn('Why'),
                        'followers':st.column_config.NumberColumn('Followers',format='%d'),
                        'playlist_url':st.column_config.LinkColumn('Spotify'),
                    },
                )
                selected_indexes=[idx for idx,flag in enumerate(edited_targets['select'].tolist()) if flag]
                selected_targets=[target_rows[idx] for idx in selected_indexes if idx<len(target_rows)]
                selected_saved_targets=[row for row in selected_targets if int(row.get('playlist_id') or 0)]
                selected_mined_targets=[row for row in selected_targets if not int(row.get('playlist_id') or 0)]
                mined_note=f" {len(selected_mined_targets)} mined recommendation(s) need to be saved before outreach." if selected_mined_targets else ''
                st.caption(f"{len(selected_targets)} playlist target(s) selected. {len(selected_saved_targets)} saved playlist(s) ready for enrichment/campaign.{mined_note}")
                c_save,c_enrich,c_campaign=st.columns(3)
                with c_save:
                    if st.button('Save Selected Mined Targets',use_container_width=True,disabled=not selected_mined_targets,key='song_targets_save_mined'):
                        rows_to_save=[]
                        for row in selected_mined_targets:
                            rows_to_save.append({
                                'playlist_name':row.get('playlist_name') or row.get('name') or '',
                                'name':row.get('playlist_name') or row.get('name') or '',
                                'playlist_url':row.get('playlist_url') or row.get('url') or '',
                                'url':row.get('playlist_url') or row.get('url') or '',
                                'curator_name':row.get('curator_name') or '',
                                'follower_count':int(row.get('follower_count') or row.get('followers') or 0),
                                'followers':int(row.get('follower_count') or row.get('followers') or 0),
                                'related_artists':row.get('cyanite_seed_artists') or row.get('related_artists') or '',
                                'candidate_fit_score':float(row.get('relevance_score') or row.get('fit_score') or 0),
                                'final_score':float(row.get('relevance_score') or row.get('fit_score') or 0),
                                'fit_score':float(row.get('relevance_score') or row.get('fit_score') or 0),
                                'scoring_notes':row.get('reason') or '',
                            })
                        with st.spinner('Saving selected mined playlist targets...'):
                            report=process_playlists(rows_to_save,do_web_enrichment=False,do_spotify_api=False,queue_email_approval=False)
                        saved_count=report.get('total_playlists_processed',len(rows_to_save)) if isinstance(report,dict) else len(rows_to_save)
                        st.success(f"Saved {saved_count} playlist target(s) into Streambase.")
                        st.rerun()
                with c_enrich:
                    if st.button('Enrich Contacts for Selected Playlists',use_container_width=True,disabled=not selected_saved_targets,key='song_targets_enrich_contacts'):
                        unique={}
                        for row in selected_saved_targets:
                            unique[row.get('playlist_url') or row.get('url') or str(row.get('playlist_id'))]=row
                        with st.spinner('Sending selected playlists to contact enrichment API...'):
                            result=run_contact_enrichment_api(list(unique.values()))
                        if result.get('ok'):
                            credit_note=f" using {result.get('credits',0)} Tavily credit(s)" if result.get('provider')=='Tavily' else ''
                            st.success(f"Saved {result.get('saved',0)} enriched contact field(s){credit_note}.")
                            st.rerun()
                        else:
                            st.error(result.get('error') or 'Contact enrichment failed.')
                with c_campaign:
                    if st.button('Start Email Campaign for Selected Playlists',type='primary',use_container_width=True,disabled=not selected_saved_targets,key='song_targets_start_campaign'):
                        playlist_ids=[int(row.get('playlist_id') or 0) for row in selected_saved_targets if row.get('playlist_id')]
                        st.session_state.campaign_plan=prepare_campaign_plan(
                            selected_saved_targets,
                            cooldown_days=int(playlist_cooldown_days),
                            guard_fn=playlist_outreach_guard,
                            outreach_events=get_outreach_events_for_playlists(playlist_ids),
                        )
                        st.session_state.campaign_copy_edits={}
                        st.session_state.campaign_plan_version+=1
                        clear_campaign_copy_state()
                        st.success('Campaign started from selected playlist targets. Open Campaigns to review and approve email drafts.')
            else:
                st.info('No playlist matches were found for the selected songs yet.')
        else:
            st.info('Select one or more catalog songs to rank saved playlists.')
with tab_campaigns:
    st.subheader('Campaigns')
    st.caption('Song-based campaign workspace with separate email, Instagram, and submission-site tasks.')
    campaign_catalog=get_release_songs()
    campaign_saved_playlists=get_all_playlists()
    campaign_targets=get_song_fit_targets()
    for catalog_song in campaign_catalog:
        sync_song_campaign_tasks(int(catalog_song.get('id') or 0),min_fit=70)
    campaign_overview=get_song_campaign_overview()
    if campaign_overview:
        st.markdown('#### Catalog Campaign Overview')
        overview_df=pd.DataFrame([
            {
                'status':f"{row.get('campaign_indicator','')} {row.get('campaign_task_status','')}",
                'song':row.get('title') or row.get('file_name') or 'Untitled',
                'artist':row.get('artist_name') or '',
                'completion':row.get('completion_pct',0),
                'completed':f"{int(row.get('completed_tasks') or 0)} of {int(row.get('total_tasks') or 0)}",
                'emails':f"{int(row.get('email_completed') or 0)} of {int(row.get('email_tasks') or 0)}",
                'instagram':f"{int(row.get('instagram_completed') or 0)} of {int(row.get('instagram_tasks') or 0)}",
                'submission_sites':f"{int(row.get('submission_completed') or 0)} of {int(row.get('submission_tasks') or 0)}",
            }
            for row in campaign_overview
        ])
        st.dataframe(
            overview_df,
            use_container_width=True,
            hide_index=True,
            column_config={
                'completion':st.column_config.ProgressColumn('Completion',min_value=0,max_value=100,format='%.0f%%'),
                'submission_sites':st.column_config.TextColumn('Submission Sites'),
            },
        )
        song_labels={
            f"{row.get('campaign_indicator','')} {row.get('title') or row.get('file_name') or 'Untitled'}{(' · '+row.get('artist_name')) if row.get('artist_name') else ''}":row
            for row in campaign_overview
        }
        selected_workspace_label=st.selectbox('Open song campaign',list(song_labels.keys()),key='song_campaign_workspace_selector')
        render_song_campaign_workspace(song_labels[selected_workspace_label])
    else:
        st.info('Add songs to the catalog before opening a campaign workspace.')

    st.divider()
    st.markdown('#### Legacy Campaign Builder and History')
    st.caption('The original campaign prep tools are preserved below.')
    if campaign_catalog and campaign_saved_playlists:
        song_labels={
            ((f"{song.get('title') or song.get('file_name') or 'Untitled'} · {song.get('artist_name')}") if song.get('artist_name') else (song.get('title') or song.get('file_name') or 'Untitled')):song
            for song in campaign_catalog
        }
        selected_song_label=st.selectbox('Song',list(song_labels.keys()),key='campaign_builder_song')
        selected_campaign_song=song_labels[selected_song_label]
        selected_campaign_song_id=int(selected_campaign_song.get('id') or 0)
        default_campaign_name=selected_campaign_song.get('title') or selected_campaign_song.get('file_name') or 'Untitled Campaign'
        campaign_name=st.text_input('Campaign name',value=default_campaign_name,key=f'campaign_name_{selected_campaign_song_id}')
        with st.expander('Playlist specifications'):
            spec1,spec2=st.columns(2)
            with spec1:
                campaign_min_relevance=st.slider('Minimum relevance',0,100,55,5,key='campaign_min_relevance')
                campaign_max_playlists=st.number_input('Maximum playlists',min_value=1,max_value=250,value=25,step=5,key='campaign_max_playlists')
            with spec2:
                campaign_contact_filter=st.selectbox('Contact requirement',['Email available','Any contact method','All saved playlists'],key='campaign_contact_filter')
                campaign_min_followers=st.number_input('Minimum followers',min_value=0,max_value=10000000,value=0,step=100,key='campaign_min_followers')
        suggested_campaign_rows=build_song_target_candidates(
            [selected_campaign_song],campaign_saved_playlists,campaign_targets,250
        )
        suggested_campaign_rows=[
            row for row in suggested_campaign_rows
            if float(row.get('relevance_score') or 0)>=float(campaign_min_relevance)
            and int(row.get('followers') or 0)>=int(campaign_min_followers)
            and (
                campaign_contact_filter=='All saved playlists'
                or (campaign_contact_filter=='Email available' and bool(row.get('email')))
                or (campaign_contact_filter=='Any contact method' and bool(row.get('email') or row.get('instagram') or row.get('submission_page')))
            )
        ][:int(campaign_max_playlists)]
        st.caption(f"{len(suggested_campaign_rows)} playlist(s) match these specifications. You can change the final selection after preparing.")
        if suggested_campaign_rows:
            suggestion_preview=pd.DataFrame(suggested_campaign_rows)
            st.dataframe(
                suggestion_preview[['playlist_name','relevance_score','email','instagram','followers']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'playlist_name':st.column_config.TextColumn('Playlist'),
                    'relevance_score':st.column_config.ProgressColumn('Relevance',min_value=0,max_value=100,format='%.0f'),
                    'email':st.column_config.TextColumn('Email'),
                    'instagram':st.column_config.LinkColumn('Instagram'),
                    'followers':st.column_config.NumberColumn('Followers',format='%d'),
                },
            )
        if st.button('Prepare Campaign',type='primary',use_container_width=True,disabled=not suggested_campaign_rows,key='prepare_song_campaign'):
            playlist_ids=[int(item.get('playlist_id') or 0) for item in suggested_campaign_rows if item.get('playlist_id')]
            specifications={
                'minimum_relevance':campaign_min_relevance,
                'maximum_playlists':int(campaign_max_playlists),
                'contact_requirement':campaign_contact_filter,
                'minimum_followers':int(campaign_min_followers),
                'playlist_ids':playlist_ids,
            }
            campaign_id=create_outreach_campaign(
                selected_campaign_song_id,campaign_name,DEFAULT_CAMPAIGN_SUBJECT,DEFAULT_CAMPAIGN_BODY,specifications
            )
            prepared_plan=prepare_campaign_plan(
                suggested_campaign_rows,
                cooldown_days=int(playlist_cooldown_days),
                guard_fn=playlist_outreach_guard,
                outreach_events=get_outreach_events_for_playlists(playlist_ids),
            )
            for prepared_row in prepared_plan.get('rows',[]):
                if prepared_row.get('email') and prepared_row.get('status')!='Wait':
                    prepared_row['recommended_channel']='Email'
                    prepared_row['send']=True
            save_outreach_campaign_targets(campaign_id,prepared_plan.get('rows',[]))
            prepared_plan.update({
                'campaign_id':campaign_id,
                'campaign_name':campaign_name,
                'song_id':selected_campaign_song_id,
                'song_context':song_context_from_catalog_song(selected_campaign_song),
                'subject_template':DEFAULT_CAMPAIGN_SUBJECT,
                'body_template':DEFAULT_CAMPAIGN_BODY,
                'specifications':specifications,
            })
            st.session_state.campaign_plan=prepared_plan
            st.session_state.active_campaign_id=campaign_id
            st.session_state.campaign_copy_edits={}
            st.session_state.campaign_plan_version+=1
            clear_campaign_copy_state()
            st.rerun()
    elif not campaign_catalog:
        st.info('Add a song to the catalog before preparing a campaign.')
    else:
        st.info('Save playlists before preparing a campaign.')

    st.divider()
    campaign_records=get_outreach_campaigns()
    campaign_filter_labels=['All campaigns']+[f"{row.get('name')} · {row.get('status')} · #{row.get('id')}" for row in campaign_records]
    campaign_filter_lookup={'All campaigns':0}
    campaign_filter_lookup.update({f"{row.get('name')} · {row.get('status')} · #{row.get('id')}":int(row.get('id') or 0) for row in campaign_records})
    default_filter_index=0
    active_campaign_id=int(st.session_state.get('active_campaign_id') or 0)
    if active_campaign_id:
        active_label=next((label for label,cid in campaign_filter_lookup.items() if cid==active_campaign_id),None)
        if active_label in campaign_filter_labels:
            default_filter_index=campaign_filter_labels.index(active_label)
    selected_campaign_filter=st.selectbox('View campaign',campaign_filter_labels,index=default_filter_index,key='campaign_history_filter')
    selected_campaign_filter_id=campaign_filter_lookup.get(selected_campaign_filter,0)
    all_queue_rows=get_email_queue()
    filtered_queue_rows=[row for row in all_queue_rows if not selected_campaign_filter_id or int(row.get('campaign_id') or 0)==selected_campaign_filter_id]
    if selected_campaign_filter_id:
        render_campaign_target_sheet(selected_campaign_filter_id)
    campaign_activity=email_campaign_activity_rows(filtered_queue_rows)
    reply_rows=get_email_replies()
    if selected_campaign_filter_id:
        reply_rows=[row for row in reply_rows if int(row.get('campaign_id') or 0)==selected_campaign_filter_id]
    active_campaign_rows=[row for row in campaign_activity if row.get('status')=='approved']
    past_campaign_rows=[row for row in campaign_activity if row.get('status') in {'sent','failed'}]
    a1,a2,a3,a4=st.columns(4)
    a1.metric('Approved Drafts',len(active_campaign_rows))
    a2.metric('Sent Emails',sum(1 for row in past_campaign_rows if row.get('status')=='sent'))
    a3.metric('Failed Emails',sum(1 for row in past_campaign_rows if row.get('status')=='failed'))
    a4.metric('Replies',len(reply_rows))
    history_active,history_past,history_replies=st.tabs(['Active Drafts','Past Sends','Replies'])
    with history_active:
        if active_campaign_rows:
            st.dataframe(
                pd.DataFrame(active_campaign_rows)[['campaign_name','status','to_email','playlist_name','song_title','subject','updated_at']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'status':st.column_config.TextColumn('Status'),
                    'campaign_name':st.column_config.TextColumn('Campaign'),
                    'to_email':st.column_config.TextColumn('To'),
                    'playlist_name':st.column_config.TextColumn('Playlist'),
                    'curator_name':st.column_config.TextColumn('Curator'),
                    'song_title':st.column_config.TextColumn('Song'),
                    'subject':st.column_config.TextColumn('Subject'),
                    'updated_at':st.column_config.TextColumn('Last Updated'),
                },
            )
        else:
            st.info('No approved email drafts are active right now.')
    with history_past:
        if past_campaign_rows:
            past_df=pd.DataFrame(past_campaign_rows).sort_values('updated_at',ascending=False)
            st.dataframe(
                past_df[['campaign_name','status','to_email','playlist_name','song_title','subject','updated_at']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'status':st.column_config.TextColumn('Status'),
                    'campaign_name':st.column_config.TextColumn('Campaign'),
                    'to_email':st.column_config.TextColumn('To'),
                    'playlist_name':st.column_config.TextColumn('Playlist'),
                    'curator_name':st.column_config.TextColumn('Curator'),
                    'song_title':st.column_config.TextColumn('Song'),
                    'subject':st.column_config.TextColumn('Subject'),
                    'updated_at':st.column_config.TextColumn('Sent / Updated'),
                },
            )
        else:
            st.info('No sent campaign emails yet.')
    with history_replies:
        gmail_status=gmail_reply_status()
        st.caption(f"Gmail reply inbox: {gmail_status.get('account') or 'not configured'}")
        if st.button('Sync Gmail Replies',use_container_width=True,disabled=not gmail_status.get('configured'),key='sync_gmail_replies'):
            with st.spinner('Checking Gmail for replies...'):
                result=sync_gmail_replies(days=30,limit=50)
            if result.get('ok'):
                st.success(f"Saved {result.get('saved',0)} reply/replies. Matched {result.get('matched',0)} to Streambase emails.")
                st.rerun()
            else:
                st.error(result.get('error') or 'Gmail reply sync failed.')
        if not gmail_status.get('configured'):
            st.info(gmail_status.get('message'))
        if reply_rows:
            reply_df=pd.DataFrame(reply_rows)
            for col in ['campaign_name','received_at','from_email','from_name','match_status','playlist_name','curator_name','song_title','subject','snippet']:
                if col not in reply_df.columns:
                    reply_df[col]=''
            st.dataframe(
                reply_df[['campaign_name','received_at','from_email','from_name','match_status','playlist_name','song_title','subject','snippet']],
                use_container_width=True,
                hide_index=True,
                column_config={
                    'received_at':st.column_config.TextColumn('Received'),
                    'campaign_name':st.column_config.TextColumn('Campaign'),
                    'from_email':st.column_config.TextColumn('From Email'),
                    'from_name':st.column_config.TextColumn('From Name'),
                    'match_status':st.column_config.TextColumn('Match'),
                    'playlist_name':st.column_config.TextColumn('Playlist'),
                    'curator_name':st.column_config.TextColumn('Curator'),
                    'song_title':st.column_config.TextColumn('Song'),
                    'subject':st.column_config.TextColumn('Subject'),
                    'snippet':st.column_config.TextColumn('Reply Preview'),
                },
            )
        else:
            st.info('No replies synced into Streambase yet.')
    st.markdown('#### Campaign Workspace')
    plan=st.session_state.campaign_plan or {}
    campaign_rows=plan.get('rows',[])
    if campaign_rows:
        m1,m2,m3,m4=st.columns(4)
        m1.metric('Ready',plan.get('ready_count',0))
        m2.metric('Worth Considering',plan.get('worth_considering_count',0))
        m3.metric('Wait',plan.get('wait_count',0))
        m4.metric('Unique Playlists',plan.get('unique_playlist_count',0))
        instagram_rows=campaign_channel_rows(campaign_rows,'Instagram')
        email_rows=campaign_channel_rows(campaign_rows,'Email')
        submission_rows=campaign_channel_rows(campaign_rows,'Submission')
        research_rows=campaign_channel_rows(campaign_rows,'Research')
        cinst,cemail,csubmit,cresearch=st.columns(4)
        cinst.metric('Instagram',len(instagram_rows),f"{sum(1 for r in instagram_rows if r.get('instagram_opened') or r.get('instagram_dm_pasted'))} opened")
        cemail.metric('Email',len(email_rows),f"{sum(1 for r in email_rows if r.get('email_drafted'))} drafted")
        csubmit.metric('Submissions',len(submission_rows),f"{sum(1 for r in submission_rows if r.get('submission_sent'))} sent")
        cresearch.metric('Research',len(research_rows))
        tab_ig,tab_email,tab_submit,tab_research=st.tabs(['Instagram','Email','Submission Links','Research'])
        with tab_ig:
            st.caption('Preselected rows are the best Instagram targets. A green check means the Instagram link was opened or the DM was pasted.')
            if instagram_rows:
                ig_df=campaign_queue_table(instagram_rows,'Instagram')
                st.dataframe(
                    ig_df[['done','playlist_name','fit_score','status','contact','reason']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'done':st.column_config.TextColumn('✓',width='small'),
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                        'contact':st.column_config.LinkColumn('Instagram'),
                    },
                )
                row,selected_idx=selected_campaign_row(instagram_rows,'Instagram')
                if row:
                    edit_key=row.get('playlist_url') or f"instagram_{selected_idx}"
                    existing_edit=st.session_state.campaign_copy_edits.get(edit_key,{})
                    plan_version=st.session_state.campaign_plan_version
                    instagram_dm_value=existing_edit.get('instagram_dm') or row.get('instagram_dm','')
                    if row.get('song_url') and row.get('song_url') not in instagram_dm_value:
                        instagram_dm_value=f"{instagram_dm_value.rstrip()}\n\nSpotify link: {row.get('song_url')}"
                    dm_body=st.text_area('Instagram DM',instagram_dm_value,height=150,key=f"campaign_ig_dm_{plan_version}_{selected_idx}")
                    st.session_state.campaign_copy_edits[edit_key]={**existing_edit,'instagram_dm':dm_body}
                    if not row.get('song_url'):
                        st.warning('No Spotify URL is saved for this campaign song yet. Add or re-scan the released Spotify URL before sending.')
                    a,b,c=st.columns(3)
                    with a:
                        copy_and_open_button('Copy DM + Open Instagram',dm_body,row.get('instagram'),f"ig-copy-open-{selected_idx}")
                    with b:
                        copy_button('Copy DM',dm_body,f"ig-copy-{selected_idx}")
                    with c:
                        raw=row.get('raw') or {}
                        if st.button('Mark Instagram Opened',use_container_width=True,key=f"mark_ig_opened_{selected_idx}"):
                            update_outreach_campaign_target_status(int(plan.get('campaign_id') or 0),int(raw.get('playlist_id') or 0),'instagram','done')
                            add_outreach_event(int(raw.get('curator_id') or 0),int(raw.get('playlist_id') or 0),'instagram','instagram_opened',row.get('instagram',''),campaign_id=int(plan.get('campaign_id') or 0))
                            st.rerun()
                    raw=row.get('raw') or {}
                    if st.button('Mark DM Pasted',use_container_width=True,key=f"mark_ig_pasted_{selected_idx}"):
                        update_outreach_campaign_target_status(int(plan.get('campaign_id') or 0),int(raw.get('playlist_id') or 0),'instagram','done')
                        add_outreach_event(int(raw.get('curator_id') or 0),int(raw.get('playlist_id') or 0),'instagram','manual_dm_pasted',dm_body,campaign_id=int(plan.get('campaign_id') or 0))
                        st.rerun()
            else:
                st.info('No Instagram targets in this campaign.')
        with tab_email:
            st.caption('Write one campaign email. Streambase changes only the playlist name for each approved recipient.')
            if email_rows:
                email_df=campaign_queue_table(email_rows,'Email')
                edited_email=st.data_editor(
                    email_df[['send','done','playlist_name','fit_score','status','contact','reason']],
                    use_container_width=True,
                    hide_index=True,
                    key=f"campaign_email_queue_editor_{plan.get('campaign_id',0)}_{st.session_state.campaign_plan_version}",
                    disabled=['done','playlist_name','fit_score','status','contact','reason'],
                    column_config={
                        'send':st.column_config.CheckboxColumn('Approve'),
                        'done':st.column_config.TextColumn('✓',width='small'),
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                        'contact':st.column_config.TextColumn('Email'),
                    },
                )
                for idx,flag in enumerate(edited_email['send'].tolist() if not edited_email.empty else []):
                    if idx<len(email_rows):
                        email_rows[idx]['send']=bool(flag)
                campaign_id=int(plan.get('campaign_id') or 0)
                campaign_subject=st.text_input(
                    'Subject template',
                    value=plan.get('subject_template') or DEFAULT_CAMPAIGN_SUBJECT,
                    key=f'campaign_subject_template_{campaign_id}_{st.session_state.campaign_plan_version}',
                )
                campaign_body=st.text_area(
                    'Campaign email',
                    value=plan.get('body_template') or DEFAULT_CAMPAIGN_BODY,
                    height=260,
                    key=f'campaign_body_template_{campaign_id}_{st.session_state.campaign_plan_version}',
                )
                st.caption('Use {playlist_name} where the playlist name should appear. The song link is shared through {song_url}.')
                preview_row,preview_idx=selected_campaign_row(email_rows,'Email Preview')
                campaign_song_context=plan.get('song_context') or ((preview_row.get('raw') or {}).get('song_context') if preview_row else {}) or {}
                if preview_row:
                    preview_subject=render_campaign_template(campaign_subject,preview_row.get('playlist_name'),campaign_song_context)
                    preview_body=render_campaign_template(campaign_body,preview_row.get('playlist_name'),campaign_song_context)
                    st.markdown('##### Preview')
                    st.text_input('Preview subject',value=preview_subject,disabled=True,key=f'campaign_subject_preview_{campaign_id}_{preview_idx}')
                    st.text_area('Preview email',value=preview_body,height=220,disabled=True,key=f'campaign_body_preview_{campaign_id}_{preview_idx}')
                if not (campaign_song_context.get('spotify_url') or campaign_song_context.get('song_url')):
                    st.warning('No Spotify URL is saved for this campaign song yet. Add it to the catalog before sending.')
                if st.button('Approve Selected Email Drafts',type='primary',use_container_width=True):
                    queued=0
                    skipped=0
                    duplicate_skipped=0
                    approved_or_sent_emails={
                        normalize_email(row.get('to_email'))
                        for row in get_email_queue()
                        if (
                            row.get('status')=='approved'
                            or (row.get('status')=='sent' and int(row.get('campaign_id') or 0)==campaign_id)
                        ) and normalize_email(row.get('to_email'))
                    }
                    for idx,item in enumerate(email_rows):
                        if not item.get('send') or not item.get('email'):
                            skipped+=1
                            continue
                        email_key=normalize_email(item.get('email'))
                        if email_key in approved_or_sent_emails:
                            duplicate_skipped+=1
                            skipped+=1
                            continue
                        raw=item.get('raw') or {}
                        song_context=campaign_song_context or (raw.get('song_context') if isinstance(raw.get('song_context'),dict) else {})
                        subject=render_campaign_template(campaign_subject,item.get('playlist_name'),song_context)
                        body=render_campaign_template(campaign_body,item.get('playlist_name'),song_context)
                        queue_id=queue_email(
                            int(raw.get('curator_id') or 0),
                            int(raw.get('playlist_id') or 0),
                            item.get('email',''),
                            subject,
                            body,
                            song_context=song_context,
                            cooldown_days=int(playlist_cooldown_days),
                            enforce_cooldown=item.get('status')!='Worth considering',
                            campaign_id=campaign_id,
                        )
                        if queue_id:
                            update_email_queue_status(queue_id,'approved')
                            approved_or_sent_emails.add(email_key)
                            queued+=1
                            add_outreach_event(int(raw.get('curator_id') or 0),int(raw.get('playlist_id') or 0),'email','drafted',body,campaign_id=campaign_id)
                        else:
                            skipped+=1
                    if campaign_id:
                        update_outreach_campaign(
                            campaign_id,
                            subject_template=campaign_subject,
                            body_template=campaign_body,
                            status='active',
                        )
                    message=f"Approved {queued} email draft(s). Skipped {skipped}."
                    if duplicate_skipped:
                        message+=f" Held {duplicate_skipped} duplicate recipient(s) out of approval."
                    st.success(message)
                    st.rerun()
                pending_emails=[
                    queued_row for queued_row in get_email_queue('approved')
                    if not campaign_id or int(queued_row.get('campaign_id') or 0)==campaign_id
                ]
                sendable_emails,duplicate_emails,missing_email_drafts=split_sendable_email_drafts(pending_emails)
                sender=email_sender_status()
                st.markdown('#### Send Approved Email Drafts')
                st.caption(f"Sender: {sender.get('from') or 'not configured'} · Reply-To: {sender.get('reply_to') or 'not configured'}")
                if pending_emails:
                    if duplicate_emails:
                        st.warning(f"{len(duplicate_emails)} approved draft(s) share a recipient with another approved draft. They are held out of the send table so one email address is only sent once.")
                        st.dataframe(
                            pd.DataFrame([
                                {
                                    'to_email':row.get('to_email',''),
                                    'playlist_name':row.get('playlist_name',''),
                                    'held_because':f"Duplicate of {row.get('duplicate_of','another approved draft')}",
                                }
                                for row in duplicate_emails
                            ]),
                            use_container_width=True,
                            hide_index=True,
                        )
                    send_df=pd.DataFrame([
                        {
                            'send':False,
                            'id':row.get('id'),
                            'to_email':row.get('to_email',''),
                            'playlist_name':row.get('playlist_name',''),
                            'subject':row.get('subject',''),
                            'song_title':row.get('song_title',''),
                            'status':row.get('status',''),
                        }
                        for row in sendable_emails
                    ])
                    if not send_df.empty:
                        edited_send=st.data_editor(
                            send_df,
                            use_container_width=True,
                            hide_index=True,
                            key=f'campaign_send_email_editor_{campaign_id}',
                            disabled=['id','to_email','playlist_name','subject','song_title','status'],
                            column_config={
                                'send':st.column_config.CheckboxColumn('Send'),
                                'id':None,
                                'to_email':st.column_config.TextColumn('To'),
                                'playlist_name':st.column_config.TextColumn('Playlist'),
                                'subject':st.column_config.TextColumn('Subject'),
                                'song_title':st.column_config.TextColumn('Song'),
                                'status':st.column_config.TextColumn('Status'),
                            },
                        )
                        selected_queue_ids=set(edited_send.loc[edited_send['send']==True,'id'].astype(int).tolist()) if not edited_send.empty else set()
                        if st.button('Send Selected Email Drafts',type='primary',use_container_width=True,disabled=not selected_queue_ids or not sender.get('configured'),key='send_selected_email_drafts'):
                            sent=0
                            failed=0
                            skipped_duplicate=0
                            sent_email_keys=set()
                            for row in sendable_emails:
                                if int(row.get('id') or 0) not in selected_queue_ids:
                                    continue
                                email_key=normalize_email(row.get('to_email'))
                                if not email_key or email_key in sent_email_keys:
                                    skipped_duplicate+=1
                                    continue
                                sent_email_keys.add(email_key)
                                result=send_email_via_resend(row.get('to_email',''),row.get('subject',''),row.get('body',''))
                                if result.get('ok'):
                                    update_email_queue_after_send(int(row.get('id')), 'sent', provider_id=result.get('provider_id',''))
                                    update_outreach_campaign_target_status(campaign_id,int(row.get('playlist_id') or 0),'email','done')
                                    add_outreach_event(int(row.get('curator_id') or 0),int(row.get('playlist_id') or 0),'email','sent',row.get('body',''),campaign_id=campaign_id)
                                    sent+=1
                                else:
                                    update_email_queue_after_send(int(row.get('id')), 'failed', error=result.get('error',''))
                                    failed+=1
                            message=f"Sent {sent} email(s). Failed {failed}."
                            if skipped_duplicate:
                                message+=f" Skipped {skipped_duplicate} duplicate recipient(s)."
                            if campaign_id:
                                remaining_for_campaign=[
                                    queued_row for queued_row in get_email_queue('approved')
                                    if int(queued_row.get('campaign_id') or 0)==campaign_id
                                ]
                                update_outreach_campaign(campaign_id,status='active' if remaining_for_campaign else 'sent')
                            st.success(message)
                            st.rerun()
                    else:
                        st.info('No approved email drafts with unique recipient addresses are ready to send.')
                    if not sender.get('configured'):
                        st.warning(sender.get('message') or 'Email sending is not configured.')
                else:
                    st.info('No approved email drafts are waiting to send.')
            else:
                st.info('No email targets in this campaign.')
        with tab_submit:
            st.caption('Submission links are tracked separately so forms and platforms do not get mixed into DM or email work.')
            if submission_rows:
                submit_df=campaign_queue_table(submission_rows,'Submission')
                st.dataframe(
                    submit_df[['done','playlist_name','fit_score','status','contact','reason']],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        'done':st.column_config.TextColumn('✓',width='small'),
                        'playlist_name':st.column_config.TextColumn('Playlist'),
                        'fit_score':st.column_config.ProgressColumn('Fit',min_value=0,max_value=100,format='%.0f'),
                        'contact':st.column_config.LinkColumn('Submission'),
                    },
                )
                row,selected_idx=selected_campaign_row(submission_rows,'Submission')
                if row:
                    edit_key=row.get('playlist_url') or f"submission_{selected_idx}"
                    existing_edit=st.session_state.campaign_copy_edits.get(edit_key,{})
                    plan_version=st.session_state.campaign_plan_version
                    submission_body=st.text_area('Submission Note',existing_edit.get('submission_note') or row.get('submission_note',''),height=150,key=f"campaign_submission_body_{plan_version}_{selected_idx}")
                    st.session_state.campaign_copy_edits[edit_key]={**existing_edit,'submission_note':submission_body}
                    s1,s2,s3=st.columns(3)
                    with s1:
                        st.link_button('Open Submission',row.get('submission_page'),use_container_width=True)
                    with s2:
                        copy_button('Copy Note',submission_body,f"submit-copy-{selected_idx}")
                    with s3:
                        raw=row.get('raw') or {}
                        if st.button('Mark Submitted',use_container_width=True,key=f"mark_submit_{selected_idx}"):
                            update_outreach_campaign_target_status(int(plan.get('campaign_id') or 0),int(raw.get('playlist_id') or 0),'submission','done')
                            add_outreach_event(int(raw.get('curator_id') or 0),int(raw.get('playlist_id') or 0),'submission','manual_submission_sent',submission_body,campaign_id=int(plan.get('campaign_id') or 0))
                            st.rerun()
            else:
                st.info('No submission-link targets in this campaign.')
        with tab_research:
            st.caption('These rows are waiting because they need better contact info, are inside cooldown, or were held to avoid double-submitting.')
            if research_rows:
                research_df=campaign_queue_table(research_rows,'Research')
                st.dataframe(research_df[['done','playlist_name','fit_score','status','contact','reason']],use_container_width=True,hide_index=True)
            else:
                st.success('No research-only targets in this campaign.')
    elif campaign_catalog and campaign_saved_playlists:
        st.info('Choose a song and click Prepare Campaign to build its suggested playlist list.')
