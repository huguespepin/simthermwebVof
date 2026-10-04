"""
scenarios.py — Calculs comparatifs fournis à l'expert (GPT ou règles).

Objectif : que les recommandations s'appuient sur des gains CALCULÉS par
le moteur SimTherm et non estimés par le modèle de langage. Pour une
configuration donnée, ce module :

  1. classe les meilleurs matériaux de mur et de toiture du pays
     (même score composite que l'onglet « Simulation matériaux ») ;
  2. simule des scénarios « et si » (toiture claire, meilleur mur,
     protection solaire des fenêtres, mur plus épais, etc.) en
     modifiant UN paramètre à la fois, puis un scénario cumulé.

Aucune dépendance à Streamlit : le module est testable seul.

Convention : `params` est le dictionnaire des arguments nommés de
core.thermal_calc.calculer_thermique_complet pour la configuration de
l'utilisateur.
"""

from typing import Iterable, Optional

from core.constants import ALPHA_TOIT_TYPIQUE, FS_VITRAGE_TYPIQUE
from core.thermal_calc import calculer_thermique_complet, calc_score_simtherm

# Valeurs « et si » : repères indicatifs non sourcés (cf. constants.py)
ALPHA_CLAIR = ALPHA_TOIT_TYPIQUE["Couleur claire"]                      # 0.40
ALPHA_REFLECHISSANT = ALPHA_TOIT_TYPIQUE["Blanc ou peinture réfléchissante"]  # 0.30
FS_BRISE_SOLEIL = FS_VITRAGE_TYPIQUE["Fenêtre protégée par brise-soleil extérieur"]  # 0.30
SUPPLEMENT_EPAISSEUR_MUR_M = 0.10


def _calc(params: dict, **modifs):
    """Relance le moteur avec quelques paramètres modifiés."""
    return calculer_thermique_complet(**{**params, **modifs})


def _modifs_materiau(m, type_paroi: str) -> dict:
    """
    Paramètres à substituer pour remplacer le matériau d'une paroi.
    Mur : l'épaisseur de l'utilisateur est conservée (comparaison à
    épaisseur égale). Toiture : le nom du matériau contient souvent son
    épaisseur (ex. « Chaume standard 15cm »), on utilise donc l'épaisseur
    de référence de la base quand elle existe, sinon celle de l'utilisateur.
    """
    suffixe = "mur" if type_paroi == "mur" else "toit"
    modifs = {f"lambda_{suffixe}": m.lambda_val, f"rho_{suffixe}": m.rho, f"cp_{suffixe}": m.cp}
    ep_ref = getattr(m, "epaisseur_ref_cm", None)
    if type_paroi == "toit" and ep_ref:
        modifs["epaisseur_toit"] = ep_ref / 100.0
    return modifs


def classer_materiaux(params: dict, candidats: Iterable, type_paroi: str, n: int = 5) -> list[dict]:
    """
    Classe les candidats selon le score composite SimTherm (U et déphasage),
    en gardant l'épaisseur et les autres paramètres de l'utilisateur.
    Retourne les n meilleurs sous forme de dictionnaires.
    """
    lignes = []
    deja_vus: dict[str, int] = {}
    for m in candidats:
        try:
            r = _calc(params, **_modifs_materiau(m, type_paroi))
        except Exception:
            continue
        u = r.U_mur if type_paroi == "mur" else r.U_toit
        phi = r.phi_mur_h if type_paroi == "mur" else r.phi_toit_h
        ligne = {
            "materiau": m,
            "nom": m.nom,
            "epaisseur_m": _modifs_materiau(m, type_paroi).get(
                "epaisseur_toit" if type_paroi == "toit" else "epaisseur_mur",
                params["epaisseur_mur"] if type_paroi == "mur" else params["epaisseur_toit"]),
            "lambda": m.lambda_val, "rho": m.rho, "cp": m.cp,
            "U": u, "phi_h": phi,
            "score": calc_score_simtherm(u, phi),
            "t_int_max": r.t_int_max,
            "classe_pic": r.classe_pic.lettre,
            "cout": m.cout_local, "monnaie": m.monnaie,
            "disponibilite": m.disponibilite,
            "niveau_confiance": m.niveau_confiance,
        }
        # Dédoublonnage par nom : on garde l'entrée qui porte un coût local
        if m.nom in deja_vus:
            i = deja_vus[m.nom]
            if lignes[i]["cout"] is None and ligne["cout"] is not None:
                lignes[i] = ligne
            continue
        deja_vus[m.nom] = len(lignes)
        lignes.append(ligne)
    lignes.sort(key=lambda d: d["score"], reverse=True)
    return lignes[:n]


