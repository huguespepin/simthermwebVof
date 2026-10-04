"""
constants.py — Constantes physiques et seuils normatifs de SimTherm.

Toutes les valeurs ici sont directement issues des normes citées.
Aucune valeur "magique" ne doit apparaître ailleurs dans le code sans
provenir de ce fichier — c'est la garantie de traçabilité scientifique.
"""

# ============================================================
# RÉSISTANCES THERMIQUES SUPERFICIELLES — ISO 6946:2017, Tableau 1
# ============================================================
RSI_MUR = 0.13      # m²K/W — paroi verticale, flux horizontal, intérieur
RSE_MUR = 0.04      # m²K/W — paroi verticale exposée, extérieur
RSI_TOIT = 0.10     # m²K/W — paroi horizontale, flux ascendant, intérieur
RSE_TOIT = 0.04     # m²K/W — identique mur (paroi exposée)

# ============================================================
# PÉRIODE DE RÉFÉRENCE — ISO 13786:2017, éq. 11
# ============================================================
PERIODE_JOUR_S = 86400  # secondes (cycle diurne de 24h)

# ============================================================
# VENTILATION — CIBSE Guide A, ch. 5
# ============================================================
# H_vent = COEFF_VENT * Nv * V   (Nv en vol/h, V en m³)
# COEFF_VENT = rho_air * Cp_air / 3600 = 1.2 * 1005 / 3600 ≈ 0.335
COEFF_VENT = 0.34  # W/(m³·K·vol/h) — valeur usuelle arrondie CIBSE

# ============================================================
# SEUILS DE CLASSIFICATION DU CONFORT ADAPTATIF
# Sources : ASHRAE 55-2020, EN 16798-1:2019, Munonye & Ji (2021),
# Nematchoua et al. (2014), Kiki et al. (2020)
# Cf. Chapitre 2.2.4 du mémoire pour la justification complète.
# ============================================================
SEUILS_CONFORT_STANDARD = {
    "A": 2.0,
    "B": 3.5,
    "C": 5.0,
    # au-delà de C -> D
}

SEUILS_CONFORT_SENSIBLE = {
    "A": 1.5,
    "B": 2.5,
    "C": 4.0,
    # au-delà de C -> D
}

DESCRIPTIONS_CLASSES = {
    "A": "Confort optimal",
    "B": "Confort acceptable",
    "C": "Inconfort modéré",
    "D": "Inconfort sévère",
}

# Types de bâtiments à seuils resserrés (occupants vulnérables)
# Cf. EN 16798-1, catégorie I
USAGES_SENSIBLES = {
    "Salle de classe / École",
    "Amphithéâtre / Salle conférence",
    "Bibliothèque / Salle d'étude",
    "Centre de santé / Dispensaire",
    "Hôpital / Clinique",
    "Administration / Bureau public",
    "Mairie / Centre administratif rural",
}

# ============================================================
# CATÉGORIES DE MATÉRIAUX — BD_MATERIAUX
# ============================================================
CATEGORIES_MUR = {"Mur porteur", "Mur conventionnel", "Isolation biosourcée"}
CATEGORIES_TOITURE = {"Toiture locale", "Toiture conventionnelle"}

# ============================================================
# SCORE COMPOSITE SIMTHERM
# Score = 100 / (1+U) * min(1, phi/12)
# Pondère isolation (U bas = mieux) et inertie (phi élevé = mieux,
# plafonné à 12h = demi-période, au-delà le gain marginal est nul)
# ============================================================
SCORE_PHI_PLAFOND_H = 12.0

# ============================================================
# OUVERTURES DE L'ENVELOPPE — deux catégories physiquement distinctes
#
# FENÊTRES (vitrées) : transmettent le rayonnement solaire direct
# (facteur solaire FS pertinent) ET conduisent la chaleur (U_vitrage).
#
# PORTES (opaques, bois/métal/PVC pleines) : n'ont AUCUNE transmission
# solaire directe significative (FS ≈ 0) mais conduisent la chaleur
# (U_porte). Les confondre avec les fenêtres sous un même facteur
# solaire unique surestime les apports solaires réels.
#
# Valeurs U de référence : littérature technique bâtiment tropical /
# valeurs fabricants usuelles.
# ============================================================
U_VITRAGE_TYPIQUE = {
    "Simple vitrage (cadre bois/PVC)": 5.7,
    "Simple vitrage (cadre aluminium)": 6.5,
    "Double vitrage standard": 2.8,
    "Double vitrage basse émissivité": 1.4,
}

