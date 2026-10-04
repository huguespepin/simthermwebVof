"""
offline_rules.py — Système de recommandations expertes hors ligne.

Fonctionne sans Internet et sans clé API. Utilisé automatiquement en
cas d'indisponibilité de l'API OpenAI (pas de clé, panne réseau, quota
dépassé, timeout). Garantit que SimTherm produit TOUJOURS un diagnostic
utilisable, condition essentielle en zone à connectivité limitée
(Afrique de l'Ouest rurale).

Règles conçues à partir de l'expertise thermique tropicale : cf.
Chapitre 2.2.4 du mémoire (calibration confort adaptatif) et
Chapitre 2.1.4 (enjeux confort tropical humide).
"""

from dataclasses import dataclass
from typing import Callable

from core.thermal_calc import ResultatThermique


@dataclass
class Recommandation:
    priorite: int  # 1 = critique, 2 = importante, 3 = suggestion
    icone: str
    titre: str
    diagnostic: str
    reco: str

    @property
    def label_priorite(self) -> str:
        return {1: "🔴 Critique", 2: "🟠 Importante", 3: "🟢 Suggestion"}[self.priorite]


@dataclass
class Regle:
    condition: Callable[[ResultatThermique, dict], bool]
    priorite: int
    icone: str
    titre: str
    diagnostic: str
    reco: str


