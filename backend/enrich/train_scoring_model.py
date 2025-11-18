# backend/enrich/train_scoring_model.py
import json, re, os
from pathlib import Path
import numpy as np
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import precision_score
from scipy.stats import spearmanr
import joblib

DATA = Path(__file__).parent.parent / "tests" / "data" / "enrichment_gold.jsonl"
MODEL_OUT = Path(__file__).parent.parent / "models"
MODEL_OUT.mkdir(exist_ok=True)

KW_FEATURES = {
    'kw_ai': ['ai','artificial intelligence','machine learning','deep learning','transformer','llm','neural'],
    'kw_hf': ['huggingface','hugging face','hf.co'],
    'kw_research': ['paper','arxiv','research','study','results','we propose','methodology'],
    'kw_tutorial': ['tutorial','how to','guide','walkthrough'],
}

def featurize(item):
    t = (item.get('title') or "").lower()
    c = (item.get('content_snippet') or "").lower()
    s = t + " " + c
    feats = []
    # binary keyword presence
    for k, kws in KW_FEATURES.items():
        feats.append(1 if any(kw in s for kw in kws) else 0)
    # lengths
    feats.append(len(t))
    feats.append(len(c))
    # uppercase ratio (title)
    feats.append(sum(1 for ch in (item.get('title') or "") if ch.isupper()) / max(1,len(item.get('title') or "")))
    # punctuation count
    feats.append(sum(1 for ch in s if ch in '?!'))
    return np.array(feats, dtype=float)

def load_Xy(path=DATA):
    X=[]; y=[]
    for line in open(path,'r',encoding='utf-8'):
        it=json.loads(line)
        X.append(featurize(it))
        y.append(1 if it.get('human_score',0)>=0.5 else 0)
    return np.vstack(X), np.array(y)

def ndcg_at_k_from_labels(y_true, y_score, k):
    # y_true are continuous (human_score) OR binary; here use binary
    idx = np.argsort(y_score)[::-1]
    rels = y_true[idx]
    def dcg(rels):
        return sum((2**r - 1)/np.log2(i+2) for i,r in enumerate(rels[:k]))
    ideal = sorted(rels, reverse=True)
    idcg = dcg(ideal)
    return dcg(rels)/idcg if idcg>0 else 0.0

if __name__=="__main__":
    X,y = load_Xy()
    if len(y) < 10:
        print("Warning: very small dataset; results will be noisy.")
    X_train, X_test, y_train, y_test = train_test_split(X,y,test_size=0.3, random_state=42, stratify=y if len(set(y))>1 else None)
    clf = LogisticRegression(max_iter=200)
    clf.fit(X_train, y_train)
    proba = clf.predict_proba(X_test)[:,1]
    preds = (proba >= 0.5).astype(int)
    prec = precision_score(y_test, preds) if len(set(y_test))>1 else float('nan')
    rho,p = spearmanr(y_test, proba)
    ndcg5 = ndcg_at_k_from_labels(y_test, proba, 5)
    print("precision (test):", prec)
    print("spearman:", rho, "p:", p)
    print("nDCG@5:", ndcg5)
    # save model and feature info
    joblib.dump(clf, MODEL_OUT / "scorer_lr.joblib")
    print("Saved model ->", MODEL_OUT / "scorer_lr.joblib")
    # print feature importances (coeff)
    print("coeffs:", clf.coef_)
