#!/usr/bin/env python3
"""
veille_vet.py - Veille bibliographique veterinaire (animaux de compagnie)

Recupere les articles de 6 revues veterinaires via PubMed (API officielle NCBI
E-utilities, gratuite), ecarte ce qui ne concerne pas les "small animals"
(chevaux, bovins, etc.), puis classe chaque article dans les matieres suivies.

Classement par matiere : modele d'apprentissage (TF-IDF + regression logistique) qui donne
un pourcentage de confiance pour chaque matiere ; l'article va dans la matiere la plus
probable si elle depasse le seuil (--seuil, bas par defaut) ; les autres matieres probables sont
signalees aussi (--seuil-secondaire). Une probabilite par matiere, independante des autres. Le modele s'entraine avec
entrainer_modele.py (a lancer une fois, puis de temps en temps).

Prerequis : Python 3.8+ et scikit-learn  (pip install scikit-learn)

Exemples :
    python3 veille_vet.py                       # 7 derniers jours (defaut)
    python3 veille_vet.py --days 14             # 14 derniers jours
    python3 veille_vet.py --last-month          # mois calendaire precedent (cron mensuel)
    python3 veille_vet.py --from 2026-10-01 --to 2026-10-31
    python3 veille_vet.py --seuil 0.15          # encore plus permissif
    python3 veille_vet.py --methode mots-cles   # secours, sans modele ni scikit-learn
    python3 veille_vet.py --last-month --email-to moi@exemple.fr

Sorties (dossier ./rapports par defaut) :
    rapport_<debut>_<fin>.html   rapport lisible, groupe par matiere, avec les % de confiance
    rapport_<debut>_<fin>.csv    tous les articles (retenus ET ecartes), probabilites par matiere,
                                 et une colonne 'matiere_corrigee' a remplir pour la verification
"""
import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import smtplib
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from email.message import EmailMessage
from pathlib import Path

# --------------------------------------------------------------------------- #
# CONFIGURATION (a modifier librement)
# --------------------------------------------------------------------------- #

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
TOOL_NAME = "veille_vet"

# code court -> (abreviation PubMed de la revue, nom complet)
JOURNALS = {
    "JVIM":  ("J Vet Intern Med",     "Journal of Veterinary Internal Medicine"),
    "JFMS":  ("J Feline Med Surg",    "Journal of Feline Medicine and Surgery"),
    "JSAP":  ("J Small Anim Pract",   "Journal of Small Animal Practice"),
    "VetJ":  ("Vet J",                "The Veterinary Journal"),
    "JAVMA": ("J Am Vet Med Assoc",   "Journal of the American Veterinary Medical Association"),
    "AJVR":  ("Am J Vet Res",         "American Journal of Veterinary Research"),
}

# Revues dont tout le contenu est "animaux de compagnie" : on garde tout.
# (JFMS = chat uniquement ; JSAP = chiens/chats/NAC.)
ALWAYS_SMALL_ANIMAL = {"JFMS", "JSAP"}

