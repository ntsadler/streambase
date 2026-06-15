import json, sqlite3
from pathlib import Path
from datetime import UTC, datetime
from src.settings import DB_PATH, local_data_path, project_data_path
def connect(db_path=DB_PATH):
    Path(db_path).parent.mkdir(parents=True,exist_ok=True); conn=sqlite3.connect(db_path); conn.row_factory=sqlite3.Row; return conn
def now(): return datetime.now(UTC).isoformat(timespec='seconds')
def init_db(db_path=DB_PATH):
    with connect(db_path) as c:
        c.execute("CREATE TABLE IF NOT EXISTS curators (id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,display_name TEXT,notes TEXT,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS playlists (id INTEGER PRIMARY KEY AUTOINCREMENT,curator_id INTEGER,name TEXT,url TEXT UNIQUE,platform TEXT DEFAULT 'spotify',followers INTEGER,related_artists TEXT,spotify_description TEXT,similarity_score REAL,final_score REAL,priority TEXT,status TEXT DEFAULT 'new',created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS contact_methods (id INTEGER PRIMARY KEY AUTOINCREMENT,curator_id INTEGER,type TEXT,value TEXT,source_url TEXT,confidence_score INTEGER,status TEXT DEFAULT 'new',created_at TEXT,UNIQUE(curator_id,type,value))")
        c.execute("CREATE TABLE IF NOT EXISTS outreach_events (id INTEGER PRIMARY KEY AUTOINCREMENT,curator_id INTEGER,playlist_id INTEGER,channel TEXT,event_type TEXT,message TEXT,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS email_queue (id INTEGER PRIMARY KEY AUTOINCREMENT,curator_id INTEGER,playlist_id INTEGER,to_email TEXT,subject TEXT,body TEXT,status TEXT DEFAULT 'pending_approval',created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS song_fit_targets (id INTEGER PRIMARY KEY AUTOINCREMENT,song_title TEXT,artist_name TEXT,playlist_name TEXT,playlist_url TEXT,curator_name TEXT,fit_score REAL,status TEXT DEFAULT 'target',notes TEXT,created_at TEXT,UNIQUE(song_title,artist_name,playlist_url))")
        c.execute("CREATE TABLE IF NOT EXISTS artist_songs (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,file_path TEXT UNIQUE,bpm REAL,key TEXT,genre_tags TEXT,mood_tags TEXT,energy TEXT,danceability REAL,instrumentation TEXT,vocal_style TEXT,reference_artists TEXT,notes TEXT,created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS artist_sound_profiles (id INTEGER PRIMARY KEY AUTOINCREMENT,profile_name TEXT UNIQUE,song_count INTEGER,profile_json TEXT,created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS songs (id INTEGER PRIMARY KEY AUTOINCREMENT,title TEXT,file_path TEXT UNIQUE,release_status TEXT DEFAULT 'unreleased',planned_release_date TEXT,campaign_status TEXT DEFAULT 'needs_profile',created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS song_audio_profiles (id INTEGER PRIMARY KEY AUTOINCREMENT,song_id INTEGER UNIQUE,bpm REAL,key TEXT,genre_tags TEXT,mood_tags TEXT,energy TEXT,danceability REAL,instrumentation TEXT,vocal_style TEXT,lyrical_theme_notes TEXT,reference_artists TEXT,recommended_playlist_categories TEXT,recommended_chartmetric_targets TEXT,analysis_source TEXT DEFAULT 'manual',notes TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS release_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT,song_id INTEGER UNIQUE,campaign_brief_json TEXT,status TEXT DEFAULT 'draft',created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS song_playlist_targets (id INTEGER PRIMARY KEY AUTOINCREMENT,song_id INTEGER,playlist_name TEXT,playlist_url TEXT,fit_score REAL,status TEXT DEFAULT 'target',notes TEXT,created_at TEXT,UNIQUE(song_id,playlist_url))")
        c.execute("CREATE TABLE IF NOT EXISTS campaign_targets (id INTEGER PRIMARY KEY AUTOINCREMENT,campaign_id INTEGER,playlist_target_id INTEGER,channel TEXT,status TEXT DEFAULT 'planned',copy_direction TEXT,created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS artist_references (id INTEGER PRIMARY KEY AUTOINCREMENT,artist_name TEXT,source TEXT,confidence_score REAL DEFAULT 0,approved_by_user INTEGER DEFAULT 0,rejected_by_user INTEGER DEFAULT 0,notes TEXT,created_at TEXT,updated_at TEXT,UNIQUE(artist_name,source))")
        c.execute("CREATE TABLE IF NOT EXISTS mining_jobs (id INTEGER PRIMARY KEY AUTOINCREMENT,profile_name TEXT,source TEXT DEFAULT 'chartmetric',status TEXT DEFAULT 'planned',query_count INTEGER DEFAULT 0,result_count INTEGER DEFAULT 0,profile_json TEXT,target_json TEXT,error TEXT,created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS mined_playlists (id INTEGER PRIMARY KEY AUTOINCREMENT,mining_job_id INTEGER,source TEXT DEFAULT 'chartmetric',query TEXT,playlist_name TEXT,playlist_url TEXT,curator_name TEXT,follower_count INTEGER,spotify_description TEXT,last_updated TEXT,chartmetric_playlist_id TEXT,raw_json TEXT,status TEXT DEFAULT 'mined',created_at TEXT,UNIQUE(source,playlist_url,query))")
        ensure_column(c,'playlists','intersection_score','REAL DEFAULT 0')
        ensure_column(c,'playlists','spotify_playlist_id','TEXT')
        ensure_column(c,'playlists','scoring_notes','TEXT')
        ensure_column(c,'playlists','submithub_verified','INTEGER DEFAULT 0')
        ensure_column(c,'playlists','submithub_url','TEXT')
        ensure_column(c,'email_queue','song_title','TEXT')
        ensure_column(c,'email_queue','song_url','TEXT')
        ensure_column(c,'email_queue','song_context_json','TEXT')
        ensure_column(c,'songs','file_name','TEXT')
        ensure_column(c,'song_audio_profiles','source','TEXT DEFAULT "manual"')
        ensure_column(c,'song_audio_profiles','raw_analysis_json','TEXT')
        ensure_column(c,'song_audio_profiles','created_at','TEXT')
        ensure_column(c,'artist_sound_profiles','name','TEXT')
        ensure_column(c,'artist_sound_profiles','core_genre_tags','TEXT')
        ensure_column(c,'artist_sound_profiles','core_mood_tags','TEXT')
        ensure_column(c,'artist_sound_profiles','strongest_reference_artists','TEXT')
        ensure_column(c,'artist_sound_profiles','recurring_audio_traits','TEXT')
        ensure_column(c,'artist_sound_profiles','recommended_playlist_keywords','TEXT')
        ensure_column(c,'artist_sound_profiles','recommended_chartmetric_targets','TEXT')
        ensure_column(c,'artist_sound_profiles','raw_profile_json','TEXT')
        c.commit()
