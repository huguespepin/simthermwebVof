"""
thermal_calc.py — Moteur de calcul thermique de SimTherm.

Implémente :
- ISO 6946:2017 (coefficient de transmission thermique U)
- ISO 13786:2017 (profondeur de pénétration périodique delta, éq. 11)
- Asan H. (1998), DOI:10.1016/S0378-7788(98)00030-9 (facteur d'amortissement f)
- Approximation du milieu semi-infini pour le déphasage phi
  (écart ~6% vs ISO 13786 rigoureux, documenté au Chapitre 2.2.3 du mémoire)
- Méthode d'admittance CIBSE Guide A ch.5 (Danter 1960, Loudon 1968)
  pour les températures intérieures moyenne et de pointe

Toutes les fonctions sont pures (aucun effet de bord, aucune dépendance
à Streamlit ou à un fichier) — elles sont testables unitairement et
constituent le pilier de la validation analytique (H2, Chapitre 2.2.6).
"""

import math
from dataclasses import dataclass
from typing import Optional, Literal

from core.constants import (
    RSI_MUR, RSE_MUR, RSI_TOIT, RSE_TOIT, PERIODE_JOUR_S, COEFF_VENT,
    SEUILS_CONFORT_STANDARD, SEUILS_CONFORT_SENSIBLE, DESCRIPTIONS_CLASSES,
    USAGES_SENSIBLES, SCORE_PHI_PLAFOND_H,
)


# ============================================================
# ISO 6946:2017 — Coefficient de transmission thermique U
# ============================================================
def calc_U(lambda_val: float, epaisseur: float,
           type_paroi: Literal["mur", "toit"] = "mur") -> float:
    """
    Calcule le coefficient de transmission thermique U (W/m²K).

    U = 1 / (Rsi + e/lambda + Rse)   — ISO 6946:2017

    Args:
        lambda_val: conductivité thermique du matériau (W/m·K)
        epaisseur: épaisseur de la paroi (m)
        type_paroi: "mur" (flux horizontal) ou "toit" (flux ascendant),
                    détermine les résistances superficielles Rsi/Rse

    Returns:
        U en W/m²K
    """
    if lambda_val <= 0 or epaisseur <= 0:
        raise ValueError("lambda_val et epaisseur doivent être strictement positifs")

    if type_paroi == "mur":
        rsi, rse = RSI_MUR, RSE_MUR
    elif type_paroi == "toit":
        rsi, rse = RSI_TOIT, RSE_TOIT
    else:
        raise ValueError(f"type_paroi invalide : {type_paroi!r} (attendu 'mur' ou 'toit')")

    return 1.0 / (rsi + epaisseur / lambda_val + rse)


def calc_U_multicouche(lambda_val: float, epaisseur: float,
                        type_paroi: Literal["mur", "toit"] = "mur",
                        epaisseur_enduit_int: float = 0.0,
                        epaisseur_enduit_ext: float = 0.0,
                        lambda_enduit_int: float = 1.15,
                        lambda_enduit_ext: float = 1.15) -> float:
    """
    Calcule U pour une paroi à trois couches (enduit intérieur + matériau
    porteur + enduit extérieur), par mise en série des résistances
    thermiques — ISO 6946:2017, clause 6.2 (parois multicouches planes).

    U = 1 / (Rsi + e_enduit_int/lambda_enduit_int + e/lambda
              + e_enduit_ext/lambda_enduit_ext + Rse)

    Cas particulier : si les deux épaisseurs d'enduit sont nulles, cette
    fonction est strictement équivalente à calc_U() (paroi monocouche).

    Args:
        lambda_val: conductivité du matériau porteur (W/m·K)
        epaisseur: épaisseur du matériau porteur (m)
        type_paroi: "mur" ou "toit"
        epaisseur_enduit_int: épaisseur enduit intérieur (m), 0 = absent
        epaisseur_enduit_ext: épaisseur enduit extérieur (m), 0 = absent
        lambda_enduit_int: conductivité enduit intérieur (W/m·K),
                           défaut 1,15 (enduit ciment/mortier bâtard usuel)
        lambda_enduit_ext: conductivité enduit extérieur (W/m·K)

    Returns:
        U en W/m²K

    Note méthodologique : seul le coefficient U (comportement statique)
    est traité en toute rigueur multicouche ici. Le comportement
    dynamique (delta, xi, f, phi) demeure calculé sur le seul matériau
    porteur (approximation monocouche, cf. Chapitre 2.2.7) : les enduits
    étant minces (1-2 cm usuels) et de faible masse par rapport au mur
    ou à la toiture, leur contribution à l'inertie thermique globale est
    considérée négligeable en première approximation. Cette limite est
    documentée explicitement plutôt que dissimulée.
    """
    if lambda_val <= 0 or epaisseur <= 0:
        raise ValueError("lambda_val et epaisseur doivent être strictement positifs")
    if epaisseur_enduit_int < 0 or epaisseur_enduit_ext < 0:
        raise ValueError("Les épaisseurs d'enduit ne peuvent pas être négatives")

    if type_paroi == "mur":
        rsi, rse = RSI_MUR, RSE_MUR
    elif type_paroi == "toit":
        rsi, rse = RSI_TOIT, RSE_TOIT
    else:
        raise ValueError(f"type_paroi invalide : {type_paroi!r} (attendu 'mur' ou 'toit')")

    r_enduit_int = (epaisseur_enduit_int / lambda_enduit_int) if epaisseur_enduit_int > 0 else 0.0
    r_enduit_ext = (epaisseur_enduit_ext / lambda_enduit_ext) if epaisseur_enduit_ext > 0 else 0.0
    r_porteur = epaisseur / lambda_val

    r_totale = rsi + r_enduit_int + r_porteur + r_enduit_ext + rse
    return 1.0 / r_totale


