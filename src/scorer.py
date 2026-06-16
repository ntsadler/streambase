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
def evidence_confidence(similarity_score,follower_count,recency='',contact=None,intersection_score=0):
    contact=contact or {}
    evidence=[]
    confidence=0
    if float(similarity_score or 0)>0:
        confidence+=25; evidence.append('playlist text match')
    if float(intersection_score or 0)>0:
        confidence+=20; evidence.append('artist/catalog overlap')
    if int(follower_count or 0)>0:
        confidence+=15; evidence.append('follower count')
    if recency:
        confidence+=10; evidence.append('recent update data')
    if contactability_score(contact)>0:
        confidence+=20; evidence.append('contact path')
    if submission_quality_score(contact)>0:
        confidence+=10; evidence.append('submission signal')
    return {'confidence_score':min(100,confidence),'evidence':evidence}
def priority_label(final,confidence):
    if confidence<35:
        return 'needs review'
    if final>=80:
        return 'strong fit'
    if final>=50:
        return 'promising'
    if final>=35:
        return 'weak fit'
    return 'low fit'
def score_playlist(similarity_score,follower_count,recency='',contact=None,intersection_score=0):
    contact=contact or {}; fs=follower_fit_score(follower_count); rs=recency_score(recency); cs=contactability_score(contact); ss=submission_quality_score(contact); ix=float(intersection_score or 0)
    final=similarity_score*.38+ix*.2+fs*.16+rs*.1+cs*.12+ss*.04
    confidence=evidence_confidence(similarity_score,follower_count,recency,contact,ix)
    return {
        'final_score':round(final,2),
        'priority':priority_label(final,confidence['confidence_score']),
        'confidence_score':confidence['confidence_score'],
        'evidence':confidence['evidence'],
        'breakdown':{
            'similarity':round(similarity_score,2),
            'intersection':round(ix,2),
            'follower_fit':fs,
            'recency':rs,
            'contactability':cs,
            'submission_quality':ss,
        },
    }