def ensure_column(conn,table,column,definition):
    cols={r['name'] for r in conn.execute(f'PRAGMA table_info({table})').fetchall()}
    if column not in cols: conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')
def get_or_create_curator(name,db_path=DB_PATH):
    clean=(name or 'Unknown Curator').strip() or 'Unknown Curator'
    with connect(db_path) as c:
        row=c.execute('SELECT id FROM curators WHERE name=?',(clean.lower(),)).fetchone()
        if row: return int(row['id'])
        cur=c.execute('INSERT INTO curators (name,display_name,created_at) VALUES (?,?,?)',(clean.lower(),clean,now())); c.commit(); return int(cur.lastrowid)
def upsert_playlist(item,db_path=DB_PATH):
    curator_id=get_or_create_curator(item.get('curator') or item.get('curator_name') or 'Unknown Curator',db_path); url=item.get('url') or item.get('playlist_url') or ''
    with connect(db_path) as c:
        c.execute("""INSERT OR REPLACE INTO playlists (curator_id,name,url,platform,followers,related_artists,spotify_description,similarity_score,intersection_score,final_score,priority,status,created_at,spotify_playlist_id,scoring_notes,submithub_verified,submithub_url) VALUES (?,?,?,COALESCE((SELECT platform FROM playlists WHERE url=?),'spotify'),?,?,?,?,?,?,?,COALESCE((SELECT status FROM playlists WHERE url=?),'new'),COALESCE((SELECT created_at FROM playlists WHERE url=?),?),?,?,?,?)""",(curator_id,item.get('name') or item.get('playlist_name'),url,url,int(item.get('followers') or item.get('follower_count') or 0),item.get('related_artists',''),item.get('spotify_description',''),item.get('similarity_score',0),item.get('intersection_score',0),item.get('final_score',0),item.get('priority','new'),url,url,now(),item.get('spotify_playlist_id',''),item.get('scoring_notes',''),1 if item.get('submithub_verified') else 0,item.get('submithub_url','')))
        row=c.execute('SELECT id FROM playlists WHERE url=?',(url,)).fetchone(); c.commit(); return int(row['id']) if row else 0