# ============================================================
# ISO 13786:2017, éq. 11 — Profondeur de pénétration périodique
# ============================================================
def calc_delta(lambda_val: float, rho: float, cp: float,
                periode_s: float = PERIODE_JOUR_S) -> float:
    """
    Calcule la profondeur de pénétration périodique delta (m).

    delta = sqrt(lambda * T / (pi * rho * Cp))   — ISO 13786:2017 éq.11

    Args:
        lambda_val: conductivité thermique (W/m·K)
        rho: masse volumique (kg/m³)
        cp: capacité thermique massique (J/kg·K)
        periode_s: période du cycle (s), 86400 par défaut (24h)

    Returns:
        delta en m
    """
    if lambda_val <= 0 or rho <= 0 or cp <= 0:
        raise ValueError("lambda_val, rho et cp doivent être strictement positifs")
    return math.sqrt(lambda_val * periode_s / (math.pi * rho * cp))


def calc_xi(epaisseur: float, delta: float) -> float:
    """Calcule le rapport adimensionnel xi = e / delta."""
    if delta <= 0:
        raise ValueError("delta doit être strictement positif")
    return epaisseur / delta


# ============================================================
# Asan H. (1998) — Facteur d'amortissement (decrement factor)
# DOI:10.1016/S0378-7788(98)00030-9
# ============================================================
def calc_f_amortissement(xi: float) -> float:
    """
    Calcule le facteur d'amortissement f (sans dimension, 0 < f <= 1).

    f = 1 / sqrt(sinh(xi)^2 + cos(xi)^2)   — Asan (1998)

    f=1 : paroi thermiquement transparente (aucun amortissement)
    f→0 : paroi épaisse, amortissement quasi-total

    NOTE IMPORTANTE : ne pas confondre avec l'approximation
    f ≈ exp(-xi), qui omet un préfacteur 2 et sous-estime
    systématiquement l'amortissement réel (cf. Chapitre 2.2.3).
    """
    denom = math.sqrt(math.sinh(xi) ** 2 + math.cos(xi) ** 2)
    if denom == 0:
        return 1.0
    return 1.0 / denom


# ============================================================
# Approximation milieu semi-infini — Déphasage thermique phi
# (Carslaw & Jaeger). Écart ~6% vs ISO 13786 rigoureux (arg Y12),
# documenté et assumé au Chapitre 2.2.3 du mémoire.
# ============================================================
def calc_phi_semi_infini(xi: float, periode_s: float = PERIODE_JOUR_S) -> float:
    """
    Calcule le déphasage thermique phi (heures) selon l'approximation
    du milieu semi-infini.

    phi = xi * (T / 2*pi)   [en secondes, puis converti en heures]

    Équivalent à la formule Excel historique :
        phi = e * sqrt(rho*Cp / (pi*lambda*T)) * (T_heures/2)
    (le littéral "12" de la version Excel encode T_heures/2 = 12h,
    valable uniquement si T=86400s ; ici la période est un paramètre
    explicite pour éviter cette fragilité — cf. limite documentée
    au Chapitre 2.2.7 du mémoire).
    """
    periode_h = periode_s / 3600.0
    phi_h = xi * (periode_h / (2 * math.pi))
    return phi_h


# ============================================================
# Coefficients de transmission globaux H (W/K)
# ============================================================
def calc_H_paroi(U: float, surface: float) -> float:
    """H_paroi = U * A"""
    return U * surface