# ============================================================
# BASE DE RÈGLES — hiérarchisée par impact
# ============================================================
REGLES: list[Regle] = [

    # ------------------------------------------------------------
    # PRIORITÉ 1 — Alertes critiques (confort dégradé)
    # ------------------------------------------------------------
    Regle(
        condition=lambda r, ctx: r.classe_ressentie.lettre == "D",
        priorite=1,
        icone="🔴",
        titre="Confort ressenti sévèrement dégradé",
        diagnostic=(
            "La température intérieure moyenne s'écarte de plus de 5°C de la "
            "neutralité adaptative. Le bâtiment sera inconfortable la majeure "
            "partie de la journée sans dispositif actif."
        ),
        reco=(
            "Trois leviers combinés à mettre en œuvre : (1) toiture, remplacer "
            "la tôle nue par tôle+faux-plafond isolant ou dalle isolée ; "
            "(2) mur, augmenter l'inertie via matériau local massif (BTC, "
            "adobe, latérite compactée) épaisseur ≥ 25 cm ; (3) protection "
            "solaire, débord de toit ≥ 1 m et vitrages sélectifs."
        ),
    ),
    Regle(
        condition=lambda r, ctx: r.classe_pic.lettre == "D" and r.classe_ressentie.lettre != "D",
        priorite=1,
        icone="🔴",
        titre="Surchauffe diurne sévère (pic dimensionnant)",
        diagnostic=(
            "La température moyenne est acceptable mais le pic diurne dépasse "
            "largement la zone de confort. L'inertie de l'enveloppe est "
            "insuffisante pour amortir l'onde de chaleur diurne."
        ),
        reco=(
            "Renforcer l'inertie thermique du mur (matériau plus dense ou "
            "épaisseur accrue) pour améliorer le facteur d'amortissement f et "
            "le déphasage φ. Compléter par ventilation nocturne (Nv ≥ 1,5 vol/h "
            "en heures fraîches)."
        ),
    ),

    # ------------------------------------------------------------
    # PRIORITÉ 2 — Points d'amélioration importants
    # ------------------------------------------------------------
    Regle(
        condition=lambda r, ctx: r.U_toit > 3.0,
        priorite=2,
        icone="🟠",
        titre="Toiture très déperditive",
        diagnostic=(
            "Le coefficient U de la toiture est très élevé "
            "(configuration actuelle). En climat tropical, la toiture reçoit "
            "l'essentiel du rayonnement solaire, c'est le premier levier de "
            "conception."
        ),
        reco=(
            "Ajouter un faux-plafond isolant (laine minérale ≥ 10 cm ou "
            "isolant biosourcé) sous la tôle, ou envisager une toiture locale "
            "à forte inertie (chaume dense, dalle béton isolée). Objectif : "
            "U_toit < 1,5 W/m²K."
        ),
    ),
    Regle(
        condition=lambda r, ctx: r.U_mur > 2.5,
        priorite=2,
        icone="🟠",
        titre="Mur peu isolant",
        diagnostic=(
            "Le coefficient U du mur reste élevé, les échanges thermiques "
            "conductifs avec l'extérieur restent importants."
        ),
        reco=(
            "Privilégier un matériau local à forte inertie et conductivité "
            "modérée : BTC 5-8% ciment, adobe stabilisé, latérite compactée. "
            "Ces matériaux offrent un bon compromis λ modéré + ρ élevée "
            "favorable au climat tropical."
        ),
    ),
    # (Chapitre 2.2.5.4) — recommandation nommée : quand un candidat
    # concret est disponible dans le pays de l'utilisateur, le citer
    # explicitement plutôt que de rester générique.
    Regle(
        condition=lambda r, ctx: (
            r.U_mur > 2.5 and ctx.get("meilleur_mur_pays") is not None
        ),
        priorite=2,
        icone="🎯",
        titre="Alternative mur nommément identifiée",
        diagnostic=(
            "Le coefficient U du mur actuel dépasse 2,5 W/m²K. Un matériau "
            "mieux noté est disponible dans votre pays selon le classement "
            "TOP 5 de SimTherm."
        ),
        reco="",  # rempli dynamiquement ci-dessous
    ),
    Regle(
        condition=lambda r, ctx: (
            r.U_toit > 3.0 and ctx.get("meilleure_toit_pays") is not None
        ),
        priorite=2,
        icone="🎯",
        titre="Alternative toiture nommément identifiée",
        diagnostic=(
            "Le coefficient U de la toiture actuelle dépasse 3,0 W/m²K. "
            "Un matériau mieux noté est disponible dans votre pays."
        ),
        reco="",  # rempli dynamiquement ci-dessous
    ),
    Regle(
        condition=lambda r, ctx: r.phi_mur_h < 6.0,
        priorite=2,
        icone="🟠",
        titre="Déphasage du mur insuffisant",
        diagnostic=(
            f"Le déphasage φ du mur est faible : l'onde thermique diurne "
            f"traverse la paroi trop rapidement. Résultat : la chaleur du midi "
            f"arrive à l'intérieur en pic d'après-midi, au pire moment."
        ),
        reco=(
            "Augmenter l'épaisseur du mur (viser ≥ 25 cm) OU passer à un "
            "matériau plus dense (ρ > 1800 kg/m³) pour porter φ à 8-12 heures. "
            "L'objectif : décaler l'arrivée du pic thermique en soirée, quand "
            "la ventilation nocturne peut l'évacuer."
        ),
    ),
    Regle(
        condition=lambda r, ctx: ctx.get("alpha_toit", 0) > 0.7,
        priorite=2,
        icone="🟠",
        titre="Toiture sombre : surchauffe évitable",
        diagnostic=(
            f"L'absorptivité solaire actuelle de la toiture est élevée (surface sombre "
            f"absorbante). En climat tropical, une toiture noire peut atteindre "
            f"70°C au soleil, doublant les apports solaires par conduction."
        ),
        reco=(
            "Peindre la toiture en blanc ou couleur claire (α ≤ 0,3), ou "
            "installer une surface réfléchissante. Investissement minimal, "
            "impact majeur : la littérature rapporte jusqu'à 4-6°C de gain "
            "sur T°int en climat sahélien."
        ),
    ),
    Regle(
        condition=lambda r, ctx: ctx.get("fs_baies", 0) > 0.7,
        priorite=2,
        icone="🟠",
        titre="Vitrages sans protection solaire",
        diagnostic=(
            "Le facteur solaire des baies est élevé, les vitrages laissent "
            "passer l'essentiel du rayonnement direct dans le bâtiment."
        ),
        reco=(
            "Installer une protection solaire extérieure (brise-soleil, "
            "casquette, débord de toit) devant les baies exposées Est-Sud-Ouest. "
            "Alternative : films solaires sélectifs (FS ≈ 0,3-0,4). L'ombrage "
            "extérieur est toujours plus efficace qu'un traitement de vitrage."
        ),
    ),

    # ------------------------------------------------------------
    # PRIORITÉ 3 — Suggestions d'optimisation
    # ------------------------------------------------------------
    Regle(
        condition=lambda r, ctx: 6.0 <= r.phi_mur_h < 10.0 and r.U_mur <= 2.5,
        priorite=3,
        icone="🟢",
        titre="Bonne inertie : optimisation possible",
        diagnostic=(
            "Le mur présente un déphasage correct (6-10 h) et une isolation "
            "correcte. Configuration déjà favorable."
        ),
        reco=(
            "Pour aller vers l'excellence (φ ≥ 12 h) : envisager une paroi "
            "composite mur+isolation extérieure, ou augmenter légèrement "
            "l'épaisseur du mur porteur (+5 cm)."
        ),
    ),
    Regle(
        condition=lambda r, ctx: r.f_env < 0.3 and r.classe_ressentie.lettre in ("A", "B"),
        priorite=3,
        icone="🟢",
        titre="Enveloppe très amortissante",
        diagnostic=(
            f"Le facteur d'amortissement global f_env est excellent : "
            f"les variations thermiques extérieures sont fortement atténuées."
        ),
        reco=(
            "Configuration remarquable. Pour un usage optimal, coupler à une "
            "stratégie de ventilation nocturne (ouverture contrôlée des baies "
            "en heures fraîches) pour évacuer la chaleur stockée dans la masse."
        ),
    ),
    Regle(
        condition=lambda r, ctx: (
            r.classe_ressentie.lettre in ("A", "B")
            and r.classe_pic.lettre in ("A", "B")
        ),
        priorite=3,
        icone="🟢",
        titre="Configuration globalement favorable",
        diagnostic=(
            "Les deux classes de confort (ressenti et pic) sont dans la zone "
            "acceptable. Le bâtiment devrait offrir un confort satisfaisant "
            "sans recours à la climatisation."
        ),
        reco=(
            "Maintenir cette configuration. Attention à ne pas dégrader l'un "
            "des paramètres clés lors de modifications ultérieures : matériau "
            "du mur, isolation de la toiture, absorptivité solaire de la toiture, ventilation nocturne."
        ),
    ),
]