def upsert_contact_method(curator_id,m,db_path=DB_PATH):
    if not m.get('value') or not m.get('type'): return
    with connect(db_path) as c:
        c.execute("INSERT OR IGNORE INTO contact_methods (curator_id,type,value,source_url,confidence_score,status,created_at) VALUES (?,?,?,?,?,?,?)",(curator_id,m.get('type'),m.get('value'),m.get('source_url',''),int(m.get('confidence_score') or 0),m.get('status','new'),now())); c.commit()
def add_outreach_event(curator_id,playlist_id,channel,event_type,message='',db_path=DB_PATH):
    with connect(db_path) as c:
        c.execute('INSERT INTO outreach_events (curator_id,playlist_id,channel,event_type,message,created_at) VALUES (?,?,?,?,?,?)',(curator_id,playlist_id,channel,event_type,message,now())); c.commit()
def update_playlist_status(playlist_id,status,db_path=DB_PATH):
    with connect(db_path) as c: c.execute('UPDATE playlists SET status=? WHERE id=?',(status,playlist_id)); c.commit()
def _parse_dt(value):
    if not value: return None
    try: return datetime.fromisoformat(value.replace('Z','+00:00'))
    except ValueError: return None
def playlist_outreach_guard(playlist_id,song_context=None,cooldown_days=30,db_path=DB_PATH):
    song_context=song_context or {}
    now_dt=datetime.now(UTC)
    with connect(db_path) as c:
        queue_rows=c.execute("""SELECT song_title,song_url,status,created_at,updated_at
                                FROM email_queue
                                WHERE playlist_id=? AND status IN ('pending_approval','approved','sent')
                                ORDER BY COALESCE(updated_at,created_at) DESC""",(playlist_id,)).fetchall()
        event_rows=c.execute("""SELECT event_type,created_at
                                FROM outreach_events
                                WHERE playlist_id=?
                                ORDER BY created_at DESC""",(playlist_id,)).fetchall()
    recent=[]
    for row in queue_rows:
        dt=_parse_dt(row['updated_at'] or row['created_at'])
        if dt:
            recent.append({'type':'email_queue','status':row['status'],'song_title':row['song_title'] or 'previous song','song_url':row['song_url'] or '','created_at':(row['updated_at'] or row['created_at']),'days_since':(now_dt-dt).days})
    for row in event_rows:
        dt=_parse_dt(row['created_at'])
        if dt:
            recent.append({'type':'outreach_event','status':row['event_type'],'song_title':'previous outreach','song_url':'','created_at':row['created_at'],'days_since':(now_dt-dt).days})
    recent=sorted(recent,key=lambda x:x['days_since'])
    blocking=next((r for r in recent if r['days_since']<cooldown_days),None)
    if blocking:
        return {'allowed':False,'reason':f"Playlist contacted {blocking['days_since']} day(s) ago for {blocking['song_title']}. Wait until the {cooldown_days}-day cooldown clears or override manually.",'cooldown_days':cooldown_days,'last_outreach':blocking,'song_title':song_context.get('title') or song_context.get('song_title','')}
    return {'allowed':True,'reason':'No recent playlist outreach found.','cooldown_days':cooldown_days,'last_outreach':recent[0] if recent else None,'song_title':song_context.get('title') or song_context.get('song_title','')}
