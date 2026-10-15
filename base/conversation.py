"""Conservative product-only anaphora. History never grants permission."""
import re
PRODUCTS=('零存整取','整存整取','存本取息','整存零取','一天通知存款','七天通知存款','通知存款','大额存单','活期存款','定期存款')
REFERENCE=re.compile(r'(?<!其)它|该产品|这种存款|这款存款|刚才(?:那个|那种|说的)|上述产品')
def resolve_query(query,history):
    if not REFERENCE.search(query):return query,{'status':'not_needed'}
    if any(p in query for p in PRODUCTS):return query,{'status':'explicit_topic'}
    if not history:return None,{'status':'unresolved','reason':'no_history'}
    for used,last in enumerate(reversed(history[-5:]),1):
        q=str(last.get('question',''));names=[p for p in PRODUCTS if p in q]
        names=[p for p in names if not any(p!=x and p in x for x in names)]
        if len(names)>1:return None,{'status':'unresolved','reason':'ambiguous_product'}
        if len(names)==1:return REFERENCE.sub(names[0],query),{'status':'resolved','product':names[0],'history_turns_used':used}
        if not REFERENCE.search(q):break  # Stop at an unrelated topic, never jump past it.
    return None,{'status':'unresolved','reason':'missing_product'}
