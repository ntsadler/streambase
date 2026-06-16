def refs(breakdown): return [x.get('match') for x in breakdown if x.get('type') in {'core_band','expanded_band'} and x.get('match')][:2]
def _style_line(playlist, similarity_result):
    name=playlist.get('playlist_name') or playlist.get('name') or 'your playlist'
    desc=(playlist.get('spotify_description') or '').strip()
    related=(playlist.get('related_artists') or '').strip()
    evidence=[]
    for item in similarity_result.get('breakdown',[]) or []:
        match=item.get('match')
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
    title=song_context.get('title') or song_context.get('song_title') or 'the track'
    artist=song_context.get('artist') or song_context.get('artist_name') or ''
    url=song_context.get('spotify_url') or song_context.get('song_url') or ''
    released=bool(url) and song_context.get('release_status','released')!='unreleased'
    label=f"{title} by {artist}".strip() if artist else title
    if released:
        return f"The track is {label}: {url}"
    if song_context.get('preview_url'):
        return f"The private preview is {label}: {song_context.get('preview_url')}"
    return f"The track is {label}."
def generate_outreach(playlist, similarity_result, song_context=None):
    name=playlist.get('playlist_name') or 'your playlist'; curator=playlist.get('curator_name') or 'there'; r=refs(similarity_result.get('breakdown',[]))
    ref=f" It sits somewhere near {' and '.join(r)} without trying to copy either lane." if r else ''
    song_line=_song_line(song_context)
    style_line=_style_line(playlist,similarity_result)
    return {
    'email_message':f"Hey {curator},\n\nI came across {name} and liked the taste of it. {style_line} I’m working on music in a nearby lane and thought one track might be a natural fit.{ref}\n\n{song_line}\n\nNo pressure, but if you’re open to submissions, I’d love for you to consider it.\n\nBest,\nNick",
    'instagram_dm':f"Hey {curator}, I came across {name} and liked the lane you’re building. {style_line} I’ve got a track that feels like it could sit naturally there"+(f" — near {' / '.join(r)}" if r else '')+f". {song_line} Open to checking it out?",
    'submission_note':f"Hi {curator}, I found {name} and thought this track might fit the playlist. {style_line} {song_line} Thanks for considering it.",
    'follow_up_message':f"Hey {curator}, just floating this once more in case it got buried. I found {name} and thought the track might make sense for the playlist. {song_line} No worries either way, appreciate you listening."
    }
