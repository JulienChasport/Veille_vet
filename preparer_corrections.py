#!/usr/bin/env python3
"""
preparer_corrections.py - Extrait les corrections manuelles des rapports vers corrections/.

Lit rapports/*.csv, garde uniquement les lignes dont la colonne 'matiere_corrigee' est remplie,
et ecrit corrections/<utilisateur>_<rapport>.csv (pmid ; titre ; matiere_corrigee).
Relancer le script met a jour le meme fichier : rien ne s'accumule en double.
"""
import csv
import getpass
import re
import sys
from pathlib import Path

ICI = Path(__file__).parent
SORTIE = ICI / "corrections"


def main():
    SORTIE.mkdir(exist_ok=True)
    user = re.sub(r"\W+", "", getpass.getuser()) or "utilisateur"
    total = 0
    for f in sorted((ICI / "rapports").glob("*.csv")):
        with open(f, newline="", encoding="utf-8-sig") as fh:
            lignes = [r for r in csv.DictReader(fh, delimiter=";")
                      if (r.get("matiere_corrigee") or "").strip()]
        if not lignes:
            continue
        cible = SORTIE / f"{user}_{f.stem}.csv"
        with open(cible, "w", newline="", encoding="utf-8-sig") as out:
            w = csv.writer(out, delimiter=";")
            w.writerow(["pmid", "titre", "matiere_corrigee"])
            for r in lignes:
                w.writerow([r["pmid"], r.get("title", ""), r["matiere_corrigee"].strip()])
        print(f"{len(lignes):4d} corrections -> {cible.relative_to(ICI)}")
        total += len(lignes)
    if not total:
        print("Aucune correction trouvee : remplissez la colonne 'matiere_corrigee' des CSV dans rapports\\.")
        return 1
    print(f"\n{total} corrections pretes dans le dossier corrections\\.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
