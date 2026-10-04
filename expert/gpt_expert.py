"""
gpt_expert.py — Intégration OpenAI GPT-4o mini pour recommandations expertes.

Architecture :
- Récupère la clé API via st.secrets (Streamlit Cloud) ou variable
  d'environnement (dev local)
- Cache en mémoire (dictionnaire) indexé par un hash SHA-256 de la
  configuration : une même config n'est calculée qu'une fois par session
  de serveur (économie de crédits ; pas d'éviction ni de persistance)
- Fallback automatique sur offline_rules si :
  * Pas de clé API
  * Panne réseau / timeout
  * Quota OpenAI dépassé
  * Toute autre erreur API
- Prompt système versionné dans expert/prompts/expert_prompt_fr.txt

Sécurité :
- La clé API n'est JAMAIS journalisée, affichée ou exposée dans les
  messages d'erreur
- Timeout court (15 s) pour éviter les blocages
"""

import hashlib
import json
import os
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from core.thermal_calc import ResultatThermique
from expert.offline_rules import generer_recommandations_offline, Recommandation


# ============================================================
# CONFIGURATION
# ============================================================
MODEL_NAME = "gpt-4o-mini"
API_TIMEOUT_S = 60  # réponse détaillée : plus longue à générer
MAX_TOKENS_OUT = 4500  # rapport détaillé (environ 2 000 mots) sans troncature
TEMPERATURE = 0.4  # relativement factuel, un peu de variation stylistique

PROMPT_PATH = Path(__file__).parent / "prompts" / "expert_prompt_fr.txt"


# ============================================================
# GESTION SÉCURISÉE DE LA CLÉ API
# ============================================================
def _get_api_key() -> Optional[str]:
    """
    Récupère la clé API depuis :
    1. st.secrets (Streamlit Cloud, chiffré) — priorité
    2. Variable d'environnement OPENAI_API_KEY (dev local)
    3. Retourne None si aucune source disponible

    La clé n'est jamais journalisée ni affichée.
    """
    # Priorité 1 : Streamlit Secrets
    try:
        import streamlit as st
        if "OPENAI_API_KEY" in st.secrets:
            key = st.secrets["OPENAI_API_KEY"]
            if key and str(key).startswith("sk-"):
                return str(key)
    except Exception:
        pass

    # Priorité 2 : variable d'environnement
    key = os.environ.get("OPENAI_API_KEY")
    if key and key.startswith("sk-"):
        return key

    return None


def api_disponible() -> bool:
    """Retourne True si une clé API valide est configurée."""
    return _get_api_key() is not None


