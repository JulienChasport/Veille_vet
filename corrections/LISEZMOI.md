# Corrections

Ce dossier contient les corrections manuelles de matières. Le script d'entraînement (`2_entrainer.bat`)
les lit automatiquement et les fait peser 5 fois plus que les étiquettes automatiques.

Format : `pmid;titre;matiere_corrigee`. La matière peut s'écrire en abrégé (`uro`, `hemato`, `infect`, `endocrino`,
`neuro`, `onco`, `gastro`, `pancreas`, `pneumo`), avec plusieurs matières séparées par `+` (`onco+hemato`),
ou `autre` pour un article hors de vos matières.

Ne pas éditer à la main : ces fichiers sont produits par `4_envoyer_corrections.bat`.