# ============================================================
# HELPER — recommandation nommément identifiée (Chapitre 2.2.5.4)
# ============================================================
def _reco_nommee(m: dict, categorie: str) -> str:
    """
    Formate la recommandation dynamique quand un matériau candidat concret
    (extrait du TOP 5 du pays) est passé dans le contexte.

    m attendu : {"nom": str, "lambda": float, "cout": float|None,
                 "monnaie": str|None}
    """
    if not m or not m.get("nom"):
        # Retour neutre au cas où le contexte serait mal formé
        return ("Consultez l'onglet « Simulation matériaux » pour identifier "
                "le matériau le mieux noté disponible dans votre pays.")
    nom = m["nom"]
    lam = m.get("lambda")
    cout = m.get("cout")
    monnaie = m.get("monnaie") or ""
    parts = [f"Envisager **{nom}**"]
    if isinstance(lam, (int, float)):
        parts.append(f" (λ = {lam:.2f} W/m·K")
        if isinstance(cout, (int, float)) and cout > 0:
            parts.append(f", coût indicatif {cout:,.0f} {monnaie}/m²")
        parts.append(")")
    parts.append(
        f", disponible dans votre pays et classé parmi les meilleurs "
        f"selon le score composite SimTherm. Voir l'onglet "
        f"« Simulation matériaux » pour le classement complet."
    )
    return "".join(parts)


# ============================================================
# API PUBLIQUE
# ============================================================
def generer_recommandations_offline(
    resultat: ResultatThermique,
    contexte: dict,
) -> list[Recommandation]:
    """
    Génère la liste des recommandations activées par les règles.

    Args:
        resultat: ResultatThermique produit par le moteur de calcul
        contexte: dict avec les entrées utilisateur pertinentes
                  (alpha_toit, fs_baies, ville, pays, materiau_mur, etc.)

    Returns:
        Liste de Recommandation triée par priorité (1 → 3)
    """
    recos = []
    for regle in REGLES:
        try:
            if not regle.condition(resultat, contexte):
                continue

            # Recommandations à contenu dynamique (Chapitre 2.2.5.4) —
            # citer nommément le meilleur candidat du pays quand disponible.
            reco_texte = regle.reco
            if regle.titre == "Alternative mur nommément identifiée":
                m = contexte.get("meilleur_mur_pays") or {}
                reco_texte = _reco_nommee(m, "mur")
            elif regle.titre == "Alternative toiture nommément identifiée":
                m = contexte.get("meilleure_toit_pays") or {}
                reco_texte = _reco_nommee(m, "toiture")

            recos.append(Recommandation(
                priorite=regle.priorite,
                icone=regle.icone,
                titre=regle.titre,
                diagnostic=regle.diagnostic,
                reco=reco_texte,
            ))
        except Exception:
            # Une règle défectueuse ne doit jamais planter tout le système
            continue

    # Trier par priorité (1 = critique en premier)
    recos.sort(key=lambda r: r.priorite)

    # Si aucune règle ne s'est déclenchée, message neutre
    if not recos:
        recos.append(Recommandation(
            priorite=3,
            icone="ℹ️",
            titre="Aucune alerte spécifique détectée",
            diagnostic="La configuration actuelle ne déclenche aucune règle d'alerte automatique.",
            reco="Explorez les autres onglets (Comparaison, Simulation matériaux) pour évaluer des alternatives.",
        ))

    return recos