def calc_H_ventilation(nv: float, volume: float) -> float:
    """H_vent = 0.34 * Nv * V   — CIBSE Guide A"""
    return COEFF_VENT * nv * volume


# ============================================================
# Facteur d'amortissement global de l'enveloppe f_env
# ============================================================
def calc_f_env(f_mur: float, H_mur: float, f_toit: float, H_toit: float,
               H_vent: float, H_baies: float = 0.0) -> float:
    """
    f_env = (f_mur*H_mur + f_toit*H_toit + f_vent*H_vent + f_baies*H_baies) / H_total

    La ventilation et les baies vitrées sont supposées sans inertie
    (f_vent = f_baies = 1, aucune capacité de stockage thermique) —
    cf. CIBSE admittance procedure.
    """
    H_total = H_mur + H_toit + H_vent + H_baies
    if H_total <= 0:
        raise ValueError("H_total doit être strictement positif")
    f_vent = 1.0
    f_baies = 1.0
    return (f_mur * H_mur + f_toit * H_toit + f_vent * H_vent + f_baies * H_baies) / H_total


# ============================================================
# Apports thermiques moyens journaliers Q_moy (W)
# ============================================================
def calc_Q_solaire_toit(alpha: float, U_toit: float, irradiance_moy: float,
                          surface_toit: float, rse: float = RSE_TOIT) -> float:
    """
    Q_toit = alpha * Rse * U_toit * I_moy * A_toit   (méthode sol-air simplifiée)
    """
    return alpha * rse * U_toit * irradiance_moy * surface_toit


def calc_Q_solaire_baies(fs: float, irradiance_moy: float, surface_baies: float) -> float:
    """Q_baies = FS * I_moy * A_baies"""
    return fs * irradiance_moy * surface_baies


def calc_Q_internes(apports_w_m2: float, surface_plancher: float) -> float:
    """Q_int = apports * A_plancher"""
    return apports_w_m2 * surface_plancher


# ============================================================
# Températures intérieures — Méthode d'admittance CIBSE
# ============================================================
def calc_T_int_moy(t_ext_moy_j: float, Q_moy: float, H_total: float) -> float:
    """T°int_moy = T°ext_moy_j + Q_moy / H_total"""
    if H_total <= 0:
        raise ValueError("H_total doit être strictement positif")
    return t_ext_moy_j + Q_moy / H_total


def calc_T_int_max(t_int_moy: float, f_env: float, amplitude: float) -> float:
    """T°int_max = T°int_moy + f_env * A/2"""
    return t_int_moy + f_env * amplitude / 2.0


def calc_T_int_min(t_int_moy: float, f_env: float, amplitude: float) -> float:
    """T°int_min = T°int_moy - f_env * A/2"""
    return t_int_moy - f_env * amplitude / 2.0


def calc_T_ext_moy_j(t_ext_max: float, amplitude: float) -> float:
    """T°ext_moy_j = Tmax - A/2  (température moyenne du jour dimensionnant)"""
    return t_ext_max - amplitude / 2.0


# ============================================================
# Classification du confort adaptatif
# ============================================================
@dataclass
class ClasseConfort:
    lettre: str            # "A", "B", "C" ou "D"
    description: str       # "Confort optimal", etc.
    delta_t: float         # écart signé T°int - Tn


def classifier_confort(t_int: float, tn: float, usage: str) -> ClasseConfort:
    """
    Classifie le confort thermique selon l'écart |T°int - Tn| et les
    seuils différenciés par usage (cf. Chapitre 2.2.4, Tableau 2.1).

    Args:
        t_int: température intérieure évaluée (°C) — moyenne OU pic
        tn: température de neutralité adaptative (°C)
        usage: type de bâtiment (chaîne exacte de BD_BATIMENTS)

    Returns:
        ClasseConfort(lettre, description, delta_t)
    """
    delta_t = t_int - tn
    abs_delta = abs(delta_t)

    seuils = SEUILS_CONFORT_SENSIBLE if usage in USAGES_SENSIBLES else SEUILS_CONFORT_STANDARD

    if abs_delta <= seuils["A"]:
        lettre = "A"
    elif abs_delta <= seuils["B"]:
        lettre = "B"
    elif abs_delta <= seuils["C"]:
        lettre = "C"
    else:
        lettre = "D"

    return ClasseConfort(lettre=lettre, description=DESCRIPTIONS_CLASSES[lettre], delta_t=delta_t)


