def _clean_text(value):
    return (value or '').encode('ascii','ignore').decode('ascii').strip()
def refs(breakdown): return [_clean_text(x.get('match')) for x in breakdown if x.get('type') in {'core_band','expanded_band'} and _clean_text(x.get('match'))][:2]
def _style_line(playlist, similarity_result):
    name=_clean_text(playlist.get('playlist_name') or playlist.get('name')) or 'your playlist'
    desc=_clean_text(playlist.get('spotify_description') or '')
    related=_clean_text(playlist.get('related_artists') or '')
    evidence=[]
    for item in similarity_result.get('breakdown',[]) or []:
        match=_clean_text(item.get('match'))
        if match and item.get('type') in {'descriptor','genre','related_artist','core_band','expanded_band'}:
            evidence.append(match)
    clean=[]
    for item in evidence:
        if item and item not in clean:
            clean.append(item)
    if clean:
        return f"{name} feels like it lives around {', '.join(clean[:3])}."
    if desc:
        return f"{name} feels curated around {desc[:120].rstrip()}."
    if related:
        return f"{name} has a lane that lines up with artists like {related.split(';')[0].strip()}."
    return f"{name} feels like the right lane."
def _song_line(song_context):
    song_context=song_context or {}
    url=song_context.get('spotify_url') or song_context.get('song_url') or ''
    released=bool(url) and song_context.get('release_status','released')!='unreleased'
    if released:
        return f"Spotify link: {url}"
    if song_context.get('preview_url'):
        return f"Private preview: {song_context.get('preview_url')}"
    return "I can send the link if it feels like a fit."
def generate_outreach(playlist, similarity_result, song_context=None):
    name=_clean_text(playlist.get('playlist_name')) or 'your playlist'; r=refs(similarity_result.get('breakdown',[]))
    ref=f" It sits somewhere near {' and '.join(r)} without trying to copy either lane." if r else ''
    song_line=_song_line(song_context)
    style_line=_style_line(playlist,similarity_result)
    return {
    'email_message':f"Hey,\n\nQuick cold email, so I'll keep it short.\n\nI found {name} and thought one of my tracks might fit. {style_line}{ref}\n\n{song_line}\n\nNo worries if it's not right for the playlist.\n\nThanks,\nNick\nStrange Hotels",
    'instagram_dm':f"Hey, I came across {name} and liked the lane you're building. {style_line} I've got a track that feels like it could sit naturally there"+(f" near {' / '.join(r)}" if r else '')+f". {song_line} No pressure, but if you're open to submissions, I'd love for you to consider it.",
    'submission_note':f"Hi, I found {name} and thought this track might fit the playlist. {style_line} {song_line} Thanks for considering it.",
    'follow_up_message':f"Hey, just floating this once more in case it got buried. I found {name} and thought the track might make sense for the playlist. {song_line} No worries either way, appreciate you listening."
    }