# ============================================================
# CONSTRUCTION DU PROMPT UTILISATEUR
# ============================================================
def _construire_message_utilisateur(
    resultat: ResultatThermique,
    contexte: dict,
) -> str:
    """
    Formate la configuration + résultats en un message textuel clair
    pour le modèle.
    """
    lignes = ["Voici les résultats de simulation thermique à analyser :\n"]

    # Contexte
    lignes.append("### Localisation et bâtiment")
    lignes.append(f"- Pays : {contexte.get('pays', '—')}")
    lignes.append(f"- Ville : {contexte.get('ville', '—')}")
    lignes.append(f"- Type de bâtiment : {contexte.get('usage', '—')}")
    lignes.append(f"- Climat : Tmax={contexte.get('tmax')}°C · Tmoy={contexte.get('tmoy')}°C · "
                    f"Tn={contexte.get('tn')}°C · Amplitude diurne={contexte.get('amplitude')}°C · "
                    f"Humidité relative={contexte.get('humidite')} % · Tmin={contexte.get('tmin')}°C")

    # Configuration constructive
    lignes.append("\n### Configuration constructive")
    lignes.append(f"- Matériau MUR : {contexte.get('materiau_mur', '—')} "
                    f"(épaisseur {contexte.get('epaisseur_mur', '—')} m)")
    lignes.append(f"- Matériau TOITURE : {contexte.get('materiau_toit', '—')} "
                    f"(épaisseur {contexte.get('epaisseur_toit', '—')} m)")
    lignes.append(f"- Absorptivité solaire de la toiture α (1 = surface noire absorbante, 0 = blanche réfléchissante) = {contexte.get('alpha_toit')}")
    lignes.append(f"- Facteur solaire vitrages FS = {contexte.get('fs_baies')}")
    if contexte.get("orientation"):
        lignes.append(f"- Orientation dominante des fenêtres : {contexte['orientation']} "
                        f"(facteur d'apport {contexte.get('facteur_orientation', 1.0):.2f})")
    if contexte.get("zone_implantation"):
        lignes.append(f"- Zone d'implantation : {contexte['zone_implantation']} "
                        f"(décalage îlot de chaleur +{contexte.get('delta_ilot_chaleur', 0.0):.1f}°C)")

    # (Chapitre 2.2.5.4) — instruction explicite au modèle : citer
    # prioritairement le matériau réellement disponible dans le pays
    # plutôt que d'inventer une catégorie générique.
    meilleur_mur = contexte.get("meilleur_mur_pays")
    meilleure_toit = contexte.get("meilleure_toit_pays")
    if meilleur_mur or meilleure_toit:
        lignes.append("\n### Candidats disponibles dans ce pays (à citer nommément si pertinent)")
        if meilleur_mur:
            lignes.append(f"- Meilleur MUR selon score composite SimTherm : "
                            f"**{meilleur_mur['nom']}** (λ = {meilleur_mur['lambda']:.2f} W/m·K)")
        if meilleure_toit:
            lignes.append(f"- Meilleure TOITURE selon score composite SimTherm : "
                            f"**{meilleure_toit['nom']}** (λ = {meilleure_toit['lambda']:.2f} W/m·K)")
        lignes.append("Si tu recommandes un changement de matériau, cite prioritairement "
                        "l'un de ces candidats plutôt qu'une catégorie générique — c'est "
                        "un matériau réellement disponible localement.")

    # Propriétés des matériaux actuels
    props = contexte.get("props_materiaux") or {}
    if props:
        lignes.append("\n### Propriétés des matériaux actuels (base SimTherm)")
        for cle, etiq in (("mur", "Mur"), ("toit", "Toiture")):
            p = props.get(cle)
            if p:
                cout = (f", coût local {p['cout']:.0f} {p.get('monnaie') or ''}/m²" if p.get("cout") else "")
                lignes.append(f"- {etiq} : λ = {p['lambda']} W/m·K, ρ = {p['rho']} kg/m³, "
                                f"Cp = {p['cp']} J/kg·K{cout}, niveau de fiabilité de la donnée : "
                                f"{p.get('niveau_confiance') or 'non renseigné'}")

    # Classements calculés par SimTherm (cf. expert/scenarios.py)
    def _tableau(titre: str, classement: list, note: str):
        lignes.append(f"\n### {titre}")
        lignes.append(note)
        lignes.append("| Matériau | Épaisseur (m) | U (W/m²K) | φ (h) | Score | T°max intérieure | Classe pic | Coût local/m² | Disponibilité | Fiabilité |")
        lignes.append("|---|---|---|---|---|---|---|---|---|---|")
        for c in classement:
            cout = f"{c['cout']:.0f} {c.get('monnaie') or ''}" if c.get("cout") else "n.d."
            lignes.append(f"| {c['nom']} | {c['epaisseur_m']:.3f} | {c['U']:.2f} | {c['phi_h']:.1f} | "
                            f"{c['score']:.1f} | {c['t_int_max']:.1f} | {c['classe_pic']} | {cout} | "
                            f"{c.get('disponibilite') or 'n.d.'} | {c.get('niveau_confiance') or 'n.d.'} |")
    if contexte.get("classement_murs"):
        _tableau("Meilleurs murs disponibles dans le pays (classés par score SimTherm)",
                 contexte["classement_murs"],
                 "Chaque mur est simulé à la même épaisseur que le mur actuel, le reste de la "
                 "configuration étant inchangé. La colonne T°max intérieure est le résultat du moteur.")
    if contexte.get("classement_toits"):
        _tableau("Meilleures toitures disponibles dans le pays (classées par score SimTherm)",
                 contexte["classement_toits"],
                 "Chaque toiture est simulée à son épaisseur de référence (celle de la source), "
                 "le reste de la configuration étant inchangé.")

    scen = contexte.get("scenarios") or []
    if scen:
        lignes.append("\n### Scénarios simulés par SimTherm (un levier modifié à la fois, puis cumul)")
        lignes.append(f"Référence (configuration actuelle) : T°max intérieure = {resultat.t_int_max:.1f} °C, "
                        f"T°moyenne = {resultat.t_int_moy:.1f} °C, classe ressentie {resultat.classe_ressentie.lettre}, "
                        f"classe pic {resultat.classe_pic.lettre}.")
        for s in scen:
            note = f" Remarque : {s['note']}." if s.get("note") else ""
            lignes.append(f"- {s['libelle']} : T°max = {s['t_int_max']:.1f} °C ({s['delta_max']:+.1f} °C), "
                            f"T°moyenne = {s['t_int_moy']:.1f} °C, classe ressentie {s['classe_ressentie']}, "
                            f"classe pic {s['classe_pic']}.{note}")

    # Géométrie, ouvertures, ventilation, enduits (analyse détaillée)
    lignes.append("\n### Géométrie et usage")
    lignes.append(f"- Surface de mur opaque = {contexte.get('surface_mur', 0):.1f} m² · "
                    f"surface de toiture = {contexte.get('surface_toit', 0):.1f} m² · "
                    f"volume = {contexte.get('volume', 0):.0f} m³ · niveaux = {contexte.get('niveaux', 1)}")
    lignes.append(f"- Fenêtres : {contexte.get('surface_vitree', 0):.1f} m² (U = {contexte.get('u_vitrage')} W/m²K) · "
                    f"portes : {contexte.get('surface_porte', 0):.1f} m²")
    lignes.append(f"- Apports internes = {contexte.get('apports_internes')} W/m² · "
                    f"renouvellement d'air = {contexte.get('nv')} vol/h")
    lignes.append(f"- Irradiation solaire globale moyenne = {contexte.get('ghi')} kWh/m²/j")
    if contexte.get("enduit_int") or contexte.get("enduit_ext"):
        lignes.append(f"- Enduits : intérieur = {contexte.get('enduit_int') or 'aucun'} "
                        f"({contexte.get('epaisseur_enduit_int', 0)} m) ; "
                        f"extérieur = {contexte.get('enduit_ext') or 'aucun'} "
                        f"({contexte.get('epaisseur_enduit_ext', 0)} m)")
    else:
        lignes.append("- Enduits : aucun")

    # Résultats thermiques
    lignes.append("\n### Résultats du moteur SimTherm")
    lignes.append(f"- U mur = {resultat.U_mur:.2f} W/m²K · U toiture = {resultat.U_toit:.2f} W/m²K")
    lignes.append(f"- Déphasage φ mur = {resultat.phi_mur_h:.1f} h · φ toiture = {resultat.phi_toit_h:.1f} h")
    lignes.append(f"- Facteur d'amortissement enveloppe f_env = {resultat.f_env:.2f}")
    lignes.append(f"- Profondeur de pénétration δ mur = {resultat.delta_mur:.3f} m · "
                    f"facteur d'amortissement f mur = {resultat.f_mur:.2f} · f toiture = {resultat.f_toit:.2f}")
    q_tot = resultat.Q_moy if resultat.Q_moy else 1.0
    lignes.append(f"- Q_moy (apports thermiques) = {resultat.Q_moy:.0f} W, répartis ainsi : "
                    f"toiture (sol-air) {resultat.Q_solaire_toit:.0f} W ({100*resultat.Q_solaire_toit/q_tot:.0f} %), "
                    f"baies vitrées {resultat.Q_solaire_baies:.0f} W ({100*resultat.Q_solaire_baies/q_tot:.0f} %), "
                    f"apports internes {resultat.Q_internes:.0f} W ({100*resultat.Q_internes/q_tot:.0f} %)")
    h_tot = resultat.H_total if resultat.H_total else 1.0
    lignes.append(f"- H_total (conductances) = {resultat.H_total:.0f} W/K, répartis ainsi : "
                    f"mur {resultat.H_mur:.0f} ({100*resultat.H_mur/h_tot:.0f} %), "
                    f"toiture {resultat.H_toit:.0f} ({100*resultat.H_toit/h_tot:.0f} %), "
                    f"ventilation {resultat.H_vent:.0f} ({100*resultat.H_vent/h_tot:.0f} %), "
                    f"fenêtres {resultat.H_vitree:.0f} ({100*resultat.H_vitree/h_tot:.0f} %), "
                    f"portes {resultat.H_porte:.0f} ({100*resultat.H_porte/h_tot:.0f} %)")
    lignes.append(f"- T°extérieure moyenne du jour = {resultat.t_ext_moy_j:.1f} °C")
    lignes.append(f"- T°intérieure min (nuit) = {resultat.t_int_min:.1f} °C")
    lignes.append(f"- T°intérieure moyenne = {resultat.t_int_moy:.1f} °C "
                    f"(ΔT vs Tn = {resultat.classe_ressentie.delta_t:+.1f} °C)")
    lignes.append(f"- T°intérieure max (pic diurne) = {resultat.t_int_max:.1f} °C "
                    f"(ΔT vs Tn = {resultat.classe_pic.delta_t:+.1f} °C)")
    lignes.append(f"- **Classe confort ressenti : {resultat.classe_ressentie.lettre} "
                    f"({resultat.classe_ressentie.description})**")
    lignes.append(f"- **Classe pic dimensionnant : {resultat.classe_pic.lettre} "
                    f"({resultat.classe_pic.description})**")

    lignes.append("\nProduis une analyse détaillée et exhaustive selon la structure demandée, en t'appuyant sur les parts relatives des apports et des conductances ci-dessus pour hiérarchiser les leviers.")

    return "\n".join(lignes)