# ============================================================
# Score composite SimTherm (pour classement TOP 5 matériaux)
# ============================================================
def calc_score_simtherm(U: float, phi_h: float) -> float:
    """
    Score = 100 / (1+U) * min(1, phi/12)

    Pondère isolation (U bas => mieux) et inertie (phi élevé => mieux,
    plafonné à 12h car au-delà le gain de confort marginal est nul
    pour un cycle de 24h).
    """
    facteur_inertie = min(1.0, phi_h / SCORE_PHI_PLAFOND_H)
    return 100.0 / (1.0 + U) * facteur_inertie


# ============================================================
# Pipeline complet — orchestration de bout en bout
# ============================================================
@dataclass
class ResultatThermique:
    U_mur: float
    U_toit: float
    delta_mur: float
    delta_toit: float
    xi_mur: float
    xi_toit: float
    f_mur: float
    f_toit: float
    phi_mur_h: float
    phi_toit_h: float
    H_mur: float
    H_toit: float
    H_vent: float
    H_baies: float
    H_vitree: float
    H_porte: float
    H_total: float
    f_env: float
    Q_solaire_toit: float
    Q_solaire_baies: float
    Q_internes: float
    Q_moy: float
    t_ext_moy_j: float
    t_int_moy: float
    t_int_max: float
    t_int_min: float
    classe_ressentie: ClasseConfort
    classe_pic: ClasseConfort


