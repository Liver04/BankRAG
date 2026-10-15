"""Source-only overlapping windows avoid silently truncating long parent tails."""
import hashlib
WINDOW_CHARS=240
WINDOW_OVERLAP=60
def evidence_windows(text,size=WINDOW_CHARS,overlap=WINDOW_OVERLAP):
    if size<=overlap or overlap<0:raise ValueError('invalid_window_size')
    if not text:return []
    return [{'text':text[start:start+size],'start':start,'end':min(len(text),start+size),
             'sha256':hashlib.sha256(text[start:start+size].encode()).hexdigest()}
            for start in range(0,max(1,len(text)-overlap),size-overlap)]

def score_parents(reranker,query,docs,mode='window_max'):
    """Return original parents and evidence scores; windows never become citations."""
    if mode not in ('parent','window_max'):raise ValueError('unknown_rerank_mode')
    pairs=[];owners=[];windows=[]
    for i,doc in enumerate(docs):
        chunks=[{'text':doc.page_content,'start':0,'end':len(doc.page_content),'sha256':hashlib.sha256(doc.page_content.encode()).hexdigest()}] if mode=='parent' else evidence_windows(doc.page_content)
        for w in chunks:
            pairs.append([query,w['text']]);owners.append(i);windows.append(w)
    scores=list(reranker.predict(pairs)) if pairs else []
    if len(scores)!=len(pairs):raise ValueError('reranker_score_count_mismatch')
    output=[{'score':float('-inf'),'window_count':0,'winning_window':None} for _ in docs]
    import math
    for owner,window,value in zip(owners,windows,scores):
        value=float(value)
        if not math.isfinite(value):raise ValueError('non_finite_rerank_score')
        result=output[owner];result['window_count']+=1
        if value>result['score']:
            result['score']=value;result['winning_window']={k:v for k,v in window.items() if k!='text'}
    for result in output:
        if not result['window_count']:result['score']=0.0
    return output
