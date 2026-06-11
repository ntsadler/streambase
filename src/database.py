import sqlite3
from pathlib import Path
from datetime import UTC, datetime
from src.settings import DB_PATH
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
        ensure_column(c,'playlists','intersection_score','REAL DEFAULT 0')
        ensure_column(c,'playlists','spotify_playlist_id','TEXT')
        ensure_column(c,'playlists','scoring_notes','TEXT')
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
        c.execute("""INSERT OR REPLACE INTO playlists (curator_id,name,url,platform,followers,related_artists,spotify_description,similarity_score,intersection_score,final_score,priority,status,created_at,spotify_playlist_id,scoring_notes) VALUES (?,?,?,COALESCE((SELECT platform FROM playlists WHERE url=?),'spotify'),?,?,?,?,?,?,?,COALESCE((SELECT status FROM playlists WHERE url=?),'new'),COALESCE((SELECT created_at FROM playlists WHERE url=?),?),?,?)""",(curator_id,item.get('name') or item.get('playlist_name'),url,url,int(item.get('followers') or item.get('follower_count') or 0),item.get('related_artists',''),item.get('spotify_description',''),item.get('similarity_score',0),item.get('intersection_score',0),item.get('final_score',0),item.get('priority','new'),url,url,now(),item.get('spotify_playlist_id',''),item.get('scoring_notes','')))
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
def queue_email(curator_id,playlist_id,to_email,subject,body,db_path=DB_PATH):
    if not to_email or not body: return 0
    with connect(db_path) as c:
        row=c.execute("SELECT id FROM email_queue WHERE curator_id=? AND playlist_id=? AND to_email=? AND status='pending_approval'",(curator_id,playlist_id,to_email)).fetchone()
        if row: return int(row['id'])
        cur=c.execute('INSERT INTO email_queue (curator_id,playlist_id,to_email,subject,body,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?)',(curator_id,playlist_id,to_email,subject,body,'pending_approval',now(),now()))
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
