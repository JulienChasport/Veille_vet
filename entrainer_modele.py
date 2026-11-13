#!/usr/bin/env python3
"""
entrainer_modele.py - Entraine le classifieur de matieres (TF-IDF + regression logistique).

Modele : une regression logistique independante par matiere (multi-etiquettes) : un article peut
avoir plusieurs matieres, chacune avec sa propre probabilite.

Principe : aucun etiquetage manuel necessaire au depart.
  1. On demande a PubMed les articles ANCIENS (donc deja indexes en MeSH) des 6 revues
     portant sur chiens/chats. Leurs descripteurs MeSH servent d'etiquettes automatiques
     pour chacune des 9 matieres (+ une classe "Autre" : cardio, ortho, derm...).
  2. Le modele apprend a reconnaitre la matiere a partir du seul titre + resume
     (les MeSH ne sont pas encore disponibles pour les articles recents).
  3. Vos corrections manuelles (colonne 'matiere_corrigee' des CSV de rapport ; plusieurs matieres : onco+hemato)
     sont reinjectees automatiquement depuis le dossier corrections/ (voir 4_envoyer_corrections.bat).

Exemples :
    python entrainer_modele.py                          # 6 ans d'historique (hors 6 derniers mois)
    python entrainer_modele.py --annees 8
    python entrainer_modele.py --corrections "rapports/*.csv"

Prerequis : scikit-learn  (pip install scikit-learn)
"""
import argparse
import csv
import datetime as dt
import glob
import random
import re
import sys
from pathlib import Path

import veille_vet as vv

# Etiquettes automatiques : requetes MeSH PubMed (le [mh] inclut automatiquement les
# descripteurs plus specifiques, ex. "Kidney Diseases" couvre l'insuffisance renale, etc.).
# Un article peut avoir plusieurs etiquettes (ex. un lymphome : hemato + onco).
MESH = {
    "Uronephrologie": '"Urologic Diseases"[mh] OR "Kidney Diseases"[mh]',
    "Hematologie / immunologie": '"Hematologic Diseases"[mh] OR "Immune System Diseases"[mh]',
    "Infectiologie": '"Infections"[mh] OR "Communicable Diseases"[mh]',
    "Endocrinologie": '"Endocrine System Diseases"[mh]',
    "Neurologie": '"Nervous System Diseases"[mh]',
    "Oncologie": '"Neoplasms"[mh]',
    "Gastroenterologie": '"Gastrointestinal Diseases"[mh]',
    "Pancreas / hepatologie": '"Liver Diseases"[mh] OR "Pancreatic Diseases"[mh] OR "Biliary Tract Diseases"[mh]',
    "Pneumologie / ORL": '"Respiratory Tract Diseases"[mh] OR "Otorhinolaryngologic Diseases"[mh]',
}
assert list(MESH) == list(vv.CATEGORIES), "MESH doit avoir les memes matieres que CATEGORIES"

CORRECTION_WEIGHT = 5.0     # une correction manuelle pese 5 fois un article etiquete par MeSH
MIN_TEXT_LEN = 80           # on ignore les notices sans resume exploitable


# --------------------------------------------------------------------------- #
# COLLECTE
# --------------------------------------------------------------------------- #

def collecter_etiquettes(annees, cap_autre):
    """Renvoie {pmid: {classes}} depuis PubMed."""
    fin = dt.date.today() - dt.timedelta(days=180)          # laisse le temps a l'indexation MeSH
    debut = fin - dt.timedelta(days=365 * annees)
    revues = "(" + " OR ".join(f'"{ta}"[ta]' for ta, _ in vv.JOURNALS.values()) + ")"
    especes = '(Dogs[mh] OR Cats[mh] OR "Dog Diseases"[mh] OR "Cat Diseases"[mh])'
    base = f"{revues} AND {especes}"
    vv.log(f"Historique d'entrainement : {debut} -> {fin}")

    labels = {}
    for nom, requete in MESH.items():
        ids = vv.esearch(f"({base}) AND ({requete})", debut, fin, "pdat")
        vv.log(f"  {nom}: {len(ids)} articles" + ("  (plafond PubMed atteint !)" if len(ids) >= 10000 else ""))
        for i in ids:
            labels.setdefault(i, set()).add(nom)

    union = " OR ".join(f"({q})" for q in MESH.values())
    autres = vv.esearch(f"({base}) NOT ({union})", debut, fin, "pdat")
    random.Random(0).shuffle(autres)
    vv.log(f"  {vv.CLASS_OTHER}: {len(autres)} articles (on en garde {min(len(autres), cap_autre)})")
    for i in autres[:cap_autre]:
        labels.setdefault(i, set()).add(vv.CLASS_OTHER)
    return labels


