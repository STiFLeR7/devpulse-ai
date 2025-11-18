# backend/enrich/eval_metrics.py
import json
from math import log2
from scipy.stats import spearmanr
from sklearn.metrics import precision_score
from pathlib import Path

DATA = Path(__file__).parent.parent / "tests" / "data" / "enrichment_gold.jsonl"

def load_gold(path=DATA):
    items=[]
    with open(path,'r',encoding='utf-8') as f:
        for line in f:
            items.append(json.loads(line))
    return items

def ndcg_at_k(rels, k):
    # rels: list of relevance scores in ranked order
    def dcg(scores):
        return sum((2**r - 1)/log2(i+2) for i,r in enumerate(scores[:k]))
    ideal = sorted(rels, reverse=True)
    idcg = dcg(ideal)
    return dcg(rels)/idcg if idcg>0 else 0.0

def mrr_at_k(rels, k):
    # rels: binary relevance list in ranked order (1/0)
    for i, r in enumerate(rels[:k]):
        if r>0:
            return 1.0/(i+1)
    return 0.0

def get_pred_score(item):
    # import your scoring function; fallback heuristic similar to earlier
    try:
        from backend.enrich.pipeline import score_item
        return score_item(item)
    except Exception:
        s=0
        t=(item.get('title') or '').lower()
        c=(item.get('content_snippet') or '').lower()
        if 'ai' in t or 'ai' in c: s+=0.6
        s+= min(len(c)/400, 0.4)
        return s

def evaluate():
    gold = load_gold()
    # For this tiny runner we treat human_score >=0.5 as relevant
    for k in (5,10):
        # sort by predicted score
        preds = [(i, get_pred_score(it)) for i,it in enumerate(gold)]
        ranked = [gold[i] for i,_ in sorted(preds, key=lambda x:x[1], reverse=True)]
        rels = [1 if r.get('human_score',0)>=0.5 else 0 for r in ranked]
        ndcg = ndcg_at_k([r.get('human_score',0) for r in ranked], k)
        mrr = mrr_at_k(rels, k)
        prec = sum(rels[:k])/k
        print(f"K={k}: precision@{k}={prec:.3f}, nDCG@{k}={ndcg:.3f}, MRR@{k}={mrr:.3f}")
    # Spearman on continuous scores
    gold_scores=[it['human_score'] for it in gold]
    pred_scores=[get_pred_score(it) for it in gold]
    rho,p = spearmanr(gold_scores, pred_scores)
    print("Spearman:", rho, "p:", p)

if __name__=="__main__":
    evaluate()