# Un terme finissant par * = prefixe (kidney* -> kidneys, kidney's...).
# Sinon = mot entier (pluriel simple accepte).
CATEGORIES = {
    "Uronephrologie": [
        "kidney*", "renal", "nephr*", "urinary", "urin*", "urolith*", "uretero*", "ureter*",
        "urethra*", "bladder", "cystitis", "pyelonephritis", "hydronephrosis", "proteinuria",
        "albuminuria", "azotemia", "creatinine", "SDMA", "glomerul*", "CKD", "AKI",
        "dialysis", "hemodialysis", "FLUTD", "lower urinary tract", "incontinence",
        "urinary tract infection", "urethral obstruction", "ureteral obstruction",
        "nephrolith*", "cystotomy", "polyuria",
    ],
    "Hematologie / immunologie": [
        "anemia", "anaemia", "IMHA", "immune-mediated", "immune mediated", "autoimmune",
        "thrombocytopenia", "ITP", "coagul*", "hemostasis", "haemostasis", "transfusion",
        "blood type", "blood group", "neutropenia", "bone marrow", "platelet*", "erythro*",
        "hemoly*", "haemoly*", "immunosuppress*", "immunodeficiency", "thromboembol*",
        "thrombosis", "thrombotic", "cytopenia", "polycythemia", "hematolog*", "haematolog*",
        "hypersensitivity", "immunoglobulin*", "complement", "leukocyt*", "eosinophil*",
        "lupus", "von Willebrand", "hemophilia", "methemoglobin*", "red blood cell*",
    ],
    "Infectiologie": [
        "infectious", "infection", "virus", "viral", "bacteri*", "antimicrobial*",
        "antibiotic*", "antibacterial", "resistance", "fung*", "parasit*", "FIV", "FeLV",
        "FIP", "coronavirus", "parvovirus", "leptospir*", "bartonella", "babesia*",
        "ehrlichia*", "anaplasma*", "leishmania*", "heartworm", "dirofilaria*", "tick-borne",
        "sepsis", "septic", "vaccin*", "zoonotic", "zoonos*", "panleukopenia", "calicivirus",
        "herpesvirus", "toxoplasma*", "giardia*", "MRSA", "pathogen*", "mycoplasma*",
        "rabies", "distemper", "salmonella", "campylobacter", "clostridi*", "cryptococc*",
        "aspergill*", "dermatophyt*", "protozoa*", "helminth*", "flea*", "tick",
    ],
    "Endocrinologie": [
        "diabet*", "insulin*", "hyperadrenocorticism", "Cushing", "hypoadrenocorticism",
        "Addison*", "hypothyroidism", "hyperthyroidism", "thyroid*", "acromegaly",
        "hypersomatotropism", "glucose", "ketoacidosis", "hypercalcemia", "hypercalcaemia",
        "hypocalcemia", "parathyroid*", "pheochromocytoma", "adrenal*", "cortisol",
        "trilostane", "radioiodine", "methimazole", "endocrin*", "pituitary", "hypoglycemia",
        "hypoglycaemia", "insulinoma", "fructosamine", "continuous glucose monitoring",
        "glycemic", "glycaemic", "growth hormone", "thyroxine", "levothyroxine", "obesity",
        "hyperaldosteronism", "aldosterone", "ACTH",
    ],
    "Neurologie": [
        "seizure*", "epilep*", "neurolog*", "neuro*", "intervertebral disc*", "IVDD",
        "spinal cord", "myelopathy", "encephal*", "meningoencephal*", "brain", "cerebell*",
        "cerebral", "vestibular", "myasthenia*", "paralysis", "ataxia", "syringomyelia",
        "Chiari", "hydrocephalus", "cognitive dysfunction", "cranial nerve*",
        "peripheral nerve*", "phenobarbital", "levetiracetam", "tetraparesis", "paraparesis",
        "paraplegia", "myopathy", "polyneuropathy", "cerebrospinal fluid", "CSF",
        "idiopathic epilepsy", "meningitis", "myelitis", "hemilaminectomy", "spinal",
    ],
    "Oncologie": [
        "cancer*", "tumor*", "tumour*", "neoplas*", "carcinoma*", "sarcoma*", "lymphoma*",
        "leukemia", "leukaemia", "melanoma*", "mast cell tumo*", "osteosarcoma*",
        "hemangiosarcoma*", "haemangiosarcoma*", "chemotherap*", "radiation therapy",
        "radiotherapy", "metasta*", "oncolog*", "malignan*", "histiocytic", "adenocarcinoma*",
        "toceranib", "CHOP", "electrochemotherapy", "immunotherapy", "cytoreduct*",
        "thymoma", "insulinoma", "adenoma*", "blastoma*", "myeloma*",
    ],
    "Gastroenterologie": [
        "gastro*", "intestin*", "enteropath*", "enteritis", "inflammatory bowel",
        "IBD", "colitis", "colon", "colonic", "diarrhea", "diarrhoea", "vomiting",
        "stomach", "esophag*", "oesophag*", "megaesophagus", "microbiome", "microbiota",
        "fecal microbiota", "faecal microbiota", "dysbiosis", "lymphangiectasia",
        "constipation", "megacolon", "dilatation-volvulus", "GDV", "helicobacter",
        "ileus", "intussusception", "cobalamin", "folate", "fecal", "faecal", "ileum",
        "jejunum", "duodenum", "dysphagia", "regurgitation", "rectal", "anal sac*",
        "protein-losing", "chronic enteropathy", "gut",
    ],
    "Pancreas / hepatologie": [
        "pancrea*", "exocrine pancreatic insufficiency", "EPI", "fPLI", "cPLI",
        "liver", "hepat*", "biliary", "bile", "cholangitis", "cholangiohepatitis",
        "gallbladder", "gall bladder", "mucocele", "portosystemic", "shunt*", "cirrhosis",
        "bile acid*", "cholestasis", "cholecystitis", "cholecystectomy", "ALT",
        "hepatopathy", "lipidosis", "copper-associated", "hepatic encephalopathy",
        "fibrosis", "trypsin-like", "lipase",
    ],
    "Pneumologie / ORL": [
        "respirat*", "pulmonary", "lung*", "bronch*", "asthma*", "pneumonia", "airway*",
        "brachycephalic", "BOAS", "laryn*", "trache*", "nasal", "rhinitis", "rhinoscopy",
        "sinus*", "sinonasal", "nasopharyn*", "polyp*", "otitis", "ear canal", "ears",
        "pharyn*", "pleural", "pyothorax", "dyspnea", "dyspnoea", "cough*", "chylothorax",
        "pneumothorax", "pulmonary fibrosis", "bronchoscopy", "bronchoalveolar",
        "upper airway", "otoscopy", "tonsil*", "thoracic", "thorax", "oxygen therapy",
        "tachypnea", "stridor", "ventilat*", "aspiration",
    ],
}