U_PORTE_TYPIQUE = {
    "Porte pleine bois": 2.0,
    "Porte métallique (tôle)": 5.8,
    "Porte PVC isolée": 1.8,
    "Porte vitrée (baie coulissante)": 3.5,  # cas mixte : conduction proche vitrage
}

# ============================================================
# ENDUITS ET REVÊTEMENTS DE FINITION — valeurs λ typiques
# Ajoutés en série au mur porteur (ISO 6946 clause 6.2, parois
# multicouches). Épaisseurs usuelles : 1 à 2,5 cm par face.
# Carreaux : λ = 1,30 W/m·K (céramique/porcelaine, ISO 10456, niveau N3) ;
# l'épaisseur saisie doit inclure le carreau ET sa colle ou son mortier
# de pose (ordre de grandeur 1 à 1,5 cm).
# ============================================================
LAMBDA_ENDUIT_TYPIQUE = {
    "Enduit ciment/mortier bâtard": 1.15,
    "Enduit chaux": 0.80,
    "Enduit terre/argile": 0.80,
    "Enduit plâtre": 0.57,
    "Revêtement en carreaux (céramique)": 1.30,
    "Aucun enduit (mur brut)": None,  # cas par défaut, e=0
}

# Facteur solaire par défaut selon le type d'ouverture — une porte
# pleine (bois/métal) est opaque : FS ≈ 0 (pas de transmission
# directe). Seule la porte vitrée transmet un peu de rayonnement.
FS_PAR_DEFAUT_PORTE = {
    "Porte pleine bois": 0.0,
    "Porte métallique (tôle)": 0.0,
    "Porte PVC isolée": 0.0,
    "Porte vitrée (baie coulissante)": 0.55,
}

# ============================================================
# ORIENTATION DES FAÇADES — facteur correctif d'apport solaire
# (Chapitre 2.2.3.4 du mémoire)
#
# Appliqué UNIQUEMENT à l'apport solaire des fenêtres vitrées.
# Les parois opaques (murs) et les portes ne sont pas modulées.
# Valeurs indicatives issues du catalogue ONU-Habitat 2020 et de
# la littérature de conception bioclimatique tropicale, qualitatives
# plutôt que rigoureusement quantifiées — limite documentée en 2.2.7.
#
#   Nord  0.65 : façade la moins exposée en hémisphère tropical
#   Sud   0.85 : soleil zénithal à midi, débord de toit efficace
#   Est   1.10 : soleil du matin (angle bas, difficile à protéger)
#   Ouest 1.15 : soleil du soir + accumulation, cas dimensionnant
#   Moyenne 1.00 : cas d'orientation multiple ou non renseignée
# ============================================================
FACTEURS_ORIENTATION = {
    "Nord": 0.65,
    "Sud": 0.85,
    "Est": 1.10,
    "Ouest": 1.15,
    "Toutes façades (moyenne)": 1.00,
}

# ============================================================
# ZONE D'IMPLANTATION — décalage d'îlot de chaleur urbain
# (Chapitre 2.2.3.5 du mémoire)
#
# Appliqué directement à la température extérieure de pointe avant
# le calcul de l'ensemble de la chaîne thermique. Valeurs délibérément
# conservatrices au regard des amplitudes rapportées par la littérature
# de télédétection (Wemegah 2020 pour Accra, Offerle 2005 pour
# Ouagadougou, qui mesurent la température de surface, structurellement
# supérieure à la température d'air). Limite documentée en 2.2.7.
# ============================================================
DECALAGES_ILOT_CHALEUR = {
    "Rural / périurbain peu dense": 0.0,
    "Semi-urbain": 1.0,
    "Urbain dense": 2.0,
}

# ============================================================
# HIÉRARCHIE DE CONFIANCE DES DONNÉES À SIX NIVEAUX
# Cf. Chapitre 2.2.1.2 du mémoire, Tableau IX. S'applique à la fois
# aux matériaux (BD_MATERIAUX, colonne "Niveau N1/N2/N3") et aux
# températures de neutralité par pays (Tableau X).
# ============================================================
LABEL_FIABILITE = {
    "N1": "N1 : donnée expérimentale, DOI vérifié, pays cible",
    "N2": "N2 : donnée régionale africaine documentée ou analogie directe",
    "N3": "N3 : norme internationale (ISO, ASHRAE) sans équivalent africain",
    "H+": "H+ : hypothèse forte, analogie directe (même sol, même équipe, même site)",
    "H-": "H- : hypothèse faible, ordre de grandeur générique de catégorie",
    "N/D": "N/D : non documenté, lacune signalée explicitement",
}

