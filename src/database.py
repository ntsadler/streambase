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
        c.execute("CREATE TABLE IF NOT EXISTS outreach_campaigns (id INTEGER PRIMARY KEY AUTOINCREMENT,song_id INTEGER DEFAULT 0,name TEXT,status TEXT DEFAULT 'draft',subject_template TEXT,body_template TEXT,specifications_json TEXT,created_at TEXT,updated_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS outreach_campaign_targets (id INTEGER PRIMARY KEY AUTOINCREMENT,campaign_id INTEGER,playlist_id INTEGER,fit_score REAL DEFAULT 0,reason TEXT,email_status TEXT DEFAULT 'pending',instagram_status TEXT DEFAULT 'pending',submission_status TEXT DEFAULT 'pending',created_at TEXT,updated_at TEXT,UNIQUE(campaign_id,playlist_id))")
        c.execute("""CREATE TABLE IF NOT EXISTS campaign_outreach_tasks (
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     song_id INTEGER,
                     playlist_id INTEGER,
                     curator_id INTEGER,
                     channel TEXT,
                     contact_destination TEXT,
                     task_status TEXT DEFAULT 'pending',
                     outcome_status TEXT DEFAULT 'pending',
                     attempted_at TEXT,
                     notes TEXT,
                     email_queue_id INTEGER DEFAULT 0,
                     campaign_id INTEGER DEFAULT 0,
                     fit_score REAL DEFAULT 0,
                     source TEXT,
                     created_at TEXT,
                     updated_at TEXT,
                     UNIQUE(song_id,playlist_id,channel,contact_destination)
                     )""")
        c.execute("CREATE TABLE IF NOT EXISTS email_replies (id INTEGER PRIMARY KEY AUTOINCREMENT,gmail_message_id TEXT UNIQUE,gmail_thread_id TEXT,email_queue_id INTEGER DEFAULT 0,curator_id INTEGER DEFAULT 0,playlist_id INTEGER DEFAULT 0,from_email TEXT,from_name TEXT,subject TEXT,snippet TEXT,received_at TEXT,match_status TEXT DEFAULT 'unmatched',created_at TEXT)")
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
        c.execute("CREATE TABLE IF NOT EXISTS mining_query_runs (id INTEGER PRIMARY KEY AUTOINCREMENT,mining_job_id INTEGER,source TEXT DEFAULT 'chartmetric',query_type TEXT,query TEXT,status TEXT DEFAULT 'planned',request_count INTEGER DEFAULT 0,result_count INTEGER DEFAULT 0,saved_count INTEGER DEFAULT 0,filtered_count INTEGER DEFAULT 0,error TEXT,raw_response_json TEXT,started_at TEXT,completed_at TEXT,updated_at TEXT,UNIQUE(mining_job_id,query_type,query))")
        c.execute("CREATE TABLE IF NOT EXISTS api_usage_events (id INTEGER PRIMARY KEY AUTOINCREMENT,source TEXT,operation TEXT,query TEXT,status_code INTEGER DEFAULT 0,request_count INTEGER DEFAULT 1,credits_used INTEGER DEFAULT 0,remaining_credits INTEGER,rate_limited INTEGER DEFAULT 0,error TEXT,created_at TEXT)")
        c.execute("CREATE TABLE IF NOT EXISTS mined_playlists (id INTEGER PRIMARY KEY AUTOINCREMENT,mining_job_id INTEGER,source TEXT DEFAULT 'chartmetric',query TEXT,playlist_name TEXT,playlist_url TEXT,curator_name TEXT,follower_count INTEGER,spotify_description TEXT,last_updated TEXT,chartmetric_playlist_id TEXT,raw_json TEXT,status TEXT DEFAULT 'mined',created_at TEXT,UNIQUE(source,playlist_url,query))")
        ensure_column(c,'playlists','intersection_score','REAL DEFAULT 0')
        ensure_column(c,'playlists','spotify_playlist_id','TEXT')
        ensure_column(c,'playlists','scoring_notes','TEXT')
        ensure_column(c,'playlists','submithub_verified','INTEGER DEFAULT 0')
        ensure_column(c,'playlists','submithub_url','TEXT')
        ensure_column(c,'email_queue','song_title','TEXT')
        ensure_column(c,'email_queue','song_url','TEXT')
        ensure_column(c,'email_queue','song_context_json','TEXT')
        ensure_column(c,'email_queue','campaign_id','INTEGER DEFAULT 0')
        ensure_column(c,'outreach_events','campaign_id','INTEGER DEFAULT 0')
        ensure_column(c,'songs','file_name','TEXT')
        ensure_column(c,'songs','artist_name','TEXT')
        ensure_column(c,'songs','spotify_url','TEXT')
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
        ensure_column(c,'mined_playlists','fit_score','REAL DEFAULT 0')
        ensure_column(c,'mined_playlists','fit_reason','TEXT')
        ensure_column(c,'mined_playlists','best_song_titles','TEXT')
        ensure_column(c,'mined_playlists','follower_tier','TEXT')
        ensure_column(c,'mined_playlists','matched_terms','TEXT')
        ensure_column(c,'mined_playlists','source_playlist_id','TEXT')
        ensure_column(c,'song_playlist_targets','source','TEXT')
        ensure_column(c,'song_playlist_targets','related_artists','TEXT')
        ensure_column(c,'song_playlist_targets','raw_json','TEXT')
        ensure_column(c,'song_playlist_targets','updated_at','TEXT')
        c.commit()

