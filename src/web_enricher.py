import re
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus, urlparse, unquote
import requests
from bs4 import BeautifulSoup
from src.submithub import is_submithub_url, submithub_signal_from_methods
EMAIL_RE=re.compile(r'[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}',re.I)
HEADERS={'User-Agent':'Mozilla/5.0 streambase/0.4'}
def safe_get(url,timeout=8):
    try:
        r=requests.get(url,headers=HEADERS,timeout=timeout)
        return None if r.status_code>=400 else r.text
    except requests.RequestException: return None
def safe_get_json(url,timeout=8):
    try:
        r=requests.get(url,headers=HEADERS,timeout=timeout)
        return {} if r.status_code>=400 else r.json()
    except Exception: return {}
def clean_duckduckgo_url(url):
    if 'uddg=' in url:
        m=re.search(r'uddg=([^&]+)',url)
        if m: return unquote(m.group(1))
    return url
def duckduckgo_search(q): return safe_get(f'https://duckduckgo.com/html/?q={quote_plus(q)}') or ''
def fetch_spotify_public_meta(playlist_url):
    meta={'title':'','description':'','author_name':'','thumbnail_url':''}
    if not playlist_url: return meta
    data=safe_get_json(f'https://open.spotify.com/oembed?url={quote_plus(playlist_url)}')
    if data:
        meta['title']=(data.get('title') or '').strip(); meta['author_name']=(data.get('author_name') or '').strip(); meta['thumbnail_url']=(data.get('thumbnail_url') or '').strip()
    html=safe_get(playlist_url) or ''
    if html:
        soup=BeautifulSoup(html,'html.parser')
        og=soup.find('meta',property='og:title')
        if og and og.get('content') and not meta['title']: meta['title']=og['content'].strip()
        od=soup.find('meta',property='og:description')
        if od and od.get('content'): meta['description']=od['content'].strip()
    if ' - playlist by ' in meta['title'].lower():
        parts=re.split(r'\s+-\s+playlist by\s+',meta['title'],flags=re.I)
        meta['title']=parts[0].strip()
        if len(parts)>1 and not meta['author_name']: meta['author_name']=parts[1].strip()
    return meta
def enrich_playlist_from_url(url):
    m=fetch_spotify_public_meta(url)
    return {'playlist_name':m.get('title',''),'curator_name':m.get('author_name',''),'spotify_description':m.get('description',''),'thumbnail_url':m.get('thumbnail_url','')}
def enrich_track_from_url(url):
    m=fetch_spotify_public_meta(url)
    title=m.get('title','')
    artist=m.get('author_name','')
    if ' - song by ' in title.lower():
        parts=re.split(r'\s+-\s+song by\s+',title,flags=re.I)
        title=parts[0].strip()
        if len(parts)>1 and not artist: artist=parts[1].strip()
    return {'title':title,'artist':artist,'reference_artists':artist,'descriptors':m.get('description',''),'thumbnail_url':m.get('thumbnail_url',''),'source':'spotify_oembed'}
def looks_submit(url,text=''):
    hay=f'{url} {text}'.lower()
    return any(k in hay for k in ['submit','submission','playlist submission','music submission','submithub','groover','toneden','hypeddit','daily playlists','send your music'])
def method(t,v,src,conf): return {'type':t,'value':v,'source_url':src,'confidence_score':max(0,min(100,int(conf))),'status':'new'}
def score_contact_method(t,v,src,base):
    low=f'{v} {src}'.lower(); score=base
    if t=='email':
        if src.startswith('mailto:') or 'mailto:' in src: score+=12
        if any(x in low for x in ['gmail.com','icloud.com','outlook.com','hotmail.com']): score+=4
        if any(x in low for x in ['support@','info@','hello@','contact@']): score-=8
        if any(x in low for x in ['example.com','domain.com']): score-=40
    if t=='submission_page' and any(x in low for x in ['submithub','groover','dailyplaylists']): score+=12
    if t=='submission_page' and (is_submithub_url(v) or is_submithub_url(src)): score+=8
    if t=='instagram' and 'instagram.com' in low: score+=5
    if src not in {'duckduckgo_search',''} and t in {'email','instagram','submission_page'}: score+=8
    return max(0,min(100,score))