COULEUR_FIABILITE = {
    "N1": "#3F6B4A",   # vert
    "N2": "#B5622E",   # orange
    "N3": "#2E75B6",   # bleu
    "H+": "#6B4A8A",   # violet
    "H-": "#C00000",   # rouge
    "N/D": "#8A8578",  # gris
}

# Fiabilité et méthode de détermination de la température de
# neutralité par pays (Tableau X du mémoire). BD_CLIMAT ne porte pas
# cette information par ville : elle est définie une fois par pays,
# conformément à l'échelle du Tableau IX. BD_PAYS conserve encore
# l'ancienne échelle à étoiles utilisée avant l'adoption de cette
# hiérarchie à six niveaux, elle n'est pas reprise ici.
FIABILITE_TN_PAR_PAYS = {
    "Bénin": "N1",
    "Nigeria": "N1",
    "Cameroun": "N1",
    "Ghana": "N2",
    "Burkina Faso": "N3",
    "Sénégal": "N3",
    "Kenya": "N3",
    "Mali": "N3",
    "Côte d'Ivoire": "H+",
    "Niger": "H+",
    "Togo": "H+",
}


# ============================================================
# ABSORPTIVITÉ SOLAIRE DE LA TOITURE (α) — repères indicatifs
#
# α est la fraction du rayonnement solaire ABSORBÉE par la surface
# extérieure de la toiture (α = 1 - albédo). Plus α est grand, plus la
# toiture s'échauffe et transmet de chaleur vers l'intérieur :
#   Q_toit = α × Rse × U_toit × I_moy × A_toit  (sol-air simplifiée)
# Valeurs indicatives (ordres de grandeur courants), à ajuster selon
# l'état réel de la surface (vieillissement, salissure, peinture).
# ============================================================
ALPHA_TOIT_TYPIQUE = {
    "Très sombre (noir, bitume)": 0.90,
    "Tôle sombre ou rouillée": 0.85,
    "Tuile terre cuite ou béton gris": 0.65,
    "Couleur claire": 0.40,
    "Blanc ou peinture réfléchissante": 0.30,
}

# ============================================================
# FACTEUR SOLAIRE DES FENÊTRES (FS) — repères indicatifs
#
# FS est la fraction du rayonnement solaire incident qui traverse la
# fenêtre vers l'intérieur : Q_baies = FS × I_moy × A_vitrée × F_orient.
# Les valeurs ci-dessous sont des ordres de grandeur courants ; la
# valeur exacte figure sur la fiche technique du fabricant.
# ============================================================
FS_VITRAGE_TYPIQUE = {
    "Simple vitrage clair": 0.75,
    "Double vitrage clair": 0.70,
    "Vitrage teinté ou réfléchissant": 0.45,
    "Film solaire sélectif": 0.35,
    "Fenêtre protégée par brise-soleil extérieur": 0.30,
}


# ============================================================
# SOURCES ET NIVEAU DE FIABILITÉ DES λ D'ENDUITS (hiérarchie N1/N2/N3)
# Vérification documentaire du 03/10/2026. Aucune mesure publiée avec DOI
# au Bénin (N1) n'a été trouvée. Les masses volumiques associées aux
# valeurs normatives sont à confirmer sur un exemplaire officiel de
# l'ISO 10456 / EN 12524 (texte intégral non consulté).
# ============================================================
ENDUIT_SOURCES = {
    "Enduit ciment/mortier bâtard": (
        "N2",
        "1,15 : valeur de Claessens et al. citée par Bamogo et al. (2023, Engineering 15:396, "
        "DOI 10.4236/eng.2023.156031), mesures 0,70 à 1,15 sur chantiers de Ouagadougou. "
        "L'ISO 10456 donne 1,00 (ρ 1800) : valeur alternative."),
    "Enduit chaux": (
        "N3", "0,80 : ISO 10456 / EN 12524, chaux et sable, ρ 1600 kg/m³. "
              "0,70 seulement pour un enduit intérieur léger."),
    "Enduit terre/argile": (
        "N2", "0,80 : cohérent avec Bamogo et al. (2022, Materials 15:4014, "
              "DOI 10.3390/ma15114014, Burkina Faso) et Guillaud et Houben."),
    "Enduit plâtre": (
        "N3", "0,57 : plâtre d'enduit courant 1000 à 1300 kg/m³ (ISO 10456 / EN 12524, Th-U). "
              "0,40 si plâtre léger (ρ ≤ 1000 kg/m³)."),
    "Revêtement en carreaux (céramique)": (
        "N3", "1,30 : ISO 10456 / EN 12524, céramique et porcelaine, ρ 2300 kg/m³. "
              "Mesures publiées de 0,6 à 1,7 selon la porosité."),
}