def calculer_thermique_complet(
    # Climat
    t_ext_max: float, amplitude: float, tn: float, ghi_kwh_m2_j: float,
    # Géométrie
    surface_mur: float, surface_toit: float, volume: float,
    # Ouvertures — fenêtres (vitrées, transmettent le rayonnement solaire)
    surface_vitree: float, U_vitrage: float, fs_vitrage: float,
    # Ouvertures — portes (opaques ou semi-vitrées, transmission solaire distincte)
    surface_porte: float, U_porte: float, fs_porte: float,
    # Mur
    lambda_mur: float, rho_mur: float, cp_mur: float, epaisseur_mur: float,
    # Toiture
    lambda_toit: float, rho_toit: float, cp_toit: float, epaisseur_toit: float,
    # Bâtiment / usage
    usage: str, apports_internes: float, nv: float,
    # Facteurs solaires toiture
    alpha_toit: float,
    # Enduits (optionnels — couches minces de finition, cf. calc_U_multicouche)
    epaisseur_enduit_int: float = 0.0, epaisseur_enduit_ext: float = 0.0,
    lambda_enduit: float = 1.15,
    lambda_enduit_ext: Optional[float] = None,
    # Orientation & implantation (Chapitre 2.2.3.4 et 2.2.3.5)
    # Valeurs neutres par défaut => rétrocompatibilité stricte
    facteur_orientation: float = 1.0,
    delta_ilot_chaleur: float = 0.0,
) -> ResultatThermique:
    """
    Exécute la chaîne de calcul complète, de la géométrie/matériaux
    jusqu'à la classification du confort. Équivalent fonctionnel exact
    du classeur Excel SimTherm — cf. tests/test_thermal_calc.py
    (classe TestCalculerThermiqueComplet) pour la preuve de cohérence.

    Les ouvertures (baies) sont désormais scindées en deux catégories
    physiquement distinctes :
    - Fenêtres vitrées : transmission solaire directe (FS) + conduction (U)
    - Portes (pleines ou vitrées) : conduction (U) + transmission solaire
      propre à leur type (FS=0 pour une porte opaque bois/métal, FS>0
      uniquement pour une porte-baie vitrée)
    Cette distinction évite de surestimer les apports solaires en
    appliquant un facteur solaire de fenêtre à une porte pleine opaque.

    Les enduits de finition du mur (intérieur et/ou extérieur), lorsque
    renseignés, sont intégrés au calcul de U_mur par mise en série des
    résistances thermiques (cf. calc_U_multicouche). Par défaut
    (épaisseurs nulles), le comportement est strictement identique à la
    version monocouche antérieure — aucune régression introduite.

    Orientation des fenêtres (Chapitre 2.2.3.4) : facteur_orientation
    module l'apport solaire des fenêtres uniquement (pas des portes,
    pas des murs opaques). Valeurs typiques 0,65 (nord) à 1,15 (ouest).
    Valeur par défaut 1,0 => aucun effet (rétrocompatibilité stricte).

    Zone d'implantation (Chapitre 2.2.3.5) : delta_ilot_chaleur est
    ajouté à t_ext_max en tout début de chaîne, avant tout calcul.
    Représente l'effet d'îlot de chaleur urbain (0 rural, +1 semi-urbain,
    +2 urbain dense). Valeur par défaut 0,0 => aucun effet.
    """
    # Zone d'implantation : décalage d'îlot de chaleur appliqué avant
    # toute la chaîne thermique (Chapitre 2.2.3.5)
    t_ext_max_effectif = t_ext_max + delta_ilot_chaleur

    # ISO 6946 (mur : multicouche si enduits renseignés ; toit : monocouche)
    U_mur = calc_U_multicouche(
        lambda_mur, epaisseur_mur, "mur",
        epaisseur_enduit_int=epaisseur_enduit_int,
        epaisseur_enduit_ext=epaisseur_enduit_ext,
        lambda_enduit_int=lambda_enduit,
        lambda_enduit_ext=lambda_enduit if lambda_enduit_ext is None else lambda_enduit_ext,
    )
    U_toit = calc_U(lambda_toit, epaisseur_toit, "toit")

    # ISO 13786 + Asan 1998
    delta_mur = calc_delta(lambda_mur, rho_mur, cp_mur)
    delta_toit = calc_delta(lambda_toit, rho_toit, cp_toit)
    xi_mur = calc_xi(epaisseur_mur, delta_mur)
    xi_toit = calc_xi(epaisseur_toit, delta_toit)
    f_mur = calc_f_amortissement(xi_mur)
    f_toit = calc_f_amortissement(xi_toit)
    phi_mur_h = calc_phi_semi_infini(xi_mur)
    phi_toit_h = calc_phi_semi_infini(xi_toit)

    # Conductances
    H_mur = calc_H_paroi(U_mur, surface_mur)
    H_toit = calc_H_paroi(U_toit, surface_toit)
    H_vent = calc_H_ventilation(nv, volume)
    H_vitree = calc_H_paroi(U_vitrage, surface_vitree)
    H_porte = calc_H_paroi(U_porte, surface_porte)
    H_baies = H_vitree + H_porte
    H_total = H_mur + H_toit + H_vent + H_baies
    f_env = calc_f_env(f_mur, H_mur, f_toit, H_toit, H_vent, H_baies)

    # Apports thermiques
    irradiance_moy = ghi_kwh_m2_j * 1000.0 / 24.0  # W/m² moyen sur 24h
    Q_solaire_toit = calc_Q_solaire_toit(alpha_toit, U_toit, irradiance_moy, surface_toit)
    # Orientation : ne module que l'apport solaire des fenêtres, pas des
    # portes (une porte opaque bois/métal ne « bénéficie » pas de
    # l'orientation puisqu'elle ne transmet pas de rayonnement direct).
    Q_solaire_vitree = calc_Q_solaire_baies(fs_vitrage, irradiance_moy, surface_vitree) * facteur_orientation
    Q_solaire_porte = calc_Q_solaire_baies(fs_porte, irradiance_moy, surface_porte)
    Q_solaire_baies = Q_solaire_vitree + Q_solaire_porte
    surface_plancher = surface_toit  # approximation standard SimTherm
    Q_internes = calc_Q_internes(apports_internes, surface_plancher)
    Q_moy = Q_solaire_toit + Q_solaire_baies + Q_internes

    # Températures (à partir de la Tmax décalée par l'îlot de chaleur)
    t_ext_moy_j = calc_T_ext_moy_j(t_ext_max_effectif, amplitude)
    t_int_moy = calc_T_int_moy(t_ext_moy_j, Q_moy, H_total)
    t_int_max = calc_T_int_max(t_int_moy, f_env, amplitude)
    t_int_min = calc_T_int_min(t_int_moy, f_env, amplitude)

    # Classification
    classe_ressentie = classifier_confort(t_int_moy, tn, usage)
    classe_pic = classifier_confort(t_int_max, tn, usage)

    return ResultatThermique(
        U_mur=U_mur, U_toit=U_toit,
        delta_mur=delta_mur, delta_toit=delta_toit,
        xi_mur=xi_mur, xi_toit=xi_toit,
        f_mur=f_mur, f_toit=f_toit,
        phi_mur_h=phi_mur_h, phi_toit_h=phi_toit_h,
        H_mur=H_mur, H_toit=H_toit, H_vent=H_vent, H_baies=H_baies,
        H_vitree=H_vitree, H_porte=H_porte, H_total=H_total,
        f_env=f_env,
        Q_solaire_toit=Q_solaire_toit, Q_solaire_baies=Q_solaire_baies,
        Q_internes=Q_internes, Q_moy=Q_moy,
        t_ext_moy_j=t_ext_moy_j, t_int_moy=t_int_moy,
        t_int_max=t_int_max, t_int_min=t_int_min,
        classe_ressentie=classe_ressentie, classe_pic=classe_pic,
    )