def telecharger(pmids, cache_path=None):
    """Telecharge les notices ; garde un cache disque pour ne pas tout retelecharger a chaque essai."""
    import json
    cache = {}
    if cache_path and Path(cache_path).exists():
        try:
            cache = json.loads(Path(cache_path).read_text(encoding="utf-8"))
        except Exception:
            cache = {}
    manquants = [p for p in pmids if p not in cache]
    vv.log(f"Notices : {len(pmids) - len(manquants)} en cache, {len(manquants)} a telecharger"
           + (" (quelques minutes)..." if manquants else ""))
    if manquants:
        for a in vv.fetch_xml(manquants):
            art = vv.parse_article(a, "?")
            cache[art["pmid"]] = art
        if cache_path:
            Path(cache_path).write_text(json.dumps(cache), encoding="utf-8")
    return {p: cache[p] for p in pmids if p in cache}


def lire_corrections(motif):
    """Lit la colonne 'matiere_corrigee' des CSV de rapport. Renvoie {pmid: {matieres}}.
    Plusieurs matieres possibles, separees par + ou , ou | (ex. 'onco+hemato'). 'autre' = hors matieres."""
    classes = list(vv.CATEGORIES) + [vv.CLASS_OTHER]
    out = {}
    for fichier in sorted(glob.glob(motif)):
        with open(fichier, newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh, delimiter=";"):
                brut = (row.get("matiere_corrigee") or "").strip().lower()
                if not brut:
                    continue
                labs, ok = set(), True
                for val in re.split(r"[+,|]", brut):
                    val = val.strip()
                    if not val:
                        continue
                    if val.startswith("hors") or val == "autre":
                        labs.add(vv.CLASS_OTHER)
                        continue
                    trouvees = [c for c in classes if c.lower().startswith(val)]   # "uro", "hemato"... suffisent
                    if len(trouvees) == 1:
                        labs.add(trouvees[0])
                    else:
                        ok = False
                        vv.log(f"  ! correction ignoree (PMID {row['pmid']}) : '{val}' est ambigu ou inconnu")
                if ok and labs:
                    if len(labs) > 1:
                        labs.discard(vv.CLASS_OTHER)
                    out[row["pmid"]] = labs
    vv.log(f"{len(out)} corrections manuelles lues")
    return out


# --------------------------------------------------------------------------- #
# MODELE
# --------------------------------------------------------------------------- #

CATS = list(vv.CATEGORIES)
SEUILS_TEST = [0.05, 0.10, 0.20, 0.30, 0.50]


def construire_pipeline():
    """Une regression logistique INDEPENDANTE par matiere (oui/non) : un article peut avoir
    plusieurs matieres a la fois, chacune avec sa propre probabilite (elles ne se partagent pas 100 %)."""
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.multiclass import OneVsRestClassifier
    from sklearn.pipeline import make_pipeline
    return make_pipeline(
        TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True,
                        stop_words="english", max_features=150000),
        OneVsRestClassifier(LogisticRegression(C=10, max_iter=2000, class_weight="balanced")),
    )


def matrice(rows):
    import numpy as np
    return np.array([[1 if c in r[2] else 0 for c in CATS] for r in rows])


def ajuster(pipe, rows):
    """Les corrections manuelles (poids > 1) sont dupliquees pour peser plus lourd."""
    import numpy as np
    X, Y = [], []
    for _pmid, text, labs, poids in rows:
        y = [1 if c in labs else 0 for c in CATS]
        for _ in range(max(1, int(round(poids)))):
            X.append(text)
            Y.append(y)
    pipe.fit(X, np.array(Y))
    return pipe


