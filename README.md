# Veille vétérinaire — petits animaux

Deux scripts :
- `entrainer_modele.py` : entraîne le classifieur (à lancer une fois, puis de temps en temps)
- `veille_vet.py` : récupère les articles des 6 revues sur PubMed, écarte les grands animaux, classe le reste

Prérequis : Python 3.8+ et `pip install scikit-learn`.

## Comment ça marche

1. **Filtre espèce** (règles) : on garde chien/chat/NAC, on écarte cheval/bovin/etc. JFMS et JSAP sont gardées en entier.
2. **Classification** (machine learning, multi-étiquettes) : TF-IDF sur titre + résumé, puis **un modèle indépendant par matière**
   (« cet article relève-t-il de cette matière ? »). Chaque matière a donc sa propre probabilité, qui ne se partage pas avec les
   autres : un lymphome peut être à 85 % en oncologie **et** 70 % en hématologie. L'article est rangé dans la matière la plus
   probable si elle atteint le **seuil bas de 10 %** (inclusif). Toutes les autres matières à partir de **30 %**
   (`--seuil-secondaire`) sont aussi signalées, et l'article **apparaît dans chacune de ces sections** (marqué « déjà classé en : … »).
   Sous le seuil, l'article va dans « Hors catégories suivies » avec sa meilleure piste, pour ne rien perdre.
3. **Rapport** : HTML groupé par matière avec les % de confiance, et CSV complet.

## Étape 1 — entraîner (une fois)

```bash
python3 entrainer_modele.py              # 6 ans d'historique
```
Pas d'étiquetage manuel au départ : PubMed fournit les étiquettes. Les articles anciens des 6 revues (chiens/chats, hors
6 derniers mois) portent des descripteurs MeSH (« Kidney Diseases », « Neoplasms »…) qui servent d'étiquettes automatiques.
Le modèle apprend ensuite à retrouver la matière à partir du seul titre + résumé, car les MeSH n'existent pas encore pour
les articles récents. Le script affiche en fin d'entraînement une évaluation sur des articles mis de côté, et crée `modele_matieres.joblib`.

## Étape 2 — lancer la veille

```bash
python3 veille_vet.py                    # 7 derniers jours
python3 veille_vet.py --days 14
python3 veille_vet.py --last-month       # pour le mensuel
python3 veille_vet.py --from 2026-10-01 --to 2026-10-31
python3 veille_vet.py --seuil 0.10       # encore plus permissif
python3 veille_vet.py --methode mots-cles   # secours sans modèle
```
Sorties dans `./rapports/` : `rapport_<début>_<fin>.html` et `.csv`.

## Vérification manuelle et corrections

Le CSV a une colonne **`matiere_corrigee`** vide, et une colonne de probabilité par matière (`p_...`). Remplissez-la pour les
articles mal classés (les débuts suffisent : `uro`, `hemato`, `neuro`, `onco`, `gastro`, `pancreas`, `pneumo`, `infect`,
`endocrino`, ou `autre` ; **plusieurs matières possibles** : `onco+hemato`). Puis double-cliquez sur
**`4_envoyer_corrections.bat`** : il extrait vos corrections vers `corrections\` (un fichier par rapport, mis à jour sans doublon)
et, si Git et un dépôt distant sont configurés, les envoie. Sinon, envoyez simplement le contenu du dossier `corrections\`.

Pour réentraîner avec toutes les corrections : `2_entrainer.bat`. Il lit automatiquement `corrections\*.csv`. Les corrections
pèsent 5 fois plus que les articles étiquetés automatiquement : le modèle s'améliore mois après mois. Les notices
téléchargées sont gardées dans `cache_notices.json` : les réentraînements suivants sont beaucoup plus rapides.

## Partage du projet (Git)

Le dépôt contient le code, les lanceurs et le dossier `corrections\`. Ne sont **pas** versionnés : `rapports\`, le modèle
(`*.joblib`), le cache et les journaux (voir `.gitignore`). Chaque personne entraîne son modèle en local (`2_entrainer.bat`) ;
les corrections de tout le monde, elles, circulent par le dépôt.

```bash
git clone <adresse-du-depot> veille_vet
cd veille_vet
1_installer.bat          # une fois (Python + scikit-learn)
2_entrainer.bat          # une fois, puis après de nouvelles corrections
3_lancer_veille.bat      # le rapport
```
Récupérer les corrections des autres : `git pull`, puis `2_entrainer.bat`.

## Planification mensuelle

Sous Windows, le plus simple : Planificateur de tâches → tâche mensuelle → programme `3_lancer_veille.bat` avec l'argument
`silencieux` (pas d'ouverture du rapport, pas de pause). Les rapports s'accumulent dans `rapports\`, et le journal du dernier
lancement est dans `dernier_lancement.log`. Le PC qui planifie doit avoir Python + scikit-learn (`1_installer.bat`) et le
modèle (`2_entrainer.bat`, ou copier `modele_matieres.joblib`).

**Linux / macOS (cron)** — le 2 de chaque mois à 7h :
```
0 7 2 * * cd /chemin/vers/le/dossier && /usr/bin/python3 veille_vet.py --last-month >> veille.log 2>&1
```
**Windows** : Planificateur de tâches, programme `python`, arguments `veille_vet.py --last-month`, dossier de départ = celui du script.

## Email (optionnel)

Variables `SMTP_HOST`, `SMTP_PORT` (587), `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM`, puis `--email-to adresse@exemple.fr`
(Gmail : mot de passe d'application). Facultatif : `NCBI_API_KEY` (plus rapide), `NCBI_EMAIL`.

## Limites à connaître

- Les étiquettes MeSH d'entraînement sont larges (un article « Infections » peut parler d'une plaie infectée) : le modèle
  hérite de ce bruit, d'où l'intérêt du seuil bas et des corrections.
- PubMed plafonne une recherche à 10 000 résultats : si l'entraînement l'indique, réduisez `--annees`.
- Les articles sans résumé sont classés sur leur seul titre, donc avec une confiance plus faible.
- Date utilisée : date d'entrée dans PubMed (`--datetype edat`), plus fiable que la date de publication.
