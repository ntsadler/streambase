def refs(breakdown): return [x.get('match') for x in breakdown if x.get('type') in {'core_band','expanded_band'} and x.get('match')][:2]
def generate_outreach(playlist, similarity_result):
    name=playlist.get('playlist_name') or 'your playlist'; curator=playlist.get('curator_name') or 'there'; r=refs(similarity_result.get('breakdown',[]))
    ref=f" It sits somewhere near {' and '.join(r)} without trying to copy either lane." if r else ''
    return {
    'email_message':f"Hey {curator},\n\nI came across {name} and liked the taste of it. I’m working on music in that indie, dance-leaning lane and thought one track might be a natural fit.{ref}\n\nNo pressure, but if you’re open to submissions, I’d love to send it over for consideration.\n\nBest,\nNick",
    'instagram_dm':f"Hey {curator}, I came across {name} and liked the lane you’re building. I’ve got a track that feels like it could sit naturally there"+(f" — near {' / '.join(r)}" if r else '')+'. Open to me sending it over?',
    'submission_note':f"Hi {curator}, I found {name} and thought this track might fit the playlist. It leans indie/electro/dance with a songwriter core"+(f" and sits near {' / '.join(r)}" if r else '')+'. Thanks for considering it.',
    'follow_up_message':f"Hey {curator}, just floating this once more in case it got buried. I found {name} and thought the track might make sense for the playlist. No worries either way — appreciate you listening."
    }