def sync_song_campaign_tasks(song_id,min_fit=70,db_path=DB_PATH):
    song_id=int(song_id or 0)
    if not song_id: return 0
    inserted=0
    with connect(db_path) as c:
        rows=c.execute("""WITH ranked_contacts AS (
                              SELECT spt.song_id,p.id AS playlist_id,p.curator_id,COALESCE(spt.fit_score,0) AS fit_score,spt.source,
                                     CASE WHEN cm.type='submission_page' THEN 'submission' ELSE cm.type END AS channel,
                                     cm.value AS contact_destination,
                                     ROW_NUMBER() OVER (
                                         PARTITION BY spt.song_id,p.id,CASE WHEN cm.type='submission_page' THEN 'submission' ELSE cm.type END
                                         ORDER BY COALESCE(cm.confidence_score,0) DESC,cm.created_at DESC,cm.id DESC
                                     ) AS contact_rank
                              FROM song_playlist_targets spt
                              JOIN playlists p ON p.url=spt.playlist_url
                              JOIN curators cur ON cur.id=p.curator_id
                              JOIN contact_methods cm ON cm.curator_id=p.curator_id
                              WHERE spt.song_id=?
                                AND COALESCE(spt.fit_score,0)>=?
                                AND lower(cur.name) NOT IN ('unknown curator','spotify')
                                AND cm.type IN ('email','instagram','submission_page')
                                AND COALESCE(cm.status,'new') NOT LIKE 'quarantined%'
                                AND COALESCE(cm.value,'')!=''
                          ),
                          primary_playlist_contacts AS (
                              SELECT * FROM ranked_contacts WHERE contact_rank=1
                          ),
                          ranked_routes AS (
                              SELECT *,
                                     ROW_NUMBER() OVER (
                                         PARTITION BY song_id,channel,lower(contact_destination)
                                         ORDER BY fit_score DESC,playlist_id DESC
                                     ) AS route_rank
                              FROM primary_playlist_contacts
                          )
                          SELECT * FROM ranked_routes WHERE route_rank=1""",(song_id,float(min_fit or 0))).fetchall()
        for row in rows:
            channel=row['channel']
            cur=c.execute("""INSERT OR IGNORE INTO campaign_outreach_tasks
                             (song_id,playlist_id,curator_id,channel,contact_destination,task_status,outcome_status,fit_score,source,created_at,updated_at)
                             VALUES (?,?,?,?,?,'pending','pending',?,?,?,?)""",
                          (song_id,int(row['playlist_id'] or 0),int(row['curator_id'] or 0),channel,row['contact_destination'],
                           float(row['fit_score'] or 0),row['source'] or 'song_playlist_targets',now(),now()))
            inserted+=cur.rowcount
        c.commit()
    return inserted

def get_song_campaign_tasks(song_id=None,db_path=DB_PATH):
    args=[]
    where=''
    if song_id is not None:
        where='WHERE t.song_id=?'
        args.append(int(song_id or 0))
    sql=f"""SELECT t.*,s.title AS song_title,s.artist_name,s.spotify_url,
                   p.name AS playlist_name,p.url AS playlist_url,p.followers,c.display_name AS curator_name,
                   q.status AS email_queue_status,
                   CASE WHEN EXISTS (SELECT 1 FROM email_replies r WHERE r.email_queue_id=t.email_queue_id) THEN 1 ELSE 0 END AS has_email_reply
            FROM campaign_outreach_tasks t
            LEFT JOIN songs s ON s.id=t.song_id
            LEFT JOIN playlists p ON p.id=t.playlist_id
            LEFT JOIN curators c ON c.id=t.curator_id
            LEFT JOIN email_queue q ON q.id=t.email_queue_id
            {where}
            ORDER BY t.task_status='completed',t.fit_score DESC,p.name,t.channel"""
    with connect(db_path) as c:
        rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]