def queue_email(curator_id,playlist_id,to_email,subject,body,db_path=DB_PATH,song_context=None,cooldown_days=30,enforce_cooldown=True):
    if not to_email or not body: return 0
    if enforce_cooldown:
        guard=playlist_outreach_guard(playlist_id,song_context,cooldown_days,db_path)
        if not guard.get('allowed'): return 0
    song_context=song_context or {}
    song_title=song_context.get('title') or song_context.get('song_title') or ''
    song_url=song_context.get('spotify_url') or song_context.get('song_url') or song_context.get('preview_url') or ''
    song_json=json.dumps(song_context,ensure_ascii=True) if song_context else ''
    with connect(db_path) as c:
        row=c.execute("SELECT id FROM email_queue WHERE curator_id=? AND playlist_id=? AND to_email=? AND status='pending_approval'",(curator_id,playlist_id,to_email)).fetchone()
        if row: return int(row['id'])
        cur=c.execute('INSERT INTO email_queue (curator_id,playlist_id,to_email,subject,body,status,created_at,updated_at,song_title,song_url,song_context_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(curator_id,playlist_id,to_email,subject,body,'pending_approval',now(),now(),song_title,song_url,song_json))
        c.commit(); return int(cur.lastrowid)
def update_email_queue_status(queue_id,status,db_path=DB_PATH):
    with connect(db_path) as c: c.execute('UPDATE email_queue SET status=?, updated_at=? WHERE id=?',(status,now(),queue_id)); c.commit()
def get_email_queue(status=None,db_path=DB_PATH):
    sql="""SELECT q.*, c.display_name AS curator_name, p.name AS playlist_name, p.url AS playlist_url
           FROM email_queue q
           LEFT JOIN curators c ON q.curator_id=c.id
           LEFT JOIN playlists p ON q.playlist_id=p.id"""
    args=()
    if status: sql+=' WHERE q.status=?'; args=(status,)
    sql+=' ORDER BY q.created_at DESC'
    with connect(db_path) as c: rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]