# Termes servant a reconnaitre l'espece
DOG_TERMS = ["dog", "canine*", "puppy", "puppies", "bitch*"]
CAT_TERMS = ["cat", "feline*", "kitten*", "queen"]
OTHER_SMALL_TERMS = [
    "small animal*", "companion animal*", "pet", "ferret*", "rabbit*", "guinea pig*",
    "hamster*", "chinchilla*", "rodent*", "exotic pet*",
]
LARGE_TERMS = [
    "horse*", "equine*", "foal*", "mare", "stallion*", "gelding*", "pony", "ponies",
    "donkey*", "cattle", "bovine*", "cow", "heifer*", "calf", "calves", "dairy",
    "beef", "sheep", "ovine", "lamb", "goat*", "caprine", "swine", "pig", "piglet*",
    "porcine", "poultry", "chicken*", "camelid*", "alpaca*", "llama*", "livestock",
    "ruminant*",
]

# Types de publication ecartes d'office
EXCLUDED_PUBTYPES = {"Published Erratum", "Retraction of Publication"}

CATEGORY_MIN_SCORE = 3          # (methode mots-cles) score minimal pour rattacher un article
SECONDARY_RATIO = 0.5           # (methode mots-cles) une matiere secondaire doit atteindre 50% du score principal
OTHER_LABEL = "Hors categories suivies"   # rubrique du rapport : aucune matiere n'atteint le seuil
CLASS_OTHER = "Autre"                     # classe "autre sujet" du modele (cardio, ortho, derm...)
MODEL_PATH = Path(__file__).with_name("modele_matieres.joblib")
DEFAULT_THRESHOLD = 0.10        # seuil bas volontairement : la verification finale est manuelle
DEFAULT_SECONDARY = 0.30        # une matiere supplementaire (en plus de la 1re) est signalee a partir de ce seuil

# --------------------------------------------------------------------------- #
# ACCES PUBMED
# --------------------------------------------------------------------------- #

def log(msg):
    print(msg, file=sys.stderr, flush=True)