def enrich_contact_info(playlist_name,curator_name='',playlist_url=''):
    spot={}
    if playlist_url:
        spot=fetch_spotify_public_meta(playlist_url); playlist_name=playlist_name or spot.get('title',''); curator_name=curator_name or spot.get('author_name','')
    q=f'{playlist_name} {curator_name} Spotify playlist curator contact Instagram email Linktree submission'.strip() or f'{playlist_url} playlist curator contact email Instagram submission'
    html=duckduckgo_search(q); soup=BeautifulSoup(html,'html.parser'); text=soup.get_text(' ',strip=True)
    links=[clean_duckduckgo_url(a.get('href','')) for a in soup.find_all('a') if a.get('href')]
    methods=[]; seen=set()
    def add(t,v,src,conf):
        if not v or (t,v) in seen: return
        seen.add((t,v)); methods.append(method(t,v,src,score_contact_method(t,v,src,conf)))
    for email in EMAIL_RE.findall(text): add('email',email,'duckduckgo_search',75)
    for link in links:
        low=link.lower()
        if 'instagram.com' in low: add('instagram',link,'duckduckgo_search',75)
        elif any(x in low for x in ['linktr.ee','linktree','beacons.ai','carrd.co']): add('link_hub',link,'duckduckgo_search',70)
        elif any(x in low for x in ['submithub.com','groover.co','dailyplaylists.com']) or looks_submit(link): add('submission_page',link,'duckduckgo_search',80 if any(x in low for x in ['submithub','groover','dailyplaylists']) else 58)
        elif low.startswith('http'):
            dom=urlparse(link).netloc.lower()
            if not any(b in dom for b in ['duckduckgo','spotify','google','bing','yahoo']): add('website',link,'duckduckgo_search',50)
    for target in [m['value'] for m in methods if m['type'] in {'link_hub','website','submission_page'}][:5]:
        page=safe_get(target) or ''
        if not page: continue
        ps=BeautifulSoup(page,'html.parser'); pt=ps.get_text(' ',strip=True)
        for email in EMAIL_RE.findall(pt): add('email',email,target,88)
        for a in ps.find_all('a'):
            href=a.get('href',''); label=a.get_text(' ',strip=True)
            if href.startswith('mailto:'): add('email',href.replace('mailto:','').split('?')[0],f'mailto:{target}',95)
            elif 'instagram.com' in href.lower(): add('instagram',href,target,82)
            elif any(x in href.lower() for x in ['submithub.com','groover.co','dailyplaylists.com']) or looks_submit(href,label): add('submission_page',href,target,85)
    best={k:next((m['value'] for m in methods if m['type']==k),None) for k in ['email','instagram','website','submission_page','link_hub']}
    top_method=max([m.get('confidence_score',0) for m in methods],default=0)
    submithub=submithub_signal_from_methods(methods)
    conf=(35 if best['email'] else 0)+(20 if best['instagram'] else 0)+(18 if best['submission_page'] else 0)+(10 if (best['website'] or best['link_hub']) else 0)+(8 if submithub.get('submithub_verified') else 0)+(5 if spot.get('title') else 0)+int(top_method*.25)
    return {'playlist_name_found':playlist_name,'curator_name_found':curator_name,'spotify_description':spot.get('description',''),'thumbnail_url':spot.get('thumbnail_url',''),'email':best['email'],'instagram':best['instagram'],'website':best['website'] or best['link_hub'],'submission_page':best['submission_page'],'link_hub':best['link_hub'],'contact_methods':methods,'confidence_score':min(100,conf),**submithub}