def update_campaign_outreach_task(task_id,task_status=None,outcome_status=None,attempted=False,notes=None,email_queue_id=None,db_path=DB_PATH):
    with connect(db_path) as c:
        row=c.execute('SELECT * FROM campaign_outreach_tasks WHERE id=?',(int(task_id),)).fetchone()
        if not row: return 0
        c.execute("""UPDATE campaign_outreach_tasks
                     SET task_status=?,
                         outcome_status=?,
                         attempted_at=CASE WHEN ? THEN COALESCE(attempted_at,?) ELSE attempted_at END,
                         notes=?,
                         email_queue_id=?,
                         updated_at=?
                     WHERE id=?""",
                  (task_status if task_status is not None else row['task_status'],
                   outcome_status if outcome_status is not None else row['outcome_status'],
                   1 if attempted else 0,now(),
                   notes if notes is not None else row['notes'],
                   int(email_queue_id if email_queue_id is not None else row['email_queue_id'] or 0),
                   now(),int(task_id)))
        c.commit()
        return int(task_id)

def get_song_campaign_overview(db_path=DB_PATH):
    songs=get_release_songs(db_path)
    with connect(db_path) as c:
        rows=c.execute("""SELECT song_id,
                          COUNT(*) AS total_tasks,
                          SUM(CASE WHEN task_status='completed' THEN 1 ELSE 0 END) AS completed_tasks,
                          SUM(CASE WHEN channel='email' THEN 1 ELSE 0 END) AS email_tasks,
                          SUM(CASE WHEN channel='email' AND task_status='completed' THEN 1 ELSE 0 END) AS email_completed,
                          SUM(CASE WHEN channel='instagram' THEN 1 ELSE 0 END) AS instagram_tasks,
                          SUM(CASE WHEN channel='instagram' AND task_status='completed' THEN 1 ELSE 0 END) AS instagram_completed,
                          SUM(CASE WHEN channel='submission' THEN 1 ELSE 0 END) AS submission_tasks,
                          SUM(CASE WHEN channel='submission' AND task_status='completed' THEN 1 ELSE 0 END) AS submission_completed
                          FROM campaign_outreach_tasks GROUP BY song_id""").fetchall()
    stats={int(r['song_id'] or 0):dict(r) for r in rows}
    overview=[]
    for song in songs:
        song_id=int(song.get('id') or 0)
        stat=stats.get(song_id,{})
        total=int(stat.get('total_tasks') or 0)
        completed=int(stat.get('completed_tasks') or 0)
        if total==0 or completed==0:
            status='Campaign Not Started'
            indicator='🔴'
        elif completed>=total:
            status='Campaign Finished'
            indicator='✅'
        else:
            status='Campaign In Progress'
            indicator='🟡'
        overview.append({**song,**stat,'total_tasks':total,'completed_tasks':completed,'campaign_task_status':status,'campaign_indicator':indicator,'completion_pct':round((completed/total)*100,1) if total else 0})
    return overview
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
    url=item.get('url') or item.get('playlist_url') or ''
    incoming_curator=(item.get('curator') or item.get('curator_name') or '').strip()
    incoming_unknown=not incoming_curator or incoming_curator.lower() in {'unknown','unknown curator'}
    with connect(db_path) as c:
        existing=c.execute('SELECT curator_id FROM playlists WHERE url=?',(url,)).fetchone()
    if incoming_unknown and existing and int(existing['curator_id'] or 0):
        curator_id=int(existing['curator_id'] or 0)
    else:
        curator_id=get_or_create_curator(incoming_curator or 'Unknown Curator',db_path)
    with connect(db_path) as c:
        c.execute("""INSERT OR REPLACE INTO playlists (curator_id,name,url,platform,followers,related_artists,spotify_description,similarity_score,intersection_score,final_score,priority,status,created_at,spotify_playlist_id,scoring_notes,submithub_verified,submithub_url) VALUES (?,?,?,COALESCE((SELECT platform FROM playlists WHERE url=?),'spotify'),?,?,?,?,?,?,?,COALESCE((SELECT status FROM playlists WHERE url=?),'new'),COALESCE((SELECT created_at FROM playlists WHERE url=?),?),?,?,?,?)""",(curator_id,item.get('name') or item.get('playlist_name'),url,url,int(item.get('followers') or item.get('follower_count') or 0),item.get('related_artists',''),item.get('spotify_description',''),item.get('similarity_score',0),item.get('intersection_score',0),item.get('final_score',0),item.get('priority','new'),url,url,now(),item.get('spotify_playlist_id',''),item.get('scoring_notes',''),1 if item.get('submithub_verified') else 0,item.get('submithub_url','')))
        row=c.execute('SELECT id FROM playlists WHERE url=?',(url,)).fetchone(); c.commit(); return int(row['id']) if row else 0
