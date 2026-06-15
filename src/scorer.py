from datetime import datetime
def follower_fit_score(f):
    f=int(f or 0)
    if f<=0: return 40
    if 1000<=f<=75000: return 100
    if 250<=f<1000: return 75
    if 75001<=f<=250000: return 65
    if f>250000: return 35
    return 50
def recency_score(v):
    if not v: return 50
    try: days=(datetime.now()-datetime.fromisoformat(v[:10])).days
    except ValueError: return 50
    return 100 if days<=30 else 80 if days<=90 else 65 if days<=180 else 45 if days<=365 else 20
def contactability_score(c):
    base=100 if c.get('email') else 75 if c.get('instagram') else 65 if c.get('submission_page') else 50 if c.get('website') else 0
    confidence=int(c.get('confidence_score') or 0)
    if c.get('submithub_verified'):
        confidence=max(confidence,int(c.get('submithub_confidence') or 0),82)
    return max(base,confidence) if base else confidence
def submission_quality_score(c):
    c=c or {}
    if c.get('submithub_verified'): return 95
    page=(c.get('submission_page') or '').lower()
    if any(x in page for x in ['groover.co','dailyplaylists.com']): return 85
    if page: return 65
    return 0
def score_playlist(similarity_score,follower_count,recency='',contact=None,intersection_score=0):
    contact=contact or {}; fs=follower_fit_score(follower_count); rs=recency_score(recency); cs=contactability_score(contact); ss=submission_quality_score(contact); ix=float(intersection_score or 0)
    final=similarity_score*.38+ix*.2+fs*.16+rs*.1+cs*.12+ss*.04
    return {'final_score':round(final,2),'priority':'high priority' if final>=80 else 'medium priority' if final>=50 else 'ignore','breakdown':{'similarity':round(similarity_score,2),'intersection':round(ix,2),'follower_fit':fs,'recency':rs,'contactability':cs,'submission_quality':ss}}