# ============================================================
# CACHE INTELLIGENT (par hash de configuration)
# ============================================================
_cache_reponses: dict[str, str] = {}


def _cle_cache(resultat: ResultatThermique, contexte: dict) -> str:
    """Génère une clé de cache stable à partir de la config."""
    payload = {
        "res": {
            "U_mur": round(resultat.U_mur, 2),
            "U_toit": round(resultat.U_toit, 2),
            "phi_mur_h": round(resultat.phi_mur_h, 1),
            "f_env": round(resultat.f_env, 2),
            "t_int_moy": round(resultat.t_int_moy, 1),
            "t_int_max": round(resultat.t_int_max, 1),
            "classe_r": resultat.classe_ressentie.lettre,
            "classe_p": resultat.classe_pic.lettre,
        },
        "ctx": {k: contexte.get(k) for k in
                ["pays", "ville", "usage", "materiau_mur", "materiau_toit",
                 "epaisseur_mur", "epaisseur_toit", "alpha_toit", "fs_baies",
                 "enduit_int", "enduit_ext", "surface_vitree", "orientation", "zone_implantation"]},
        "scen": [(s["libelle"], round(s["t_int_max"], 1)) for s in (contexte.get("scenarios") or [])],
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


# ============================================================
# APPEL API GPT-4o MINI
# ============================================================
def _appeler_gpt(prompt_systeme: str, message_user: str, api_key: str) -> Optional[str]:
    """
    Appelle l'API OpenAI. Retourne le texte de la réponse, ou None
    en cas d'erreur (fallback offline sera déclenché par l'appelant).

    Ne journalise JAMAIS la clé API ni le contenu des erreurs API
    (qui peut contenir la clé sur certaines librairies).
    """
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, timeout=API_TIMEOUT_S)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS_OUT,
            messages=[
                {"role": "system", "content": prompt_systeme},
                {"role": "user", "content": message_user},
            ],
        )
        return response.choices[0].message.content
    except Exception:
        # Absorber toutes les erreurs API (réseau, quota, clé invalide,
        # timeout, etc.) — le fallback offline prendra le relais.
        return None


