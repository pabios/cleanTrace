# Permet à pytest d'importer le paquet cleantrace depuis la racine du projet.
#
# CLEANTRACE_STRING_STORAGE=python|pyarrow choisit le moteur de texte de pandas : avec
# pyarrow (cas d'Anaconda), les expressions régulières passent par RE2, plus restrictif.
import os

import pandas as pd

if os.environ.get("CLEANTRACE_STRING_STORAGE"):
    pd.set_option("mode.string_storage", os.environ["CLEANTRACE_STRING_STORAGE"])