def eutils(endpoint, params, retries=4):
    """Appel POST a E-utilities avec nouvelles tentatives."""
    params = dict(params)
    params.setdefault("tool", TOOL_NAME)
    if os.getenv("NCBI_EMAIL"):
        params["email"] = os.getenv("NCBI_EMAIL")
    api_key = os.getenv("NCBI_API_KEY")
    if api_key:
        params["api_key"] = api_key
    data = urllib.parse.urlencode(params).encode()
    delay = 0.12 if api_key else 0.4   # limite NCBI : 3 req/s sans cle, 10 avec
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(EUTILS + endpoint, data=data)
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = resp.read()
            time.sleep(delay)
            return body
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last_err = e
            wait = 2 ** attempt
            log(f"  ! {endpoint} echec ({e}); nouvel essai dans {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"E-utilities injoignable : {last_err}")


def esearch(term, d1=None, d2=None, datetype="pdat", retmax=10000):
    """Recherche PubMed quelconque ; renvoie la liste des PMID."""
    params = {"db": "pubmed", "term": term, "retmax": retmax, "retmode": "json"}
    if d1 and d2:
        params.update(datetype=datetype, mindate=d1.strftime("%Y/%m/%d"),
                      maxdate=d2.strftime("%Y/%m/%d"))
    body = eutils("esearch.fcgi", params)
    return json.loads(body)["esearchresult"].get("idlist", [])


def search_pmids(journal_abbr, d1, d2, datetype):
    return esearch(f'"{journal_abbr}"[ta]', d1, d2, datetype)


def fetch_xml(pmids, batch=150):
    """Telecharge les notices par lots, renvoie une liste d'elements PubmedArticle."""
    out = []
    for i in range(0, len(pmids), batch):
        chunk = pmids[i:i + batch]
        body = eutils("efetch.fcgi", {"db": "pubmed", "id": ",".join(chunk), "retmode": "xml"})
        root = ET.fromstring(body)
        out.extend(root.findall("PubmedArticle"))
    return out


def _text(el):
    return "".join(el.itertext()).strip() if el is not None else ""


def parse_article(a, journal_code):
    art = a.find("MedlineCitation/Article")
    pubdate = ""
    pd = art.find("Journal/JournalIssue/PubDate")
    if pd is not None:
        medline = _text(pd.find("MedlineDate"))
        pubdate = medline or " ".join(
            p for p in (_text(pd.find("Year")), _text(pd.find("Month")), _text(pd.find("Day"))) if p
        )
    doi = ""
    for i in a.findall("PubmedData/ArticleIdList/ArticleId"):
        if i.get("IdType") == "doi":
            doi = _text(i)
    pmid = _text(a.find("MedlineCitation/PMID"))
    return {
        "pmid": pmid,
        "journal": journal_code,
        "date": pubdate,
        "title": _text(art.find("ArticleTitle")),
        "abstract": " ".join(_text(x) for x in art.findall("Abstract/AbstractText")),
        "mesh": [_text(x) for x in a.findall("MedlineCitation/MeshHeadingList/MeshHeading/DescriptorName")],
        "keywords": [_text(x) for x in a.findall("MedlineCitation/KeywordList/Keyword")],
        "pubtypes": [_text(x) for x in art.findall("PublicationTypeList/PublicationType")],
        "doi": doi,
        "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
    }


def journal_code_from_xml(a):
    """Deduit le code court de la revue a partir de la notice (mode --from-xml)."""
    abbr = _text(a.find("MedlineCitation/Article/Journal/ISOAbbreviation")).rstrip(".").lower()
    for code, (ta, _) in JOURNALS.items():
        if ta.lower() == abbr:
            return code
    return abbr or "?"

# --------------------------------------------------------------------------- #
# CLASSIFICATION
# --------------------------------------------------------------------------- #

def compile_terms(terms):
    rxs = []
    for t in terms:
        if t.endswith("*"):
            pat = r"\b" + re.escape(t[:-1].lower()) + r"\w*"
        else:
            pat = r"\b" + re.escape(t.lower()) + r"(?:s|es)?\b"
        rxs.append(re.compile(pat))
    return rxs


CAT_RX = {name: compile_terms(terms) for name, terms in CATEGORIES.items()}
DOG_RX = compile_terms(DOG_TERMS)
CAT_SPECIES_RX = compile_terms(CAT_TERMS)
OTHER_SMALL_RX = compile_terms(OTHER_SMALL_TERMS)
LARGE_RX = compile_terms(LARGE_TERMS)


def score(rxs, title, meshkw, abstract):
    """Chaque terme distinct rapporte : 3 (titre) + 3 (MeSH/mots-cles) + 1 (resume)."""
    s = 0
    for rx in rxs:
        if rx.search(title):
            s += 3
        if rx.search(meshkw):
            s += 3
        if rx.search(abstract):
            s += 1
    return s


def filtrer_espece(art):
    """Etape 1 : garde ou ecarte l'article (petit animal ou non). Regles, pas d'apprentissage."""
    title = art["title"].lower()
    meshkw = " ; ".join(art["mesh"] + art["keywords"]).lower()
    abstract = art["abstract"].lower()

    # --- type de publication ---
    bad = EXCLUDED_PUBTYPES.intersection(art["pubtypes"])
    if bad:
        return finish(art, False, "", "type de publication ecarte : " + ", ".join(sorted(bad)))

    # --- espece ---
    dog = score(DOG_RX, title, meshkw, abstract)
    cat = score(CAT_SPECIES_RX, title, meshkw, abstract)
    oth = score(OTHER_SMALL_RX, title, meshkw, abstract)
    small = dog + cat + oth
    large = score(LARGE_RX, title, meshkw, abstract)

    if art["journal"] == "JFMS":
        species = "chat"
        keep, reason = True, "revue JFMS (chat)"
    else:
        if dog and cat:
            species = "chien+chat"
        elif dog:
            species = "chien"
        elif cat:
            species = "chat"
        elif oth:
            species = "autre petit animal"
        else:
            species = ""
        if small > 0 and small >= large:
            keep, reason = True, "petit animal" + (" (etude mixte avec grands animaux)" if large else "")
        elif large > small:
            keep, reason = False, "grands animaux dominants (cheval/bovin/etc.)"
        elif art["journal"] in ALWAYS_SMALL_ANIMAL:
            keep, reason = True, "revue petits animaux, espece non precisee"
        else:
            keep, reason = False, "espece non identifiee (a verifier dans le CSV)"

    return finish(art, keep, species, reason)


def finish(art, keep, species, reason):
    art = dict(art)
    art.update(keep=keep, species=species, reason=reason,
               primary="", secondary=[],      # secondary = liste de (matiere, probabilite ou None)
               conf=None,                      # probabilite de la matiere retenue
               proba={},                       # probabilite de chaque classe (modele)
               best=None,                      # (meilleure matiere, proba) meme sous le seuil
               sortkey=0.0)
    return art


def texte_modele(art):
    """Texte donne au modele (le meme a l'entrainement et a l'inference) : titre x2 + resume."""
    return (art["title"] + ". ") * 2 + art["abstract"]


def charger_modele(path):
    try:
        import joblib
    except ImportError:
        sys.exit("scikit-learn est requis : pip install scikit-learn  (ou --methode mots-cles)")
    path = Path(path)
    if not path.exists():
        sys.exit(f"Modele introuvable : {path}\nLancez d'abord : python3 entrainer_modele.py")
    obj = joblib.load(path)
    if not (isinstance(obj, dict) and obj.get("format") == 2):
        sys.exit("Ancien format de modele : relancez 2_entrainer.bat (python entrainer_modele.py).")
    manquantes = [c for c in CATEGORIES if c not in obj["classes"]]
    if manquantes:
        sys.exit(f"Le modele ne correspond plus aux matieres ({manquantes}) : relancez entrainer_modele.py")
    return obj


def matieres_ml(arts, model, seuil, seuil2):
    """Etape 2 (defaut) : une probabilite INDEPENDANTE par matiere (elles ne s'additionnent pas a 100 %).
    L'article va dans la matiere la plus probable si elle atteint `seuil` (le seuil bas, inclusif) ;
    toutes les autres matieres a partir de `seuil2` sont signalees en plus."""
    if not arts:
        return
    classes = model["classes"]
    probs = model["pipeline"].predict_proba([texte_modele(a) for a in arts])
    for a, row in zip(arts, probs):
        p = {c: float(x) for c, x in zip(classes, row)}
        ranked = sorted(p.items(), key=lambda kv: -kv[1])
        top, ptop = ranked[0]
        a["proba"], a["best"], a["sortkey"] = p, (top, ptop), ptop
        if ptop >= seuil:
            a["primary"], a["conf"] = top, ptop
            a["secondary"] = [(c, x) for c, x in ranked[1:] if x >= max(seuil, seuil2)]
        else:
            a["primary"] = OTHER_LABEL


def matieres_mots_cles(art):
    """Methode de secours (sans modele) : score par mots-cles, sans pourcentage."""
    title = art["title"].lower()
    meshkw = " ; ".join(art["mesh"] + art["keywords"]).lower()
    abstract = art["abstract"].lower()
    scores = {n: score(rxs, title, meshkw, abstract) for n, rxs in CAT_RX.items()}
    ranked = sorted(scores.items(), key=lambda kv: -kv[1])
    if ranked[0][1] >= CATEGORY_MIN_SCORE:
        top = ranked[0][1]
        cats = [(n, s) for n, s in ranked
                if s >= CATEGORY_MIN_SCORE and (s == top or s >= SECONDARY_RATIO * top)]
        art["primary"] = cats[0][0]
        art["secondary"] = [(n, None) for n, _ in cats[1:]]
        art["sortkey"] = float(top)
    else:
        art["primary"] = OTHER_LABEL

# --------------------------------------------------------------------------- #
# PERIODE
# --------------------------------------------------------------------------- #

def resolve_period(args):
    today = dt.date.today()
    parse = lambda s: dt.datetime.strptime(s, "%Y-%m-%d").date()
    if args.date_from or args.date_to:
        d2 = parse(args.date_to) if args.date_to else today
        d1 = parse(args.date_from) if args.date_from else d2 - dt.timedelta(days=args.days)
    elif args.last_month:
        d2 = today.replace(day=1) - dt.timedelta(days=1)
        d1 = d2.replace(day=1)
    else:
        d2 = today
        d1 = today - dt.timedelta(days=args.days)
    if d1 > d2:
        sys.exit("Erreur : la date de debut est posterieure a la date de fin.")
    return d1, d2

# --------------------------------------------------------------------------- #
# RAPPORTS
# --------------------------------------------------------------------------- #

CSS = """
body{font-family:-apple-system,Segoe UI,Roboto,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem;color:#222;line-height:1.45}
h1{font-size:1.6rem;margin-bottom:.2rem} .sub{color:#666;margin-bottom:1.5rem}
h2{margin-top:2rem;border-bottom:2px solid #ddd;padding-bottom:.2rem;font-size:1.2rem}
.count{color:#888;font-weight:normal;font-size:.9rem}
ul{padding-left:1.1rem} li{margin:.55rem 0}
a{color:#0b5cad;text-decoration:none} a:hover{text-decoration:underline}
.meta{color:#666;font-size:.85rem} .tag{background:#eef;border-radius:3px;padding:0 .35rem;font-size:.8rem;margin-left:.25rem}
details{margin-top:1.5rem} summary{cursor:pointer;color:#555}
.warn{background:#fff4e5;border:1px solid #f0c78a;padding:.5rem .8rem;border-radius:4px}
.pct{display:inline-block;min-width:2.8rem;font-weight:600;color:#0b5cad}
"""


def pct(p):
    return "" if p is None else f" {p:.0%}"


def item_html(a, show_reason=False, show_best=False):
    h = "<li>"
    if a["conf"] is not None:
        h += f'<span class="pct">{a["conf"]:.0%}</span> '
    h += f'<a href="{html.escape(a["url"])}">{html.escape(a["title"] or "(sans titre)")}</a>'
    meta = [a["journal"], a["date"]]
    if a["species"]:
        meta.append(a["species"])
    h += f'<br><span class="meta">{html.escape(" · ".join(m for m in meta if m))}'
    if a["doi"]:
        h += f' · <a href="https://doi.org/{html.escape(a["doi"])}">DOI</a>'
    for name, p in a["secondary"]:
        h += f'<span class="tag">aussi : {html.escape(name)}{pct(p)}</span>'
    if a.get("vu_aussi_de"):
        h += f'<span class="tag">deja classe en : {html.escape(a["vu_aussi_de"])}</span>'
    if show_best and a["best"]:
        h += f' · meilleure piste : {html.escape(a["best"][0])}{pct(a["best"][1])}'
    if show_reason:
        h += f' · <em>{html.escape(a["reason"])}</em>'
    return h + "</span></li>"


def build_html(arts, d1, d2, datetype, errors, note=""):
    kept = [a for a in arts if a["keep"]]
    dropped = [a for a in arts if not a["keep"]]
    by_cat = {n: [] for n in CATEGORIES}
    by_cat[OTHER_LABEL] = []
    for a in kept:
        by_cat[a["primary"]].append(a)
        for name, p in a["secondary"]:        # inclusif : l'article apparait aussi dans les autres matieres probables
            if name in by_cat:
                dup = dict(a, conf=p, secondary=[], sortkey=p, vu_aussi_de=a["primary"])
                by_cat[name].append(dup)

    nb_total = len(arts)
    out = [f"<!doctype html><html lang='fr'><head><meta charset='utf-8'>"
           f"<title>Veille veterinaire {d1} - {d2}</title><style>{CSS}</style></head><body>",
           f"<h1>Veille veterinaire — petits animaux</h1>",
           f"<div class='sub'>Periode : {d1} au {d2} (date d'entree dans PubMed si datetype=edat) · "
           f"{nb_total} articles analyses · {len(kept)} retenus · {len(dropped)} ecartes (un article peut figurer dans plusieurs matieres)"
           f"{' · ' + html.escape(note) if note else ''}</div>"]
    if errors:
        out.append("<p class='warn'>Attention, des revues n'ont pas pu etre interrogees : "
                   + html.escape(", ".join(errors)) + "</p>")

    # Sommaire par matiere
    out.append("<p>" + " · ".join(
        f"{html.escape(n)} <b>{len(v)}</b>" for n, v in by_cat.items() if n != OTHER_LABEL and v) + "</p>")

    for name in list(CATEGORIES) + [OTHER_LABEL]:
        items = by_cat[name]
        if not items:
            if name != OTHER_LABEL:
                out.append(f"<h2>{html.escape(name)} <span class='count'>(0)</span></h2>"
                           f"<p class='meta'>Rien cette periode.</p>")
            continue
        items.sort(key=lambda a: (-a["sortkey"], a["journal"]))
        if name == OTHER_LABEL:
            out.append(f"<details><summary><b>{OTHER_LABEL}</b> ({len(items)}) — aucune matiere "
                       f"au-dessus du seuil</summary><ul>")
            out.extend(item_html(a, show_best=True) for a in items)
            out.append("</ul></details>")
        else:
            out.append(f"<h2>{html.escape(name)} <span class='count'>({len(items)})</span></h2><ul>")
            out.extend(item_html(a) for a in items)
            out.append("</ul>")

    if dropped:
        out.append(f"<details><summary>Articles ecartes ({len(dropped)}) — pour verification</summary><ul>")
        out.extend(item_html(a, show_reason=True) for a in sorted(dropped, key=lambda a: a["journal"]))
        out.append("</ul></details>")
    out.append("</body></html>")
    return "\n".join(out)


def write_csv(path, arts):
    classes = list(CATEGORIES) + [CLASS_OTHER]
    cols = ["pmid", "journal", "date", "title", "espece", "retenu", "matiere", "confiance_pct",
            "matieres_secondaires", "matiere_corrigee", "motif", "doi", "url"] + \
           [f"p_{c}" for c in classes]
    with open(path, "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig + ';' : ouvre bien dans Excel FR
        w = csv.writer(f, delimiter=";")
        w.writerow(cols)
        for a in arts:
            conf = "" if a["conf"] is None else f"{a['conf'] * 100:.0f}"
            second = " | ".join(f"{n}{pct(p)}" for n, p in a["secondary"])
            probas = [f"{a['proba'][c] * 100:.0f}" if c in a["proba"] else "" for c in classes]
            w.writerow([a["pmid"], a["journal"], a["date"], a["title"], a["species"],
                        "oui" if a["keep"] else "non", a["primary"], conf, second, "",
                        a["reason"], a["doi"], a["url"]] + probas)


def send_email(to, subject, body, attachments):
    host = os.getenv("SMTP_HOST")
    if not host:
        log("! --email-to fourni mais SMTP_HOST non defini : email non envoye.")
        return
    msg = EmailMessage()
    msg["From"] = os.getenv("SMTP_FROM") or os.getenv("SMTP_USER") or "veille@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    for p in attachments:
        p = Path(p)
        maintype, subtype = ("text", "html") if p.suffix == ".html" else ("text", "csv")
        msg.add_attachment(p.read_bytes(), maintype=maintype, subtype=subtype, filename=p.name)
    with smtplib.SMTP(host, int(os.getenv("SMTP_PORT", "587"))) as s:
        s.starttls()
        if os.getenv("SMTP_USER"):
            s.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD", ""))
        s.send_message(msg)
    log(f"Email envoye a {to}")

# --------------------------------------------------------------------------- #
# MAIN
# --------------------------------------------------------------------------- #

def main():
    ap = argparse.ArgumentParser(description="Veille bibliographique veterinaire (petits animaux).")
    ap.add_argument("--days", type=int, default=7, help="fenetre en jours avant aujourd'hui (defaut : 7)")
    ap.add_argument("--from", dest="date_from", help="date de debut AAAA-MM-JJ")
    ap.add_argument("--to", dest="date_to", help="date de fin AAAA-MM-JJ (defaut : aujourd'hui)")
    ap.add_argument("--last-month", action="store_true", help="mois calendaire precedent")
    ap.add_argument("--datetype", choices=["edat", "pdat"], default="edat",
                    help="edat = date d'entree dans PubMed (defaut, recommande) ; pdat = date de publication")
    ap.add_argument("--journals", default=",".join(JOURNALS),
                    help="liste de codes separes par des virgules (defaut : toutes)")
    ap.add_argument("--methode", choices=["ml", "mots-cles"], default="ml",
                    help="ml = modele entraine (defaut) ; mots-cles = secours sans modele")
    ap.add_argument("--seuil", type=float, default=DEFAULT_THRESHOLD,
                    help="probabilite minimale (0-1) pour ranger un article dans une matiere "
                         f"(defaut : {DEFAULT_THRESHOLD}, volontairement bas)")
    ap.add_argument("--seuil-secondaire", type=float, default=DEFAULT_SECONDARY,
                    help="probabilite a partir de laquelle une matiere supplementaire est signalee "
                         f"(defaut : {DEFAULT_SECONDARY}) ; l'article apparait alors aussi dans cette matiere")
    ap.add_argument("--modele", default=str(MODEL_PATH), help="chemin du modele entraine")
    ap.add_argument("--outdir", default="rapports", help="dossier de sortie (defaut : ./rapports)")
    ap.add_argument("--email-to", help="envoyer le rapport par email (config SMTP_* en variables d'environnement)")
    ap.add_argument("--from-xml", help="(test) lire un fichier XML PubMed local au lieu d'interroger le reseau")
    args = ap.parse_args()

    d1, d2 = resolve_period(args)
    log(f"Periode : {d1} -> {d2} ({args.datetype})")
    model = charger_modele(args.modele) if args.methode == "ml" else None   # echec rapide, avant le reseau

    raw, errors = [], []
    if args.from_xml:
        root = ET.parse(args.from_xml).getroot()
        for a in root.iter("PubmedArticle"):
            raw.append(parse_article(a, journal_code_from_xml(a)))
    else:
        codes = [c.strip() for c in args.journals.split(",") if c.strip()]
        unknown = [c for c in codes if c not in JOURNALS]
        if unknown:
            sys.exit(f"Codes de revue inconnus : {unknown}. Valides : {list(JOURNALS)}")
        for code in codes:
            try:
                pmids = search_pmids(JOURNALS[code][0], d1, d2, args.datetype)
                log(f"{code}: {len(pmids)} articles")
                raw.extend(parse_article(a, code) for a in fetch_xml(pmids))
            except Exception as e:     # une revue en panne ne doit pas bloquer les autres
                log(f"{code}: ERREUR {e}")
                errors.append(code)
        if len(errors) == len(codes):
            sys.exit("Aucune revue n'a pu etre interrogee (reseau ?).")

    seen, arts = set(), []
    for r in raw:
        if r["pmid"] in seen:
            continue
        seen.add(r["pmid"])
        arts.append(filtrer_espece(r))

    retenus = [a for a in arts if a["keep"]]
    if model is not None:
        matieres_ml(retenus, model, args.seuil, args.seuil_secondaire)
        note = f"classement par modele, seuil {args.seuil:.0%} (matieres supplementaires des {args.seuil_secondaire:.0%})"
    else:
        for a in retenus:
            matieres_mots_cles(a)
        note = "classement par mots-cles (sans pourcentage)"

    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    stem = f"rapport_{d1}_{d2}"
    html_path, csv_path = outdir / f"{stem}.html", outdir / f"{stem}.csv"
    html_path.write_text(build_html(arts, d1, d2, args.datetype, errors, note), encoding="utf-8")
    write_csv(csv_path, arts)

    log(f"{len(arts)} articles, {len(retenus)} retenus -> {html_path}")
    if args.email_to:
        send_email(args.email_to, f"Veille veterinaire {d1} - {d2} ({len(retenus)} articles)",
                   f"{len(retenus)} articles retenus sur {len(arts)} analyses. Rapport en piece jointe.",
                   [html_path, csv_path])
    print(html_path)
    return 0 if not errors else 3


if __name__ == "__main__":
    sys.exit(main())