# ============================================================
# API PUBLIQUE
# ============================================================
@dataclass
class ResultatExpert:
    mode: str  # "online" ou "offline"
    texte_markdown: Optional[str] = None  # rempli si online
    recommandations: Optional[list[Recommandation]] = None  # rempli si offline
    message_info: str = ""


def obtenir_recommandations(
    resultat: ResultatThermique,
    contexte: dict,
    forcer_offline: bool = False,
) -> ResultatExpert:
    """
    Point d'entrée principal du système expert.

    Args:
        resultat: sortie du moteur de calcul
        contexte: dict des entrées utilisateur (pays, ville, matériaux, etc.)
        forcer_offline: True pour bypasser l'API même si dispo

    Returns:
        ResultatExpert avec :
        - mode = "online" et texte_markdown rempli, si API OK
        - mode = "offline" et recommandations remplies, sinon
    """
    # Toujours calculer les règles offline (rapide, gratuit)
    recos_offline = generer_recommandations_offline(resultat, contexte)

    # Si offline forcé ou pas de clé API, retour immédiat
    if forcer_offline or not api_disponible():
        return ResultatExpert(
            mode="offline",
            recommandations=recos_offline,
            message_info=("Mode hors ligne : recommandations générées par règles conditionnelles. "
                          "Configurez OPENAI_API_KEY dans Streamlit Secrets pour activer "
                          "l'analyse experte GPT-4o mini." if not api_disponible()
                          else "Mode hors ligne activé par l'utilisateur."),
        )

    # Vérifier le cache
    cle = _cle_cache(resultat, contexte)
    if cle in _cache_reponses:
        return ResultatExpert(
            mode="online",
            texte_markdown=_cache_reponses[cle],
            recommandations=recos_offline,  # toujours dispo en secours
            message_info="Analyse experte (résultat en cache).",
        )

    # Charger le prompt système
    try:
        prompt_systeme = PROMPT_PATH.read_text(encoding="utf-8")
    except Exception:
        prompt_systeme = "Tu es un expert en thermique du bâtiment tropical. Réponds en français."

    # Construire le message utilisateur
    message_user = _construire_message_utilisateur(resultat, contexte)

    # Appeler l'API
    api_key = _get_api_key()
    texte = _appeler_gpt(prompt_systeme, message_user, api_key)

    if texte:
        _cache_reponses[cle] = texte
        return ResultatExpert(
            mode="online",
            texte_markdown=texte,
            recommandations=recos_offline,
            message_info=f"Analyse experte générée par {MODEL_NAME}.",
        )
    else:
        # Fallback silencieux : API indisponible, on utilise offline
        return ResultatExpert(
            mode="offline",
            recommandations=recos_offline,
            message_info=("L'analyse experte n'a pas pu être générée (API indisponible ou "
                          "quota dépassé). Recommandations basées sur les règles conditionnelles."),
        )