def evaluer(rows, seuil):
    """Mesure sur 20 % d'articles mis de cote (jamais vus a l'apprentissage)."""
    import numpy as np
    from sklearn.model_selection import train_test_split

    strat = [sorted(r[2])[0] for r in rows]
    try:
        train, test = train_test_split(rows, test_size=0.2, random_state=0, stratify=strat)
    except ValueError:
        train, test = train_test_split(rows, test_size=0.2, random_state=0)
    pipe = ajuster(construire_pipeline(), train)
    P = pipe.predict_proba([r[1] for r in test])          # (n articles, 9 matieres), independantes
    Y = matrice(test)
    en_matiere = Y.sum(axis=1) > 0
    top = P.argmax(axis=1)
    pmax = P.max(axis=1)

    print(f"\nEvaluation sur {len(test)} articles non vus pendant l'apprentissage")
    print(f"{'Matiere':28} {'n':>5} {'retrouvee >= ' + format(seuil, '.0%'):>16} {'en tete':>9}")
    for j, c in enumerate(CATS):
        idx = np.where(Y[:, j] == 1)[0]
        if len(idx):
            print(f"{c:28} {len(idx):5d} {np.mean(P[idx, j] >= seuil):16.0%} {np.mean(top[idx] == j):9.0%}")

    print("\nSelon le seuil (articles d'une de vos matieres / articles 'Autre') :")
    print(f"{'seuil':>6} {'matiere retrouvee':>18} {'rien perdu':>11} {'bonne 1re':>10} {'Autre a ecarter':>16} {'matieres/article':>17}")
    for t in SEUILS_TEST:
        pairs = Y == 1
        rappel = np.mean(P[pairs] >= t)                                    # chaque (article, vraie matiere)
        perdu = np.mean(pmax[en_matiere] >= t)                             # article range quelque part
        bonne = np.mean([Y[i, top[i]] == 1 for i in np.where(en_matiere & (pmax >= t))[0]] or [0])
        autre = np.mean(pmax[~en_matiere] >= t) if (~en_matiere).any() else 0
        nb = np.mean((P[en_matiere] >= t).sum(axis=1))
        print(f"{t:6.0%} {rappel:18.0%} {perdu:11.0%} {bonne:10.0%} {autre:16.0%} {nb:17.1f}")
    print("  matiere retrouvee = part des (article, vraie matiere) dont la probabilite depasse le seuil")
    print("  rien perdu        = part des articles de vos matieres rangee quelque part (pas en 'Hors categories')")
    print("  bonne 1re         = quand l'article est range, sa 1re matiere est une vraie matiere")
    print("  Autre a ecarter   = part des articles hors matieres quand meme ranges (a trier a la main)")
    return pipe


# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Entraine le classifieur de matieres.")
    ap.add_argument("--annees", type=int, default=6, help="annees d'historique (defaut : 6)")
    ap.add_argument("--cap-autre", type=int, default=3000, help="nb max d'articles 'Autre' (defaut : 3000)")
    ap.add_argument("--seuil", type=float, default=vv.DEFAULT_THRESHOLD, help="seuil utilise pour l'evaluation")
    ap.add_argument("--sortie", default=str(vv.MODEL_PATH), help="fichier du modele")
    ap.add_argument("--corrections", default=str(Path(__file__).with_name("corrections") / "*.csv"),
                    help='glob des CSV corriges (defaut : corrections/*.csv ; ex. "rapports/*.csv")')
    ap.add_argument("--cache", default=str(Path(__file__).with_name("cache_notices.json")),
                    help="cache des notices telechargees (evite de tout retelecharger)")
    ap.add_argument("--sans-cache", action="store_true", help="ignorer le cache et tout retelecharger")
    args = ap.parse_args()

    try:
        import sklearn  # noqa: F401
    except ImportError:
        sys.exit("scikit-learn est requis : pip install scikit-learn")

    labels = collecter_etiquettes(args.annees, args.cap_autre)
    corrections = lire_corrections(args.corrections) if args.corrections else {}
    arts = telecharger(set(labels) | set(corrections), None if args.sans_cache else args.cache)

    rows = []
    for pmid, labs in labels.items():
        art = arts.get(pmid)
        if art and pmid not in corrections:
            text = vv.texte_modele(art)
            if len(text) >= MIN_TEXT_LEN:
                rows.append((pmid, text, labs, 1.0))
    n_mesh = len(rows)
    evalrows = list(rows)                                  # evaluation sur les etiquettes MeSH uniquement
    for pmid, labs in corrections.items():
        art = arts.get(pmid)
        if art:
            rows.append((pmid, vv.texte_modele(art), set(labs), CORRECTION_WEIGHT))
    if n_mesh < 200:
        sys.exit(f"Seulement {n_mesh} articles exploitables : verifiez l'acces a PubMed.")

    import joblib
    evaluer(evalrows, args.seuil)
    pipe = ajuster(construire_pipeline(), rows)
    joblib.dump({"pipeline": pipe, "classes": CATS, "format": 2}, args.sortie)
    print(f"\nModele enregistre : {args.sortie}  ({n_mesh} articles MeSH + {len(rows) - n_mesh} corrections)")


if __name__ == "__main__":
    main()