def upsert_contact_method(curator_id,m,db_path=DB_PATH):
    if not m.get('value') or not m.get('type'): return
    with connect(db_path) as c:
        c.execute("INSERT OR IGNORE INTO contact_methods (curator_id,type,value,source_url,confidence_score,status,created_at) VALUES (?,?,?,?,?,?,?)",(curator_id,m.get('type'),m.get('value'),m.get('source_url',''),int(m.get('confidence_score') or 0),m.get('status','new'),now())); c.commit()
def add_outreach_event(curator_id,playlist_id,channel,event_type,message='',db_path=DB_PATH,campaign_id=0):
    with connect(db_path) as c:
        c.execute('INSERT INTO outreach_events (curator_id,playlist_id,channel,event_type,message,created_at,campaign_id) VALUES (?,?,?,?,?,?,?)',(curator_id,playlist_id,channel,event_type,message,now(),int(campaign_id or 0))); c.commit()
def get_outreach_events_for_playlists(playlist_ids,db_path=DB_PATH):
    ids=[int(x) for x in playlist_ids if x]
    if not ids: return []
    marks=','.join(['?']*len(ids))
    with connect(db_path) as c:
        rows=c.execute(f'SELECT * FROM outreach_events WHERE playlist_id IN ({marks}) ORDER BY created_at DESC',ids).fetchall()
    return [dict(r) for r in rows]
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
def queue_email(curator_id,playlist_id,to_email,subject,body,db_path=DB_PATH,song_context=None,cooldown_days=30,enforce_cooldown=True,campaign_id=0):
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
        cur=c.execute('INSERT INTO email_queue (curator_id,playlist_id,to_email,subject,body,status,created_at,updated_at,song_title,song_url,song_context_json,campaign_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(curator_id,playlist_id,to_email,subject,body,'pending_approval',now(),now(),song_title,song_url,song_json,int(campaign_id or 0)))
        c.commit(); return int(cur.lastrowid)
def update_email_queue_status(queue_id,status,db_path=DB_PATH):
    with connect(db_path) as c: c.execute('UPDATE email_queue SET status=?, updated_at=? WHERE id=?',(status,now(),queue_id)); c.commit()
def update_email_queue_after_send(queue_id,status,provider_id='',error='',db_path=DB_PATH):
    note=json.dumps({'provider_id':provider_id,'error':error},ensure_ascii=True)
    with connect(db_path) as c:
        c.execute('UPDATE email_queue SET status=?, updated_at=?, song_context_json=CASE WHEN ?!="" THEN ? ELSE song_context_json END WHERE id=?',(status,now(),note,note,queue_id))
        c.commit()
def get_email_queue(status=None,db_path=DB_PATH):
    sql="""SELECT q.*, c.display_name AS curator_name, p.name AS playlist_name, p.url AS playlist_url,
                  oc.name AS campaign_name, oc.song_id AS campaign_song_id
           FROM email_queue q
           LEFT JOIN curators c ON q.curator_id=c.id
           LEFT JOIN playlists p ON q.playlist_id=p.id
           LEFT JOIN outreach_campaigns oc ON q.campaign_id=oc.id"""
    args=()
    if status: sql+=' WHERE q.status=?'; args=(status,)
    sql+=' ORDER BY q.created_at DESC'
    with connect(db_path) as c: rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]

def create_outreach_campaign(song_id,name,subject_template,body_template,specifications=None,status='draft',db_path=DB_PATH):
    clean_name=(name or 'Untitled Campaign').strip() or 'Untitled Campaign'
    with connect(db_path) as c:
        cur=c.execute("""INSERT INTO outreach_campaigns (song_id,name,status,subject_template,body_template,specifications_json,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?)""",
                      (int(song_id or 0),clean_name,status,subject_template or '',body_template or '',json.dumps(specifications or {},ensure_ascii=True),now(),now()))
        c.commit()
        return int(cur.lastrowid)

def update_outreach_campaign(campaign_id,name=None,subject_template=None,body_template=None,specifications=None,status=None,db_path=DB_PATH):
    with connect(db_path) as c:
        row=c.execute('SELECT * FROM outreach_campaigns WHERE id=?',(int(campaign_id),)).fetchone()
        if not row: return 0
        c.execute("""UPDATE outreach_campaigns
                     SET name=?,subject_template=?,body_template=?,specifications_json=?,status=?,updated_at=?
                     WHERE id=?""",
                  ((name if name is not None else row['name']),
                   (subject_template if subject_template is not None else row['subject_template']),
                   (body_template if body_template is not None else row['body_template']),
                   json.dumps(specifications,ensure_ascii=True) if specifications is not None else (row['specifications_json'] or '{}'),
                   (status if status is not None else row['status']),now(),int(campaign_id)))
        c.commit()
        return int(campaign_id)