def _ligne(libelle: str, r, base, note: str = "") -> dict:
    return {
        "libelle": libelle,
        "t_int_moy": r.t_int_moy,
        "t_int_max": r.t_int_max,
        "delta_max": r.t_int_max - base.t_int_max,
        "classe_ressentie": r.classe_ressentie.lettre,
        "classe_pic": r.classe_pic.lettre,
        "note": note,
    }


def simuler_scenarios(params: dict, base, meilleur_mur=None, meilleure_toit=None) -> list[dict]:
    """
    Simule des scénarios d'amélioration, un levier à la fois, puis leur
    cumul. Un scénario n'est proposé que s'il a un sens (par exemple
    pas de « toiture claire » si la toiture l'est déjà).

    Retourne une liste de dictionnaires triée par gain décroissant sur
    la température intérieure maximale (le plus négatif d'abord), le
    scénario cumulé étant placé en dernier.
    """
    # (libellé, modifications, note, cumulable)
    simples: list[tuple[str, dict, str, bool]] = []
    noms_cumul: dict[str, str] = {}

    alpha = params.get("alpha_toit", 0.6)
    if alpha > ALPHA_CLAIR + 1e-9:
        simples.append((f"Toiture de couleur claire (absorptivité α = {ALPHA_CLAIR:.2f})",
                        {"alpha_toit": ALPHA_CLAIR}, "valeur indicative non sourcée", True))
        noms_cumul["alpha_toit"] = "toiture claire"
    if alpha > ALPHA_REFLECHISSANT + 1e-9:
        simples.append((f"Toiture blanche ou peinture réfléchissante (α = {ALPHA_REFLECHISSANT:.2f})",
                        {"alpha_toit": ALPHA_REFLECHISSANT}, "valeur indicative non sourcée", False))

    fs = params.get("fs_vitrage", 0.6)
    if params.get("surface_vitree", 0) > 0 and fs > FS_BRISE_SOLEIL + 1e-9:
        simples.append((f"Fenêtres protégées par un brise-soleil extérieur (FS = {FS_BRISE_SOLEIL:.2f})",
                        {"fs_vitrage": FS_BRISE_SOLEIL}, "valeur indicative non sourcée", True))
        noms_cumul["fs_vitrage"] = "brise-soleil"

    if meilleur_mur is not None and meilleur_mur.lambda_val != params["lambda_mur"]:
        simples.append((f"Mur remplacé par : {meilleur_mur.nom} (même épaisseur)",
                        _modifs_materiau(meilleur_mur, "mur"), "", True))
        noms_cumul["lambda_mur"] = "meilleur mur"

    if meilleure_toit is not None and meilleure_toit.lambda_val != params["lambda_toit"]:
        m = _modifs_materiau(meilleure_toit, "toit")
        simples.append((f"Toiture remplacée par : {meilleure_toit.nom} "
                        f"(épaisseur de référence {m.get('epaisseur_toit', params['epaisseur_toit']):.3f} m)",
                        m, "", True))
        noms_cumul["lambda_toit"] = "meilleure toiture"

    ep = params["epaisseur_mur"]
    simples.append((f"Mur plus épais de {int(SUPPLEMENT_EPAISSEUR_MUR_M * 100)} cm "
                    f"({ep:.2f} m vers {ep + SUPPLEMENT_EPAISSEUR_MUR_M:.2f} m)",
                    {"epaisseur_mur": ep + SUPPLEMENT_EPAISSEUR_MUR_M}, "", False))

    nv = params.get("nv", 1.0)
    simples.append((f"Renouvellement d'air doublé ({nv:.1f} vers {2 * nv:.1f} vol/h)",
                    {"nv": 2 * nv},
                    "le moteur applique la même ventilation jour et nuit : ce scénario ne "
                    "représente pas une ventilation nocturne ciblée", False))

    resultats = []
    cumulables: list[tuple[dict, str]] = []
    for libelle, modifs, note, cumulable in simples:
        try:
            ligne = _ligne(libelle, _calc(params, **modifs), base, note)
        except Exception:
            continue
        resultats.append(ligne)
        if cumulable and ligne["delta_max"] < 0:
            cle = next(k for k in modifs if k in noms_cumul)
            cumulables.append((modifs, noms_cumul[cle]))
    resultats.sort(key=lambda d: d["delta_max"])

    # Cumul : uniquement les leviers qui, pris seuls, réduisent la température de pointe
    if len(cumulables) >= 2:
        modifs_cumul: dict = {}
        for modifs, _ in cumulables:
            modifs_cumul.update(modifs)
        try:
            resultats.append(_ligne("Cumul des leviers favorables : " + " + ".join(n for _, n in cumulables),
                                    _calc(params, **modifs_cumul), base))
        except Exception:
            pass
    return resultats