def get_playlist_scoring_context(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute('SELECT name,url,related_artists,spotify_description FROM playlists').fetchall()
    return [dict(r) for r in rows]
def save_song_fit_targets(song,matches,db_path=DB_PATH):
    saved=0; title=song.get('title',''); artist=song.get('artist','')
    with connect(db_path) as c:
        for m in matches:
            if not m.get('playlist_url'): continue
            cur=c.execute("""INSERT OR IGNORE INTO song_fit_targets (song_title,artist_name,playlist_name,playlist_url,curator_name,fit_score,status,notes,created_at) VALUES (?,?,?,?,?,?,?,?,?)""",(title,artist,m.get('playlist_name',''),m.get('playlist_url',''),m.get('curator_name',''),m.get('fit_score',0),'target',str({'shared_reference_artists':m.get('shared_reference_artists',[]),'matched_descriptors':m.get('matched_descriptors',[])}),now()))
            saved+=cur.rowcount
        c.commit()
    return saved
def get_song_fit_targets(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute('SELECT * FROM song_fit_targets ORDER BY created_at DESC, fit_score DESC').fetchall()
    return [dict(r) for r in rows]
def get_curator_profiles(db_path=DB_PATH):
    with connect(db_path) as c:
        curators=[dict(r) for r in c.execute('SELECT * FROM curators ORDER BY display_name').fetchall()]
        for cur in curators:
            cur['playlists']=[dict(r) for r in c.execute('SELECT * FROM playlists WHERE curator_id=? ORDER BY final_score DESC',(cur['id'],)).fetchall()]
            cur['contact_methods']=[dict(r) for r in c.execute('SELECT * FROM contact_methods WHERE curator_id=? ORDER BY confidence_score DESC',(cur['id'],)).fetchall()]
            cur['outreach_events']=[dict(r) for r in c.execute('SELECT * FROM outreach_events WHERE curator_id=? ORDER BY created_at DESC',(cur['id'],)).fetchall()]
    return curators
def get_all_playlists(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute('SELECT p.*, c.display_name AS curator_name FROM playlists p LEFT JOIN curators c ON p.curator_id=c.id ORDER BY p.final_score DESC').fetchall()
    return [dict(r) for r in rows]

def create_mining_job(profile,target,source='chartmetric',status='planned',db_path=DB_PATH):
    with connect(db_path) as c:
        cur=c.execute("""INSERT INTO mining_jobs (profile_name,source,status,query_count,result_count,profile_json,target_json,error,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (profile.get('profile_name','Artist Sound Profile'),source,status,0,0,json.dumps(profile,ensure_ascii=True),json.dumps(target,ensure_ascii=True),'',now(),now()))
        c.commit(); return int(cur.lastrowid)

def update_mining_job(job_id,status=None,query_count=None,result_count=None,error='',db_path=DB_PATH):
    with connect(db_path) as c:
        current=c.execute('SELECT * FROM mining_jobs WHERE id=?',(int(job_id),)).fetchone()
        if not current: return 0
        c.execute("""UPDATE mining_jobs SET status=?,query_count=?,result_count=?,error=?,updated_at=? WHERE id=?""",
                  (status if status is not None else current['status'],
                   int(query_count if query_count is not None else current['query_count'] or 0),
                   int(result_count if result_count is not None else current['result_count'] or 0),
                   error if error is not None else current['error'],
                   now(),int(job_id)))
        c.commit(); return int(job_id)

def save_mined_playlist(job_id,playlist,db_path=DB_PATH):
    if not playlist.get('playlist_url') and not playlist.get('chartmetric_playlist_id'): return 0
    raw=playlist.get('raw_json') or playlist.get('raw') or {}
    if not isinstance(raw,str): raw=json.dumps(raw,ensure_ascii=True)
    with connect(db_path) as c:
        cur=c.execute("""INSERT OR IGNORE INTO mined_playlists (mining_job_id,source,query,playlist_name,playlist_url,curator_name,follower_count,spotify_description,last_updated,chartmetric_playlist_id,raw_json,status,created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (int(job_id),playlist.get('source','chartmetric'),playlist.get('search_query') or playlist.get('query',''),playlist.get('playlist_name',''),playlist.get('playlist_url',''),playlist.get('curator_name',''),int(playlist.get('follower_count') or 0),playlist.get('spotify_description',''),playlist.get('last_updated',''),playlist.get('chartmetric_playlist_id',''),raw,playlist.get('status','mined'),now()))
        c.commit(); return int(cur.lastrowid) if cur.rowcount else 0

def bulk_save_mined_playlists(job_id,playlists,db_path=DB_PATH):
    return sum(1 for p in playlists if save_mined_playlist(job_id,p,db_path))

def get_mining_jobs(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute('SELECT * FROM mining_jobs ORDER BY created_at DESC').fetchall()
    return [dict(r) for r in rows]

def get_mined_playlists(job_id=None,db_path=DB_PATH):
    args=()
    sql='SELECT * FROM mined_playlists'
    if job_id is not None:
        sql+=' WHERE mining_job_id=?'; args=(int(job_id),)
    sql+=' ORDER BY created_at DESC'
    with connect(db_path) as c:
        rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]

def upsert_artist_song(song,db_path=DB_PATH):
    file_path=song.get('file_path','')
    if not file_path: return 0
    with connect(db_path) as c:
        cur=c.execute("""INSERT INTO artist_songs (title,file_path,bpm,key,genre_tags,mood_tags,energy,danceability,instrumentation,vocal_style,reference_artists,notes,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(file_path) DO UPDATE SET
                         title=excluded.title,bpm=excluded.bpm,key=excluded.key,genre_tags=excluded.genre_tags,mood_tags=excluded.mood_tags,energy=excluded.energy,danceability=excluded.danceability,
                         instrumentation=excluded.instrumentation,vocal_style=excluded.vocal_style,reference_artists=excluded.reference_artists,notes=excluded.notes,updated_at=excluded.updated_at""",
                      (song.get('title',''),file_path,song.get('bpm') or None,song.get('key',''),song.get('genre_tags',''),song.get('mood_tags',''),song.get('energy',''),song.get('danceability') or None,song.get('instrumentation',''),song.get('vocal_style',''),song.get('reference_artists',''),song.get('notes',''),now(),now()))
        row=c.execute('SELECT id FROM artist_songs WHERE file_path=?',(file_path,)).fetchone(); c.commit(); return int(row['id']) if row else int(cur.lastrowid)

def bulk_upsert_artist_songs(songs,db_path=DB_PATH):
    return [upsert_artist_song(song,db_path) for song in songs]

def get_artist_songs(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute('SELECT * FROM artist_songs ORDER BY updated_at DESC, created_at DESC').fetchall()
    return [dict(r) for r in rows]

def save_artist_sound_profile(profile,profile_name='Artist Sound Profile',db_path=DB_PATH,output_path=None):
    payload=json.dumps(profile,indent=2)
    json_path=Path(output_path) if output_path else local_data_path('artist_sound_profile.json')
    json_path.parent.mkdir(parents=True,exist_ok=True)
    json_path.write_text(payload,encoding='utf-8')
    if output_path is None:
        project_data_path('artist_sound_profile.json').write_text(payload,encoding='utf-8')
    with connect(db_path) as c:
        c.execute("""INSERT INTO artist_sound_profiles (profile_name,song_count,profile_json,created_at,updated_at)
                     VALUES (?,?,?,?,?)
                     ON CONFLICT(profile_name) DO UPDATE SET song_count=excluded.song_count,profile_json=excluded.profile_json,updated_at=excluded.updated_at""",
                  (profile_name,int(profile.get('song_count') or 0),payload,now(),now()))
        c.execute("""UPDATE artist_sound_profiles SET name=?,core_genre_tags=?,core_mood_tags=?,strongest_reference_artists=?,recurring_audio_traits=?,recommended_playlist_keywords=?,recommended_chartmetric_targets=?,raw_profile_json=? WHERE profile_name=?""",
                  (profile_name,'; '.join(profile.get('core_genre_tags',[])),'; '.join(profile.get('core_mood_tags',[])),'; '.join(profile.get('strongest_reference_artists',[])),'; '.join(profile.get('recurring_audio_traits',[])),'; '.join(profile.get('playlist_search_phrases',[])),json.dumps(profile.get('chartmetric_mining_targets',{}),indent=2),payload,profile_name))
        c.commit()
    return str(json_path)

def get_artist_sound_profile(profile_name='Artist Sound Profile',db_path=DB_PATH):
    with connect(db_path) as c:
        row=c.execute('SELECT * FROM artist_sound_profiles WHERE profile_name=?',(profile_name,)).fetchone()
    if not row: return {}
    data=dict(row)
    try:
        data['profile']=json.loads(data.get('profile_json') or '{}')
    except json.JSONDecodeError:
        data['profile']={}
    return data

def upsert_release_song(song,db_path=DB_PATH):
    file_path=song.get('file_path','')
    if not file_path: return 0
    file_name=song.get('file_name') or Path(file_path).name
    with connect(db_path) as c:
        c.execute("""INSERT INTO songs (title,file_path,release_status,planned_release_date,campaign_status,created_at,updated_at,file_name)
                     VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(file_path) DO UPDATE SET
                     title=excluded.title,release_status=excluded.release_status,planned_release_date=excluded.planned_release_date,campaign_status=excluded.campaign_status,updated_at=excluded.updated_at,file_name=excluded.file_name""",
                  (song.get('title',''),file_path,song.get('release_status','unreleased') or 'unreleased',song.get('planned_release_date',''),song.get('campaign_status','needs_profile') or 'needs_profile',now(),now(),file_name))
        row=c.execute('SELECT id FROM songs WHERE file_path=?',(file_path,)).fetchone()
        song_id=int(row['id']) if row else 0
        if song_id:
            source=song.get('source') or song.get('analysis_source','manual') or 'manual'
            raw=song.get('raw_analysis_json','')
            if isinstance(raw,(dict,list)): raw=json.dumps(raw,indent=2)
            c.execute("""INSERT INTO song_audio_profiles (song_id,bpm,key,genre_tags,mood_tags,energy,danceability,instrumentation,vocal_style,lyrical_theme_notes,reference_artists,recommended_playlist_categories,recommended_chartmetric_targets,analysis_source,source,notes,raw_analysis_json,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(song_id) DO UPDATE SET
                         bpm=excluded.bpm,key=excluded.key,genre_tags=excluded.genre_tags,mood_tags=excluded.mood_tags,energy=excluded.energy,danceability=excluded.danceability,
                         instrumentation=excluded.instrumentation,vocal_style=excluded.vocal_style,lyrical_theme_notes=excluded.lyrical_theme_notes,reference_artists=excluded.reference_artists,
                         recommended_playlist_categories=excluded.recommended_playlist_categories,recommended_chartmetric_targets=excluded.recommended_chartmetric_targets,analysis_source=excluded.analysis_source,source=excluded.source,notes=excluded.notes,raw_analysis_json=excluded.raw_analysis_json,updated_at=excluded.updated_at""",
                      (song_id,song.get('bpm') or None,song.get('key',''),song.get('genre_tags',''),song.get('mood_tags',''),song.get('energy',''),song.get('danceability') or None,song.get('instrumentation',''),song.get('vocal_style',''),song.get('lyrical_theme_notes',''),song.get('reference_artists',''),song.get('recommended_playlist_categories',''),song.get('recommended_chartmetric_targets',''),source,source,song.get('notes',''),raw,now(),now()))
        c.commit()
        return song_id

def bulk_upsert_release_songs(songs,db_path=DB_PATH):
    return [upsert_release_song(song,db_path) for song in songs]

def get_release_songs(db_path=DB_PATH):
    sql="""SELECT s.*, p.bpm, p.key, p.genre_tags, p.mood_tags, p.energy, p.danceability, p.instrumentation, p.vocal_style,
                  p.lyrical_theme_notes, p.reference_artists, p.recommended_playlist_categories, p.recommended_chartmetric_targets,
                  p.analysis_source, p.source, p.notes, p.raw_analysis_json
           FROM songs s
           LEFT JOIN song_audio_profiles p ON p.song_id=s.id
           ORDER BY s.updated_at DESC, s.created_at DESC"""
    with connect(db_path) as c:
        rows=c.execute(sql).fetchall()
    return [dict(r) for r in rows]

def backup_song_profiles_json(db_path=DB_PATH,output_path=None):
    rows=get_release_songs(db_path)
    payload=json.dumps(rows,indent=2)
    path=Path(output_path) if output_path else project_data_path('song_profiles.json')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(payload,encoding='utf-8')
    return str(path)

def save_release_campaign_brief(song_id,brief,status='draft',db_path=DB_PATH):
    payload=json.dumps(brief,indent=2)
    with connect(db_path) as c:
        c.execute("""INSERT INTO release_campaigns (song_id,campaign_brief_json,status,created_at,updated_at)
                     VALUES (?,?,?,?,?)
                     ON CONFLICT(song_id) DO UPDATE SET campaign_brief_json=excluded.campaign_brief_json,status=excluded.status,updated_at=excluded.updated_at""",
                  (int(song_id),payload,status,now(),now()))
        c.execute('UPDATE songs SET campaign_status=?, updated_at=? WHERE id=?',(status,now(),int(song_id)))
        c.commit()
    return True

def get_release_campaigns(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute("""SELECT rc.*, s.title AS song_title
                          FROM release_campaigns rc
                          LEFT JOIN songs s ON s.id=rc.song_id
                          ORDER BY rc.updated_at DESC""").fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        try:
            item['campaign_brief']=json.loads(item.get('campaign_brief_json') or '{}')
        except json.JSONDecodeError:
            item['campaign_brief']={}
        out.append(item)
    return out

def upsert_artist_reference(ref,db_path=DB_PATH):
    artist=(ref.get('artist_name') or '').strip()
    if not artist: return 0
    source=(ref.get('source') or 'manual').strip() or 'manual'
    approved=1 if ref.get('approved_by_user') in {1,True,'1','true','yes','approved'} else 0
    rejected=1 if ref.get('rejected_by_user') in {1,True,'1','true','yes','rejected'} else 0
    with connect(db_path) as c:
        c.execute("""INSERT INTO artist_references (artist_name,source,confidence_score,approved_by_user,rejected_by_user,notes,created_at,updated_at)
                     VALUES (?,?,?,?,?,?,?,?)
                     ON CONFLICT(artist_name,source) DO UPDATE SET
                     confidence_score=excluded.confidence_score,approved_by_user=excluded.approved_by_user,rejected_by_user=excluded.rejected_by_user,notes=excluded.notes,updated_at=excluded.updated_at""",
                  (artist,source,float(ref.get('confidence_score') or 0),approved,rejected,ref.get('notes',''),now(),now()))
        row=c.execute('SELECT id FROM artist_references WHERE artist_name=? AND source=?',(artist,source)).fetchone(); c.commit(); return int(row['id']) if row else 0

def bulk_upsert_artist_references(refs,db_path=DB_PATH):
    return [upsert_artist_reference(ref,db_path) for ref in refs]

def get_artist_references(db_path=DB_PATH,include_rejected=True):
    sql='SELECT * FROM artist_references'
    args=()
    if not include_rejected:
        sql+=' WHERE rejected_by_user=0'
    sql+=' ORDER BY approved_by_user DESC, confidence_score DESC, artist_name'
    with connect(db_path) as c:
        rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]