def get_outreach_campaigns(db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute("""SELECT oc.*,s.title AS song_title,s.artist_name,
                          (SELECT COUNT(*) FROM email_queue q WHERE q.campaign_id=oc.id) AS email_count,
                          (SELECT COUNT(*) FROM email_queue q WHERE q.campaign_id=oc.id AND q.status='sent') AS sent_count,
                          (SELECT COUNT(*) FROM email_queue q WHERE q.campaign_id=oc.id AND q.status='approved') AS approved_count
                          FROM outreach_campaigns oc
                          LEFT JOIN songs s ON s.id=oc.song_id
                          ORDER BY oc.updated_at DESC,oc.id DESC""").fetchall()
    result=[]
    for row in rows:
        item=dict(row)
        try: item['specifications']=json.loads(item.get('specifications_json') or '{}')
        except json.JSONDecodeError: item['specifications']={}
        result.append(item)
    return result

def save_outreach_campaign_targets(campaign_id,rows,db_path=DB_PATH):
    saved=0
    with connect(db_path) as c:
        for row in rows or []:
            raw=row.get('raw') if isinstance(row.get('raw'),dict) else {}
            playlist_id=int(row.get('playlist_id') or raw.get('playlist_id') or row.get('id') or 0)
            if not playlist_id: continue
            c.execute("""INSERT INTO outreach_campaign_targets (campaign_id,playlist_id,fit_score,reason,email_status,instagram_status,submission_status,created_at,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(campaign_id,playlist_id) DO UPDATE SET fit_score=excluded.fit_score,reason=excluded.reason,updated_at=excluded.updated_at""",
                      (int(campaign_id),playlist_id,float(row.get('fit_score') or row.get('relevance_score') or row.get('final_score') or 0),row.get('reason') or '',
                       'pending' if row.get('email') else 'unavailable','pending' if row.get('instagram') else 'unavailable','pending' if row.get('submission_page') else 'unavailable',now(),now()))
            saved+=1
        c.commit()
    return saved

def get_outreach_campaign_targets(campaign_id,db_path=DB_PATH):
    with connect(db_path) as c:
        rows=c.execute("""SELECT ct.*,p.name AS playlist_name,p.url AS playlist_url,p.followers,p.curator_id,c.display_name AS curator_name,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='email' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS email,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='instagram' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS instagram,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='submission_page' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC,created_at DESC LIMIT 1) AS submission_page
                  FROM outreach_campaign_targets ct
                  JOIN playlists p ON p.id=ct.playlist_id
                  LEFT JOIN curators c ON c.id=p.curator_id
                  WHERE ct.campaign_id=?
                  ORDER BY ct.fit_score DESC,p.name""",(int(campaign_id),)).fetchall()
    return [dict(row) for row in rows]

def update_outreach_campaign_target_status(campaign_id,playlist_id,channel,status='done',db_path=DB_PATH):
    columns={'email':'email_status','instagram':'instagram_status','submission':'submission_status'}
    column=columns.get(channel)
    if not column: return 0
    with connect(db_path) as c:
        cur=c.execute(f'UPDATE outreach_campaign_targets SET {column}=?,updated_at=? WHERE campaign_id=? AND playlist_id=?',(status,now(),int(campaign_id),int(playlist_id)))
        c.commit()
        return cur.rowcount
def upsert_email_reply(reply,db_path=DB_PATH):
    if not reply.get('gmail_message_id'): return 0
    with connect(db_path) as c:
        c.execute("""INSERT INTO email_replies (gmail_message_id,gmail_thread_id,email_queue_id,curator_id,playlist_id,from_email,from_name,subject,snippet,received_at,match_status,created_at)
                     VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(gmail_message_id) DO UPDATE SET
                     gmail_thread_id=excluded.gmail_thread_id,
                     email_queue_id=excluded.email_queue_id,
                     curator_id=excluded.curator_id,
                     playlist_id=excluded.playlist_id,
                     from_email=excluded.from_email,
                     from_name=excluded.from_name,
                     subject=excluded.subject,
                     snippet=excluded.snippet,
                     received_at=excluded.received_at,
                     match_status=excluded.match_status""",
                  (reply.get('gmail_message_id',''),reply.get('gmail_thread_id',''),int(reply.get('email_queue_id') or 0),int(reply.get('curator_id') or 0),int(reply.get('playlist_id') or 0),reply.get('from_email',''),reply.get('from_name',''),reply.get('subject',''),reply.get('snippet',''),reply.get('received_at',''),reply.get('match_status','unmatched'),now()))
        row=c.execute('SELECT id FROM email_replies WHERE gmail_message_id=?',(reply.get('gmail_message_id',''),)).fetchone()
        c.commit()
        return int(row['id']) if row else 0
def get_email_replies(db_path=DB_PATH):
    sql="""SELECT r.*, q.to_email, q.song_title, q.campaign_id, oc.name AS campaign_name,
                  p.name AS playlist_name, p.url AS playlist_url, c.display_name AS curator_name
           FROM email_replies r
           LEFT JOIN email_queue q ON r.email_queue_id=q.id
           LEFT JOIN playlists p ON r.playlist_id=p.id
           LEFT JOIN curators c ON r.curator_id=c.id
           LEFT JOIN outreach_campaigns oc ON q.campaign_id=oc.id
           ORDER BY r.received_at DESC, r.created_at DESC"""
    with connect(db_path) as c:
        rows=c.execute(sql).fetchall()
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
        legacy=[dict(r) for r in c.execute('SELECT * FROM song_fit_targets ORDER BY created_at DESC, fit_score DESC').fetchall()]
        table_names={r['name'] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        if 'viberate_cyanite_playlist_matches' in table_names:
            catalog_sql="""WITH viberate_match_summary AS (
                    SELECT catalog_song_id,playlist_url,
                           MAX(playlist_name) AS mined_playlist_name,
                           MAX(curator_name) AS mined_curator_name,
                           MAX(follower_count) AS mined_follower_count,
                           COUNT(DISTINCT seed_artist) AS seed_match_count,
                           GROUP_CONCAT(DISTINCT seed_artist) AS cyanite_seed_artists,
                           MIN(seed_rank) AS best_seed_rank,
                           MAX(fit_score) AS viberate_fit_score
                    FROM viberate_cyanite_playlist_matches
                    GROUP BY catalog_song_id,playlist_url
                )
                SELECT spt.id,spt.song_id,s.title AS song_title,s.artist_name,
                       COALESCE(NULLIF(spt.playlist_name,''),vms.mined_playlist_name) AS playlist_name,
                       spt.playlist_url,p.curator_id,
                       COALESCE(c.display_name,vms.mined_curator_name) AS curator_name,
                       COALESCE(p.followers,vms.mined_follower_count,0) AS follower_count,
                       MAX(COALESCE(spt.fit_score,0),COALESCE(vms.viberate_fit_score,0)) AS fit_score,
                       spt.status,spt.notes,spt.created_at,spt.source,spt.related_artists,spt.raw_json,spt.updated_at,
                       COALESCE(vms.seed_match_count,0) AS seed_match_count,
                       COALESCE(vms.cyanite_seed_artists,'') AS cyanite_seed_artists,
                       COALESCE(vms.best_seed_rank,0) AS best_seed_rank
                FROM song_playlist_targets spt
                LEFT JOIN songs s ON s.id=spt.song_id
                LEFT JOIN playlists p ON p.url=spt.playlist_url
                LEFT JOIN curators c ON c.id=p.curator_id
                LEFT JOIN viberate_match_summary vms ON vms.catalog_song_id=spt.song_id AND vms.playlist_url=spt.playlist_url
                ORDER BY spt.created_at DESC, fit_score DESC"""
        else:
            catalog_sql="""SELECT spt.id,spt.song_id,s.title AS song_title,s.artist_name,
                         spt.playlist_name,spt.playlist_url,p.curator_id,c.display_name AS curator_name,
                         COALESCE(p.followers,0) AS follower_count,
                         spt.fit_score,spt.status,spt.notes,spt.created_at,spt.source,spt.related_artists,spt.raw_json,spt.updated_at,
                         0 AS seed_match_count,'' AS cyanite_seed_artists,0 AS best_seed_rank
                  FROM song_playlist_targets spt
                  LEFT JOIN songs s ON s.id=spt.song_id
                  LEFT JOIN playlists p ON p.url=spt.playlist_url
                  LEFT JOIN curators c ON c.id=p.curator_id
                  ORDER BY spt.created_at DESC, spt.fit_score DESC"""
        catalog=[dict(r) for r in c.execute(catalog_sql).fetchall()]
    seen=set()
    merged=[]
    for row in catalog+legacy:
        key=(int(row.get('song_id') or 0),str(row.get('song_title') or '').strip().lower(),str(row.get('artist_name') or '').strip().lower(),row.get('playlist_url') or '')
        if key in seen:
            continue
        seen.add(key)
        merged.append(row)
    return merged

def save_song_playlist_target(song_id,playlist,source='manual',fit_score=0,status='target',notes='',db_path=DB_PATH):
    playlist_url=playlist.get('playlist_url') or playlist.get('url') or ''
    playlist_name=playlist.get('playlist_name') or playlist.get('name') or ''
    if not int(song_id or 0) or not playlist_url:
        return 0
    raw=playlist.get('raw_json') or playlist.get('raw') or {}
    if not isinstance(raw,str):
        raw=json.dumps(raw,ensure_ascii=True)
    with connect(db_path) as c:
        cur=c.execute("""INSERT INTO song_playlist_targets
                         (song_id,playlist_name,playlist_url,fit_score,status,notes,created_at,source,related_artists,raw_json,updated_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?)
                         ON CONFLICT(song_id,playlist_url) DO UPDATE SET
                         playlist_name=excluded.playlist_name,
                         fit_score=max(song_playlist_targets.fit_score,excluded.fit_score),
                         status=excluded.status,
                         notes=excluded.notes,
                         source=excluded.source,
                         related_artists=excluded.related_artists,
                         raw_json=excluded.raw_json,
                         updated_at=excluded.updated_at""",
                      (int(song_id),playlist_name,playlist_url,float(fit_score or playlist.get('fit_score') or playlist.get('candidate_fit_score') or 0),status,notes or playlist.get('notes',''),now(),source,playlist.get('related_artists',''),raw,now()))
        row=c.execute('SELECT id FROM song_playlist_targets WHERE song_id=? AND playlist_url=?',(int(song_id),playlist_url)).fetchone()
        c.commit()
        return int(row['id']) if row else int(cur.lastrowid)

def import_song_seed_playlists(song_id,playlists,source='cyanite_seed',db_path=DB_PATH):
    saved=[]
    seen=set()
    for playlist in playlists or []:
        url=playlist.get('playlist_url') or playlist.get('url') or ''
        if not url or url in seen:
            continue
        seen.add(url)
        playlist_id=upsert_playlist(playlist,db_path)
        target_id=save_song_playlist_target(song_id,playlist,source=source,fit_score=playlist.get('fit_score') or playlist.get('candidate_fit_score') or 85,status='target',notes=f'Imported from {source}',db_path=db_path)
        saved.append({'playlist_id':playlist_id,'target_id':target_id,'playlist_url':url,'playlist_name':playlist.get('playlist_name') or playlist.get('name') or ''})
    return saved
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
        rows=c.execute("""SELECT p.*, c.display_name AS curator_name,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='email' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS email,
                  (SELECT confidence_score FROM contact_methods WHERE curator_id=p.curator_id AND type='email' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS email_confidence,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='instagram' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS instagram,
                  (SELECT confidence_score FROM contact_methods WHERE curator_id=p.curator_id AND type='instagram' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS instagram_confidence,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='submission_page' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS submission_page,
                  (SELECT confidence_score FROM contact_methods WHERE curator_id=p.curator_id AND type='submission_page' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS submission_confidence,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='website' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS website,
                  (SELECT value FROM contact_methods WHERE curator_id=p.curator_id AND type='link_hub' AND COALESCE(status,'new') NOT LIKE 'quarantined%' ORDER BY confidence_score DESC, created_at DESC LIMIT 1) AS link_hub
           FROM playlists p
           LEFT JOIN curators c ON p.curator_id=c.id
           ORDER BY p.final_score DESC""").fetchall()
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

def get_mining_job(job_id,db_path=DB_PATH):
    with connect(db_path) as c:
        row=c.execute('SELECT * FROM mining_jobs WHERE id=?',(int(job_id),)).fetchone()
    return dict(row) if row else {}

def plan_mining_query_runs(job_id,queries,source='chartmetric',db_path=DB_PATH):
    planned=0
    with connect(db_path) as c:
        for item in queries or []:
            query_type=item.get('type') or item.get('query_type') or 'query'
            query=' '.join(str(item.get('query') or '').split())
            if not query: continue
            cur=c.execute("""INSERT OR IGNORE INTO mining_query_runs (mining_job_id,source,query_type,query,status,request_count,result_count,saved_count,filtered_count,error,raw_response_json,updated_at)
                             VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (int(job_id),source,query_type,query,'planned',0,0,0,0,'','',now()))
            planned+=cur.rowcount
        c.commit()
    return planned

def get_mining_query_runs(job_id,statuses=None,db_path=DB_PATH):
    args=[int(job_id)]
    sql='SELECT * FROM mining_query_runs WHERE mining_job_id=?'
    if statuses:
        marks=','.join(['?']*len(statuses))
        sql+=f' AND status IN ({marks})'
        args.extend(statuses)
    sql+=' ORDER BY id'
    with connect(db_path) as c:
        rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]

def update_mining_query_run(query_run_id,status=None,request_count=None,result_count=None,saved_count=None,filtered_count=None,error=None,raw_response=None,started=False,completed=False,db_path=DB_PATH):
    with connect(db_path) as c:
        current=c.execute('SELECT * FROM mining_query_runs WHERE id=?',(int(query_run_id),)).fetchone()
        if not current: return 0
        raw=current['raw_response_json'] or ''
        if raw_response is not None:
            raw=raw_response if isinstance(raw_response,str) else json.dumps(raw_response,ensure_ascii=True)
        c.execute("""UPDATE mining_query_runs
                     SET status=?,request_count=?,result_count=?,saved_count=?,filtered_count=?,error=?,raw_response_json=?,
                         started_at=CASE WHEN ? THEN COALESCE(started_at,?) ELSE started_at END,
                         completed_at=CASE WHEN ? THEN ? ELSE completed_at END,
                         updated_at=?
                     WHERE id=?""",
                  (status if status is not None else current['status'],
                   int(request_count if request_count is not None else current['request_count'] or 0),
                   int(result_count if result_count is not None else current['result_count'] or 0),
                   int(saved_count if saved_count is not None else current['saved_count'] or 0),
                   int(filtered_count if filtered_count is not None else current['filtered_count'] or 0),
                   error if error is not None else current['error'],
                   raw,1 if started else 0,now(),1 if completed else 0,now(),now(),int(query_run_id)))
        c.commit(); return int(query_run_id)

def log_api_usage_event(source,operation,query='',status_code=0,request_count=1,credits_used=0,remaining_credits=None,rate_limited=False,error='',db_path=DB_PATH):
    with connect(db_path) as c:
        cur=c.execute("""INSERT INTO api_usage_events (source,operation,query,status_code,request_count,credits_used,remaining_credits,rate_limited,error,created_at)
                         VALUES (?,?,?,?,?,?,?,?,?,?)""",
                      (source,operation,query,int(status_code or 0),int(request_count or 0),int(credits_used or 0),remaining_credits,1 if rate_limited else 0,error or '',now()))
        c.commit(); return int(cur.lastrowid)

def get_api_usage_events(source=None,db_path=DB_PATH):
    args=()
    sql='SELECT * FROM api_usage_events'
    if source:
        sql+=' WHERE source=?'; args=(source,)
    sql+=' ORDER BY created_at DESC,id DESC'
    with connect(db_path) as c:
        rows=c.execute(sql,args).fetchall()
    return [dict(r) for r in rows]

def save_mined_playlist(job_id,playlist,db_path=DB_PATH):
    source_playlist_id=playlist.get('source_playlist_id') or playlist.get('chartmetric_playlist_id') or ''
    if not playlist.get('playlist_url') and not source_playlist_id: return 0
    raw=playlist.get('raw_json') or playlist.get('raw') or {}
    if not isinstance(raw,str): raw=json.dumps(raw,ensure_ascii=True)
    with connect(db_path) as c:
        cur=c.execute("""INSERT OR IGNORE INTO mined_playlists (mining_job_id,source,query,playlist_name,playlist_url,curator_name,follower_count,spotify_description,last_updated,chartmetric_playlist_id,source_playlist_id,raw_json,status,created_at,fit_score,fit_reason,best_song_titles,follower_tier,matched_terms)
                         VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (int(job_id),playlist.get('source','chartmetric'),playlist.get('search_query') or playlist.get('query',''),playlist.get('playlist_name',''),playlist.get('playlist_url',''),playlist.get('curator_name',''),int(playlist.get('follower_count') or 0),playlist.get('spotify_description',''),playlist.get('last_updated',''),playlist.get('chartmetric_playlist_id',''),source_playlist_id,raw,playlist.get('status','mined'),now(),float(playlist.get('fit_score') or 0),playlist.get('fit_reason',''),playlist.get('best_song_titles',''),playlist.get('follower_tier',''),playlist.get('matched_terms','')))
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
        c.execute("""INSERT INTO songs (title,file_path,release_status,planned_release_date,campaign_status,created_at,updated_at,file_name,artist_name,spotify_url)
                     VALUES (?,?,?,?,?,?,?,?,?,?)
                     ON CONFLICT(file_path) DO UPDATE SET
                     title=excluded.title,release_status=excluded.release_status,planned_release_date=excluded.planned_release_date,campaign_status=excluded.campaign_status,updated_at=excluded.updated_at,file_name=excluded.file_name,artist_name=excluded.artist_name,spotify_url=excluded.spotify_url""",
                  (song.get('title',''),file_path,song.get('release_status','unreleased') or 'unreleased',song.get('planned_release_date',''),song.get('campaign_status','needs_profile') or 'needs_profile',now(),now(),file_name,song.get('artist_name',''),song.get('spotify_url','')))
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
