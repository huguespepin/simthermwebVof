"""
app.py — Application web SimTherm (Streamlit).

Interface web du simulateur thermique quasi-statique pour bâtiments
en Afrique tropicale. Moteur de calcul strictement identique à la
version Excel (cf. tests/test_thermal_calc.py pour la preuve de
cohérence croisée).

Lancer en local :   streamlit run app.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

from core.db_loader import SimThermDB
from core.thermal_calc import calculer_thermique_complet, calc_score_simtherm, calc_U_multicouche
from core.constants import (
    USAGES_SENSIBLES, U_VITRAGE_TYPIQUE, U_PORTE_TYPIQUE, FS_PAR_DEFAUT_PORTE,
    LAMBDA_ENDUIT_TYPIQUE, FACTEURS_ORIENTATION, DECALAGES_ILOT_CHALEUR,
    ALPHA_TOIT_TYPIQUE, FS_VITRAGE_TYPIQUE, ENDUIT_SOURCES,
    LABEL_FIABILITE, COULEUR_FIABILITE, FIABILITE_TN_PAR_PAYS,
)
from expert.gpt_expert import obtenir_recommandations, api_disponible
from expert.scenarios import classer_materiaux, simuler_scenarios

# ============================================================
# CONFIGURATION DE LA PAGE
# ============================================================
st.set_page_config(
    page_title="SimTherm · Simulateur thermique Afrique tropicale",
    page_icon="🌡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Injection CSS pour appliquer le thème SimTherm (remplace .streamlit/config.toml)
st.markdown("""
    <style>
    :root {
        --primary-color: #1F4E78;
    }
    .stApp {
        background-color: #FFFFFF;
    }
    [data-testid="stSidebar"] {
        background-color: #EDF2FA;
    }
    h1, h2, h3 {
        color: #1F4E78;
    }
    </style>
""", unsafe_allow_html=True)

COULEUR_CLASSE = {
    "A": "#70AD47",  # vert
    "B": "#2E75B6",  # bleu
    "C": "#E97132",  # orange
    "D": "#C00000",  # rouge
}


def badge_fiabilite(niveau: str) -> str:
    """Rend un badge HTML coloré pour un niveau de fiabilité N1/N2/N3/H+/H-/N/D
    (hiérarchie à six niveaux, cf. Chapitre 2.2.1.2 du mémoire, Tableau IX)."""
    couleur = COULEUR_FIABILITE.get(niveau, "#8A8578")
    label = LABEL_FIABILITE.get(niveau, niveau)
    return (
        f'<span title="{label}" style="background-color:{couleur}; color:white; '
        f'padding:2px 8px; border-radius:8px; font-size:12px; font-weight:600;">'
        f'{niveau}</span>'
    )


# ============================================================
# CHARGEMENT DE LA BASE DE DONNÉES (mise en cache)
# ============================================================
@st.cache_resource
def charger_db():
    return SimThermDB("data/SimTherm_BD_v6.xlsx")


try:
    db = charger_db()
except FileNotFoundError as e:
    st.error(f"❌ {e}")
    st.stop()


# ============================================================
# EN-TÊTE
# ============================================================
st.title("🌡️ SimTherm")
st.caption(
    "Aide à la décision constructive · 11 pays · 156 villes · 55 matériaux locaux"
)
st.caption(
    "🌐 Interface en français. Pour l'anglais, l'espagnol ou une autre langue, "
    "utilisez la fonction de traduction de votre navigateur (clic droit → "
    "« Traduire en... »). Les résultats numériques (températures, classes A/B/C/D) "
    "restent valables dans toutes les langues."
)

# ============================================================
# BARRE LATÉRALE — PARAMÈTRES DU PROJET
# ============================================================
with st.sidebar:
    st.header("📍 Localisation")

    pays = st.selectbox("Pays", db.get_pays(), index=0)
    st.caption(f"Sélection : {pays}")

    villes = db.get_villes(pays)
    noms_villes = sorted([v.nom for v in villes])
    ville_nom = st.selectbox("Ville", noms_villes)
    st.caption(f"Sélection : {ville_nom}")
    ville = db.get_ville(pays, ville_nom)

    # Zone d'implantation — décalage d'îlot de chaleur urbain
    # (Chapitre 2.2.3.5 du mémoire)
    zone_implantation = st.selectbox(
        "Zone d'implantation",
        list(DECALAGES_ILOT_CHALEUR.keys()),
        index=0,
        help=("Décale la température extérieure de pointe pour tenir compte de "
              "l'îlot de chaleur urbain (Wemegah 2020, Offerle 2005). "
              "Rural : 0°C · Semi-urbain : +1°C · Urbain dense : +2°C."),
    )
    delta_ilot_chaleur = DECALAGES_ILOT_CHALEUR[zone_implantation]
    if delta_ilot_chaleur > 0:
        st.caption(f"↑ Tmax effective = {ville.tmax + delta_ilot_chaleur:.1f}°C "
                    f"(Tmax ville {ville.tmax}°C + îlot de chaleur +{delta_ilot_chaleur}°C)")

    st.divider()
    st.header("🏠 Bâtiment")

    batiments = db.get_batiments()
    noms_batiments = [b.nom for b in batiments]
    bat_nom = st.selectbox("Type de bâtiment", noms_batiments)
    st.caption(f"Sélection : {bat_nom}")
    batiment = db.get_batiment_par_nom(bat_nom)

    is_sensible = bat_nom in USAGES_SENSIBLES
    if is_sensible:
        st.info("ℹ️ Usage sensible : seuils de confort resserrés (EN 16798-1, catégorie I)")


    st.divider()
    st.header("📐 Géométrie")

    col1, col2 = st.columns(2)
    with col1:
        longueur = st.number_input("Longueur (m)", min_value=3.0, max_value=100.0, value=10.0, step=0.5)
        hauteur = st.number_input("Hauteur sous plafond (m)", min_value=2.0, max_value=6.0, value=2.8, step=0.1)
    with col2:
        largeur = st.number_input("Largeur (m)", min_value=3.0, max_value=100.0, value=8.0, step=0.5)
        niveaux = st.number_input("Nombre de niveaux", min_value=1, max_value=20, value=1, step=1)

    st.markdown("**Fenêtres (vitrées)**")
    surface_vitree = st.number_input("Surface des fenêtres (m²)", min_value=0.0, value=5.0, step=0.5,
                                       help="Baies vitrées : transmettent le rayonnement solaire (FS)")

    # Orientation dominante des fenêtres — module l'apport solaire des
    # vitrages (Chapitre 2.2.3.4 du mémoire). Reste sans effet sur les
    # murs opaques et sur les portes.
    orientation = st.selectbox(
        "Orientation dominante des fenêtres",
        list(FACTEURS_ORIENTATION.keys()),
        index=4,  # "Toutes façades (moyenne)" = 1.00
        help=("Nord (0,65) : moins exposé · Sud (0,85) : soleil de midi, "
              "protégeable · Est (1,10) : soleil du matin · Ouest (1,15) : "
              "façade la plus critique en climat tropical."),
    )
    facteur_orientation = FACTEURS_ORIENTATION[orientation]
    st.caption(f"Facteur d'apport solaire fenêtres = {facteur_orientation:.2f}")

    options_vitrage = list(U_VITRAGE_TYPIQUE.keys()) + ["Personnalisé (saisie manuelle)"]
    type_vitrage = st.selectbox("Type de vitrage", options_vitrage, index=2)
    if type_vitrage == "Personnalisé (saisie manuelle)":
        U_vitrage = st.number_input("U vitrage personnalisé (W/m²K)", min_value=0.1, max_value=10.0,
                                      value=2.8, step=0.1,
                                      help="Valeur trouvée sur la fiche technique du fabricant")
    else:
        U_vitrage = U_VITRAGE_TYPIQUE[type_vitrage]
        st.caption(f"U_vitrage = {U_vitrage} W/m²K")

    st.markdown("**Portes**")
    surface_porte = st.number_input("Surface des portes (m²)", min_value=0.0, value=2.0, step=0.5,
                                      help="Portes pleines : opaques (bois/métal, FS≈0) ou vitrées (FS>0)")

    options_porte = list(U_PORTE_TYPIQUE.keys()) + ["Personnalisé (saisie manuelle)"]
    type_porte = st.selectbox("Type de porte", options_porte, index=0)
    if type_porte == "Personnalisé (saisie manuelle)":
        col_up, col_fp = st.columns(2)
        with col_up:
            U_porte = st.number_input("U porte (W/m²K)", min_value=0.1, max_value=10.0,
                                        value=2.0, step=0.1)
        with col_fp:
            fs_porte = st.number_input("FS porte", min_value=0.0, max_value=1.0,
                                         value=0.0, step=0.05,
                                         help="0 = opaque (bois/métal plein), >0 = partiellement vitrée")
    else:
        U_porte = U_PORTE_TYPIQUE[type_porte]
        fs_porte = FS_PAR_DEFAUT_PORTE[type_porte]
        st.caption(f"U_porte = {U_porte} W/m²K · FS = {fs_porte} "
                    f"({'opaque, aucun apport solaire' if fs_porte == 0 else 'vitrée, transmet le rayonnement'})")

    surface_baies = surface_vitree + surface_porte  # surface totale des ouvertures (pour la géométrie du mur)

    # Géométrie dérivée (jamais stockée — toujours recalculée)
    A_plancher = longueur * largeur
    A_toit = longueur * largeur
    perimetre = 2 * (longueur + largeur)
    A_mur = perimetre * hauteur * niveaux - surface_baies
    volume = longueur * largeur * hauteur * niveaux

    with st.expander("Voir la géométrie calculée"):
        st.write(f"- Surface plancher : **{A_plancher:.1f} m²**")
        st.write(f"- Surface toiture : **{A_toit:.1f} m²**")
        st.write(f"- Surface murs opaques : **{A_mur:.1f} m²** (murs − fenêtres − portes)")
        st.write(f"- Volume : **{volume:.1f} m³**")

    st.divider()
    st.header("🧱 Matériau MUR")

    murs = db.get_materiaux_mur(pays)
    noms_murs = sorted([m.nom for m in murs])
    mur_nom = st.selectbox("Matériau du mur", noms_murs, key="mur_select")
    st.caption(f"Sélection : {mur_nom}")
    mur = db.get_materiau_par_nom(mur_nom)
    epaisseur_mur = st.number_input("Épaisseur mur (m)", min_value=0.05, max_value=1.0, value=0.20, step=0.01)

    if mur:
        st.caption(f"λ={mur.lambda_val} W/m·K · ρ={mur.rho} kg/m³ · Cp={mur.cp} J/kg·K")
        if mur.niveau_confiance:
            st.markdown(badge_fiabilite(mur.niveau_confiance), unsafe_allow_html=True)
        if mur.cout_local:
            st.caption(f"💰 Coût indicatif : {mur.cout_local:,.0f} {mur.monnaie}/m² · {mur.disponibilite or ''}")

    with st.expander("➕ Enduits et revêtements de finition (optionnel)", expanded=True):
        st.caption("Enduits (ciment, chaux, terre, plâtre) ou revêtement en carreaux, pris en compte dans le calcul de U par mise en série "
                    "des résistances thermiques (ISO 6946). Sans effet sur l'inertie (φ), cf. limite documentée.")
        appliquer_enduit = st.checkbox("Appliquer un enduit", value=False)
        if appliquer_enduit:
            types_enduit = list(LAMBDA_ENDUIT_TYPIQUE.keys())[:-1]
            col_ei, col_ee = st.columns(2)
            with col_ei:
                type_enduit_int = st.selectbox("Face intérieure", types_enduit, index=0, key="type_enduit_int")
                epaisseur_enduit_int = st.number_input("Épaisseur int. (m)", min_value=0.0, max_value=0.05,
                                                          value=0.015, step=0.005, format="%.3f")
            with col_ee:
                type_enduit_ext = st.selectbox("Face extérieure", types_enduit, index=0, key="type_enduit_ext")
                epaisseur_enduit_ext = st.number_input("Épaisseur ext. (m)", min_value=0.0, max_value=0.05,
                                                          value=0.015, step=0.005, format="%.3f")
            lambda_enduit = LAMBDA_ENDUIT_TYPIQUE[type_enduit_int]
            lambda_enduit_ext = LAMBDA_ENDUIT_TYPIQUE[type_enduit_ext]
            st.caption(f"λ intérieur = {lambda_enduit} W/m·K · λ extérieur = {lambda_enduit_ext} W/m·K")
            for face, tp in (("intérieur", type_enduit_int), ("extérieur", type_enduit_ext)):
                niv, src = ENDUIT_SOURCES[tp]
                st.markdown(badge_fiabilite(niv), unsafe_allow_html=True)
                st.caption(f"Source ({face}) : {src}")
            if "carreaux" in type_enduit_int or "carreaux" in type_enduit_ext:
                st.caption("Pour les carreaux, saisir l'épaisseur du carreau plus celle de la colle ou du mortier de pose (environ 1 à 1,5 cm).")
            if mur:
                u_sans = calc_U_multicouche(mur.lambda_val, epaisseur_mur, "mur")
                u_avec = calc_U_multicouche(
                    mur.lambda_val, epaisseur_mur, "mur",
                    epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext,
                    lambda_enduit_int=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext)
                st.info(f"U du mur : {u_sans:.3f} W/m²K sans enduit, **{u_avec:.3f} W/m²K avec enduit** "
                        f"({(u_avec - u_sans) / u_sans:+.1%}).")
        else:
            epaisseur_enduit_int, epaisseur_enduit_ext = 0.0, 0.0
            lambda_enduit, lambda_enduit_ext = 1.15, 1.15

    st.divider()
    st.header("🏗️ Matériau TOITURE")

    toits = db.get_materiaux_toit(pays)
    noms_toits = sorted([t.nom for t in toits])
    toit_nom = st.selectbox("Matériau de toiture", noms_toits, key="toit_select")
    st.caption(f"Sélection : {toit_nom}")
    toit = db.get_materiau_par_nom(toit_nom)
    epaisseur_toit = st.number_input("Épaisseur toiture (m)", min_value=0.002, max_value=0.5, value=0.05, step=0.005)

    if toit:
        st.caption(f"λ={toit.lambda_val} W/m·K · ρ={toit.rho} kg/m³ · Cp={toit.cp} J/kg·K")
        if toit.niveau_confiance:
            st.markdown(badge_fiabilite(toit.niveau_confiance), unsafe_allow_html=True)

    st.divider()
    st.header("☀️ Facteurs solaires")

    st.caption("α agit sur l'apport solaire de la TOITURE, FS sur celui des FENÊTRES. "
               "Les repères proposés sont des ordres de grandeur NON sourcés : privilégiez la fiche technique du produit.")

    OPT_PERSO = "Personnalisé (curseur)"
    choix_alpha = st.selectbox(
        "Surface de la toiture",
        list(ALPHA_TOIT_TYPIQUE.keys()) + [OPT_PERSO], index=len(ALPHA_TOIT_TYPIQUE),
        help="Repères indicatifs d'absorptivité solaire selon la couleur et la nature de la surface.")
    if choix_alpha == OPT_PERSO:
        alpha_toit = st.slider(
            "Absorptivité solaire de la toiture (α)", 0.0, 1.0, 0.6, 0.05,
            help="Fraction du rayonnement solaire absorbée par la toiture (α = 1 − albédo). "
                 "0 = surface blanche parfaitement réfléchissante, 1 = surface noire absorbante. "
                 "Plus α est grand, plus la toiture chauffe l'intérieur.")
    else:
        alpha_toit = ALPHA_TOIT_TYPIQUE[choix_alpha]
        st.caption(f"α = {alpha_toit:.2f} (absorbe {alpha_toit:.0%} du rayonnement solaire)")

    choix_fs = st.selectbox(
        "Protection solaire des fenêtres",
        list(FS_VITRAGE_TYPIQUE.keys()) + [OPT_PERSO], index=len(FS_VITRAGE_TYPIQUE),
        help="Repères indicatifs de facteur solaire ; la valeur exacte figure sur la fiche du fabricant.")
    if choix_fs == OPT_PERSO:
        fs_vitrage = st.slider(
            "Facteur solaire des fenêtres (FS)", 0.0, 1.0, 0.6, 0.05,
            help="Fraction du rayonnement solaire qui traverse la fenêtre vers l'intérieur. "
                 "0 = rien ne passe, 1 = tout passe. Le facteur solaire des portes est fixé "
                 "automatiquement selon leur type (section Portes).")
    else:
        fs_vitrage = FS_VITRAGE_TYPIQUE[choix_fs]
        st.caption(f"FS = {fs_vitrage:.2f} (laisse passer {fs_vitrage:.0%} du rayonnement)")


# ============================================================
# CALCUL PRINCIPAL
# ============================================================
if not (ville and batiment and mur and toit):
    st.warning("⚠️ Configuration incomplète, vérifiez les sélections dans la barre latérale.")
    st.stop()

resultat = calculer_thermique_complet(
    t_ext_max=ville.tmax, amplitude=ville.amplitude, tn=ville.tn,
    ghi_kwh_m2_j=ville.ghi,
    surface_mur=A_mur, surface_toit=A_toit, volume=volume,
    surface_vitree=surface_vitree, U_vitrage=U_vitrage, fs_vitrage=fs_vitrage,
    surface_porte=surface_porte, U_porte=U_porte, fs_porte=fs_porte,
    lambda_mur=mur.lambda_val, rho_mur=mur.rho, cp_mur=mur.cp, epaisseur_mur=epaisseur_mur,
    lambda_toit=toit.lambda_val, rho_toit=toit.rho, cp_toit=toit.cp, epaisseur_toit=epaisseur_toit,
    usage=bat_nom, apports_internes=batiment.apports_w_m2, nv=batiment.nv_vol_h,
    alpha_toit=alpha_toit,
    epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext, lambda_enduit=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext,
    facteur_orientation=facteur_orientation, delta_ilot_chaleur=delta_ilot_chaleur,
)

# ============================================================
# ONGLETS PRINCIPAUX
# ============================================================
tab_resultats, tab_comparaison, tab_simulation, tab_recommandations = st.tabs(
    ["📊 Résultats", "⚖️ Comparaison", "🔬 Simulation matériaux", "💡 Recommandations"]
)

# ------------------------------------------------------------
# ONGLET RÉSULTATS
# ------------------------------------------------------------
with tab_resultats:
    st.subheader(f"Résultats · {ville.nom}, {pays}")
    st.caption(f"Tmax={ville.tmax}°C · Tmoy={ville.tmoy}°C · Tn={ville.tn}°C · Amplitude={ville.amplitude}°C · Köppen={ville.koppen or 'N/D'}")
    fiabilite_tn = FIABILITE_TN_PAR_PAYS.get(pays)
    if fiabilite_tn:
        st.markdown(badge_fiabilite(fiabilite_tn), unsafe_allow_html=True)

    col_moy, col_max, col_min = st.columns(3)
    with col_moy:
        st.metric("T°int MOYENNE (confort ressenti)", f"{resultat.t_int_moy:.1f} °C",
                   delta=f"{resultat.classe_ressentie.delta_t:+.1f}°C vs Tn")
    with col_max:
        st.metric("T°int MAX (pic dimensionnant)", f"{resultat.t_int_max:.1f} °C",
                   delta=f"{resultat.classe_pic.delta_t:+.1f}°C vs Tn")
    with col_min:
        st.metric("T°int MIN (creux nocturne)", f"{resultat.t_int_min:.1f} °C")

    col_cls1, col_cls2 = st.columns(2)
    with col_cls1:
        c = resultat.classe_ressentie
        st.markdown(
            f"""<div style="background-color:{COULEUR_CLASSE[c.lettre]}; padding:20px;
            border-radius:10px; text-align:center;">
            <span style="color:white; font-size:14px;">CLASSE CONFORT RESSENTI</span><br>
            <span style="color:white; font-size:48px; font-weight:bold;">{c.lettre}</span><br>
            <span style="color:white; font-size:16px;">{c.description}</span>
            </div>""", unsafe_allow_html=True)
    with col_cls2:
        c = resultat.classe_pic
        st.markdown(
            f"""<div style="background-color:{COULEUR_CLASSE[c.lettre]}; padding:20px;
            border-radius:10px; text-align:center;">
            <span style="color:white; font-size:14px;">CLASSE PIC DIMENSIONNANT</span><br>
            <span style="color:white; font-size:48px; font-weight:bold;">{c.lettre}</span><br>
            <span style="color:white; font-size:16px;">{c.description}</span>
            </div>""", unsafe_allow_html=True)

    st.divider()

    with st.expander("🔍 Détail des calculs (ISO 6946 / ISO 13786 / Asan 1998)", expanded=False):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("**① Coefficients U, ISO 6946:2017**")
            st.write(f"U_mur = {resultat.U_mur:.3f} W/m²K")
            st.write(f"U_toit = {resultat.U_toit:.3f} W/m²K")
            st.markdown("**② Déphasage φ, approximation semi-infinie**")
            st.write(f"φ_mur = {resultat.phi_mur_h:.1f} h")
            st.write(f"φ_toit = {resultat.phi_toit_h:.1f} h")
            st.caption("Écart ~6% vs formulation rigoureuse ISO 13786 (cf. Chapitre 2.2.3 du mémoire)")
        with c2:
            st.markdown("**③ Méthode admittance, CIBSE + Asan (1998)**")
            st.write(f"f_mur = {resultat.f_mur:.3f}  (ξ_mur = {resultat.xi_mur:.3f})")
            st.write(f"f_toit = {resultat.f_toit:.3f}  (ξ_toit = {resultat.xi_toit:.3f})")
            st.write(f"f_env = {resultat.f_env:.3f}")
            st.markdown("**Conductances**")
            st.write(f"H_mur={resultat.H_mur:.1f} · H_toit={resultat.H_toit:.1f} · "
                       f"H_fenêtres={resultat.H_vitree:.1f} · H_portes={resultat.H_porte:.1f} · "
                       f"H_vent={resultat.H_vent:.1f} · **H_total={resultat.H_total:.1f} W/K**")

        st.markdown("**Apports thermiques moyens**")
        st.write(f"Q_solaire toiture = {resultat.Q_solaire_toit:.0f} W · "
                   f"Q_solaire baies = {resultat.Q_solaire_baies:.0f} W · "
                   f"Q_internes = {resultat.Q_internes:.0f} W · "
                   f"**Q_moy total = {resultat.Q_moy:.0f} W**")

    # Graphique cycle diurne simplifié (sinusoïde autour de la moyenne)
    st.divider()
    st.markdown("**Aperçu du cycle diurne (approximation sinusoïdale)**")
    import numpy as np
    heures = np.linspace(0, 24, 100)
    t_ext_cycle = ville.tmax - ville.amplitude / 2 + (ville.amplitude / 2) * np.cos(2 * np.pi * (heures - 14) / 24)
    t_int_cycle = resultat.t_int_moy + resultat.f_env * (ville.amplitude / 2) * np.cos(2 * np.pi * (heures - 14 - resultat.phi_mur_h) / 24)

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=heures, y=t_ext_cycle, name="T° extérieure", line=dict(color="#E97132", width=2)))
    fig.add_trace(go.Scatter(x=heures, y=t_int_cycle, name="T° intérieure", line=dict(color="#2E75B6", width=2)))
    fig.add_hline(y=ville.tn, line_dash="dash", line_color="#70AD47", annotation_text="Tn (neutralité)")
    fig.update_layout(xaxis_title="Heure", yaxis_title="Température (°C)", height=350,
                       margin=dict(l=20, r=20, t=20, b=20))
    st.plotly_chart(fig, width='stretch')
    st.caption("Cycle thermique journalier estimé (sinusoïde approximative)")


# ------------------------------------------------------------
# ONGLET COMPARAISON
# ------------------------------------------------------------
with tab_comparaison:
    st.subheader("Comparaison de 2 matériaux MUR")
    st.caption("Configuration identique (géométrie, toiture), seul le matériau du mur diffère")

    col_a, col_b = st.columns(2)
    with col_a:
        st.markdown("**Configuration A**")
        mur_a_nom = st.selectbox("Matériau A", noms_murs, index=0, key="cmp_a")
        mur_a = db.get_materiau_par_nom(mur_a_nom)
    with col_b:
        st.markdown("**Configuration B**")
        idx_b = min(1, len(noms_murs) - 1)
        mur_b_nom = st.selectbox("Matériau B", noms_murs, index=idx_b, key="cmp_b")
        mur_b = db.get_materiau_par_nom(mur_b_nom)

    if mur_a and mur_b:
        r_a = calculer_thermique_complet(
            t_ext_max=ville.tmax, amplitude=ville.amplitude, tn=ville.tn, ghi_kwh_m2_j=ville.ghi,
            surface_mur=A_mur, surface_toit=A_toit, volume=volume,
            surface_vitree=surface_vitree, U_vitrage=U_vitrage, fs_vitrage=fs_vitrage,
            surface_porte=surface_porte, U_porte=U_porte, fs_porte=fs_porte,
            lambda_mur=mur_a.lambda_val, rho_mur=mur_a.rho, cp_mur=mur_a.cp, epaisseur_mur=epaisseur_mur,
            lambda_toit=toit.lambda_val, rho_toit=toit.rho, cp_toit=toit.cp, epaisseur_toit=epaisseur_toit,
            usage=bat_nom, apports_internes=batiment.apports_w_m2, nv=batiment.nv_vol_h,
            alpha_toit=alpha_toit,
            epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext, lambda_enduit=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext,
            facteur_orientation=facteur_orientation, delta_ilot_chaleur=delta_ilot_chaleur,
        )
        r_b = calculer_thermique_complet(
            t_ext_max=ville.tmax, amplitude=ville.amplitude, tn=ville.tn, ghi_kwh_m2_j=ville.ghi,
            surface_mur=A_mur, surface_toit=A_toit, volume=volume,
            surface_vitree=surface_vitree, U_vitrage=U_vitrage, fs_vitrage=fs_vitrage,
            surface_porte=surface_porte, U_porte=U_porte, fs_porte=fs_porte,
            lambda_mur=mur_b.lambda_val, rho_mur=mur_b.rho, cp_mur=mur_b.cp, epaisseur_mur=epaisseur_mur,
            lambda_toit=toit.lambda_val, rho_toit=toit.rho, cp_toit=toit.cp, epaisseur_toit=epaisseur_toit,
            usage=bat_nom, apports_internes=batiment.apports_w_m2, nv=batiment.nv_vol_h,
            alpha_toit=alpha_toit,
            epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext, lambda_enduit=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext,
            facteur_orientation=facteur_orientation, delta_ilot_chaleur=delta_ilot_chaleur,
        )

        df_cmp = pd.DataFrame({
            "Grandeur": ["U (W/m²K)", "φ (heures)", "T°int moyenne (°C)", "T°int max (°C)",
                          "Classe ressentie", "Classe pic"],
            f"A : {mur_a_nom}": [f"{r_a.U_mur:.2f}", f"{r_a.phi_mur_h:.1f}",
                                   f"{r_a.t_int_moy:.1f}", f"{r_a.t_int_max:.1f}",
                                   r_a.classe_ressentie.lettre, r_a.classe_pic.lettre],
            f"B : {mur_b_nom}": [f"{r_b.U_mur:.2f}", f"{r_b.phi_mur_h:.1f}",
                                   f"{r_b.t_int_moy:.1f}", f"{r_b.t_int_max:.1f}",
                                   r_b.classe_ressentie.lettre, r_b.classe_pic.lettre],
        })
        st.dataframe(df_cmp, width='stretch', hide_index=True)

        diff_t = r_b.t_int_moy - r_a.t_int_moy
        if abs(diff_t) < 0.3:
            st.info("➡️ Configurations quasi-équivalentes pour ce paramétrage (toiture/ventilation dominantes).")
        elif diff_t < 0:
            st.success(f"✓ Le matériau B réduit la température moyenne de {abs(diff_t):.1f}°C par rapport à A.")
        else:
            st.warning(f"⚠ Le matériau B augmente la température moyenne de {diff_t:.1f}°C par rapport à A.")


# ------------------------------------------------------------
# ONGLET SIMULATION MATÉRIAUX (TOP 5)
# ------------------------------------------------------------
with tab_simulation:
    st.subheader(f"Comparaison automatique, tous les matériaux MUR disponibles ({pays})")

    @st.cache_data(show_spinner=False)
    def _comparer_materiaux_mur(
        murs_noms_lambda_rho_cp_niveau_cout_monnaie, toit_key,
        t_ext_max, amplitude, tn, ghi, A_mur, A_toit, volume,
        surface_vitree, U_vitrage, fs_vitrage, surface_porte, U_porte, fs_porte,
        lambda_toit, rho_toit, cp_toit, epaisseur_toit, epaisseur_mur,
        bat_nom, apports_w_m2, nv_vol_h, alpha_toit,
        epaisseur_enduit_int, epaisseur_enduit_ext, lambda_enduit, lambda_enduit_ext,
        facteur_orientation, delta_ilot_chaleur,
    ):
        resultats = []
        for (nom, categorie, lam, rho, cp, niveau, cout, monnaie) in murs_noms_lambda_rho_cp_niveau_cout_monnaie:
            r = calculer_thermique_complet(
                t_ext_max=t_ext_max, amplitude=amplitude, tn=tn, ghi_kwh_m2_j=ghi,
                surface_mur=A_mur, surface_toit=A_toit, volume=volume,
                surface_vitree=surface_vitree, U_vitrage=U_vitrage, fs_vitrage=fs_vitrage,
                surface_porte=surface_porte, U_porte=U_porte, fs_porte=fs_porte,
                lambda_mur=lam, rho_mur=rho, cp_mur=cp, epaisseur_mur=epaisseur_mur,
                lambda_toit=lambda_toit, rho_toit=rho_toit, cp_toit=cp_toit, epaisseur_toit=epaisseur_toit,
                usage=bat_nom, apports_internes=apports_w_m2, nv=nv_vol_h,
                alpha_toit=alpha_toit,
                epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext,
                lambda_enduit=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext,
                facteur_orientation=facteur_orientation, delta_ilot_chaleur=delta_ilot_chaleur,
            )
            score = calc_score_simtherm(r.U_mur, r.phi_mur_h)
            cout_str = f"{cout:,.0f} {monnaie}" if cout else "N/D"
            resultats.append({
                "Matériau": nom, "Catégorie": categorie, "Fiabilité": niveau or "N/D",
                "U (W/m²K)": round(r.U_mur, 2), "φ (h)": round(r.phi_mur_h, 1),
                "T°int moy (°C)": round(r.t_int_moy, 1), "T°int max (°C)": round(r.t_int_max, 1),
                "Classe ressentie": r.classe_ressentie.lettre, "Classe pic": r.classe_pic.lettre,
                "Score SimTherm": round(score, 1), "Coût indicatif/m²": cout_str,
            })
        return resultats

    murs_tuple = tuple(
        (m.nom, m.categorie, m.lambda_val, m.rho, m.cp, m.niveau_confiance, m.cout_local, m.monnaie)
        for m in murs
    )
    lignes = _comparer_materiaux_mur(
        murs_tuple, toit_nom,
        ville.tmax, ville.amplitude, ville.tn, ville.ghi, A_mur, A_toit, volume,
        surface_vitree, U_vitrage, fs_vitrage, surface_porte, U_porte, fs_porte,
        toit.lambda_val, toit.rho, toit.cp, epaisseur_toit, epaisseur_mur,
        bat_nom, batiment.apports_w_m2, batiment.nv_vol_h, alpha_toit,
        epaisseur_enduit_int, epaisseur_enduit_ext, lambda_enduit, lambda_enduit_ext,
        facteur_orientation, delta_ilot_chaleur,
    )

    df_sim = pd.DataFrame(lignes).sort_values("Score SimTherm", ascending=False).reset_index(drop=True)
    df_sim.index = df_sim.index + 1

    st.markdown("**🏆 TOP 5 matériaux (classement par score composite)**")
    top5 = df_sim.head(5)
    medailles = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    for i, (_, row) in enumerate(top5.iterrows()):
        st.markdown(f"{medailles[i]} **{row['Matériau']}** [{row['Fiabilité']}] Score {row['Score SimTherm']} · "
                     f"Classe {row['Classe ressentie']} · T°int {row['T°int moy (°C)']}°C")

    st.divider()
    st.markdown("**Tableau complet**")
    st.dataframe(df_sim, width='stretch')

    fig2 = go.Figure(go.Bar(
        x=df_sim.head(10)["Matériau"], y=df_sim.head(10)["Score SimTherm"],
        marker_color="#2E75B6",
    ))
    fig2.update_layout(title="Top 10 matériaux par score", height=350,
                        margin=dict(l=20, r=20, t=40, b=100))
    st.plotly_chart(fig2, width='stretch')


# ------------------------------------------------------------
# ONGLET RECOMMANDATIONS
# ------------------------------------------------------------
with tab_recommandations:
    st.subheader("💡 Analyse experte")

    # Indicateur mode online/offline + toggle utilisateur
    col_status, col_toggle = st.columns([3, 1])
    with col_status:
        if api_disponible():
            st.caption("🟢 Analyse experte GPT-4o mini disponible")
        else:
            st.caption("⚪ Analyse experte hors ligne (règles conditionnelles)")
    with col_toggle:
        forcer_offline = st.toggle("Mode hors ligne", value=False,
                                      help="Force l'utilisation des règles locales même si l'IA est disponible")

    # Bouton de génération explicite (évite les appels API à chaque changement d'input)
    if st.button("🔍 Générer l'analyse", type="primary", width="stretch"):

        # Pré-calculs fournis à l'expert (cf. expert/scenarios.py) :
        # classement des meilleurs matériaux du pays et scénarios « et si »,
        # calculés par le moteur pour que les gains cités soient réels.
        params_calcul = dict(
            t_ext_max=ville.tmax, amplitude=ville.amplitude, tn=ville.tn,
            ghi_kwh_m2_j=ville.ghi,
            surface_mur=A_mur, surface_toit=A_toit, volume=volume,
            surface_vitree=surface_vitree, U_vitrage=U_vitrage, fs_vitrage=fs_vitrage,
            surface_porte=surface_porte, U_porte=U_porte, fs_porte=fs_porte,
            lambda_mur=mur.lambda_val, rho_mur=mur.rho, cp_mur=mur.cp, epaisseur_mur=epaisseur_mur,
            lambda_toit=toit.lambda_val, rho_toit=toit.rho, cp_toit=toit.cp, epaisseur_toit=epaisseur_toit,
            usage=bat_nom, apports_internes=batiment.apports_w_m2, nv=batiment.nv_vol_h,
            alpha_toit=alpha_toit,
            epaisseur_enduit_int=epaisseur_enduit_int, epaisseur_enduit_ext=epaisseur_enduit_ext,
            lambda_enduit=lambda_enduit, lambda_enduit_ext=lambda_enduit_ext,
            facteur_orientation=facteur_orientation, delta_ilot_chaleur=delta_ilot_chaleur,
        )
        classement_murs = classer_materiaux(params_calcul, murs, "mur", n=5)
        classement_toits = classer_materiaux(params_calcul, toits, "toit", n=5)
        scenarios = simuler_scenarios(
            params_calcul, resultat,
            meilleur_mur=classement_murs[0]["materiau"] if classement_murs else None,
            meilleure_toit=classement_toits[0]["materiau"] if classement_toits else None,
        )

        def _resume(c):  # format attendu par les règles hors ligne
            if not c:
                return None
            return {"nom": c["nom"], "lambda": c["lambda"], "cout": c["cout"], "monnaie": c["monnaie"]}

        meilleur_mur_pays = _resume(classement_murs[0] if classement_murs else None)
        meilleure_toit_pays = _resume(classement_toits[0] if classement_toits else None)

        # Construire le contexte pour l'expert
        contexte = {
            "pays": pays,
            "ville": ville.nom,
            "usage": bat_nom,
            "tmax": ville.tmax,
            "tmoy": ville.tmoy,
            "tn": ville.tn,
            "amplitude": ville.amplitude,
            "materiau_mur": mur.nom,
            "materiau_toit": toit.nom,
            "epaisseur_mur": epaisseur_mur,
            "epaisseur_toit": epaisseur_toit,
            "alpha_toit": alpha_toit,
            "fs_baies": fs_vitrage,
            "orientation": orientation,
            "facteur_orientation": facteur_orientation,
            "zone_implantation": zone_implantation,
            "delta_ilot_chaleur": delta_ilot_chaleur,
            "meilleur_mur_pays": meilleur_mur_pays,
            "meilleure_toit_pays": meilleure_toit_pays,
            "classement_murs": classement_murs,
            "classement_toits": classement_toits,
            "scenarios": scenarios,
            "humidite": ville.humidite,
            "tmin": ville.tmin,
            "props_materiaux": {
                "mur": {"lambda": mur.lambda_val, "rho": mur.rho, "cp": mur.cp, "cout": mur.cout_local,
                        "monnaie": mur.monnaie, "niveau_confiance": mur.niveau_confiance},
                "toit": {"lambda": toit.lambda_val, "rho": toit.rho, "cp": toit.cp, "cout": toit.cout_local,
                         "monnaie": toit.monnaie, "niveau_confiance": toit.niveau_confiance},
            },
            # Éléments supplémentaires pour une analyse détaillée
            "ghi": ville.ghi,
            "surface_mur": A_mur,
            "surface_toit": A_toit,
            "volume": volume,
            "niveaux": niveaux,
            "surface_vitree": surface_vitree,
            "surface_porte": surface_porte,
            "u_vitrage": U_vitrage,
            "apports_internes": batiment.apports_w_m2,
            "nv": batiment.nv_vol_h,
            "enduit_int": type_enduit_int if appliquer_enduit else None,
            "enduit_ext": type_enduit_ext if appliquer_enduit else None,
            "epaisseur_enduit_int": epaisseur_enduit_int,
            "epaisseur_enduit_ext": epaisseur_enduit_ext,
        }

        with st.spinner("Analyse en cours..."):
            expert = obtenir_recommandations(resultat, contexte, forcer_offline=forcer_offline)

        # Stocker le résultat dans la session pour affichage persistant
        st.session_state["expert_resultat"] = expert

    # Affichage du dernier résultat obtenu
    if "expert_resultat" in st.session_state:
        expert = st.session_state["expert_resultat"]

        st.caption(expert.message_info)
        st.divider()

        if expert.mode == "online" and expert.texte_markdown:
            # Réponse GPT-4o mini
            st.markdown(expert.texte_markdown)

            # Repli offline consultable dans un expander
            with st.expander("📋 Voir aussi les règles conditionnelles (mode hors ligne)"):
                for reco in expert.recommandations or []:
                    st.markdown(f"**{reco.icone} {reco.titre}** ({reco.label_priorite})")
                    st.markdown(f"*{reco.diagnostic}*")
                    st.markdown(f"→ {reco.reco}")
                    st.markdown("---")
        else:
            # Mode offline : afficher les règles
            for reco in expert.recommandations or []:
                with st.container(border=True):
                    st.markdown(f"### {reco.icone} {reco.titre}")
                    st.caption(reco.label_priorite)
                    st.markdown(f"**Diagnostic :** {reco.diagnostic}")
                    st.markdown(f"**Recommandation :** {reco.reco}")
    else:
        st.info("Cliquez sur « Générer l'analyse » pour obtenir un diagnostic personnalisé "
                 "et des recommandations d'amélioration basées sur la configuration actuelle.")


# ============================================================
# PIED DE PAGE
# ============================================================
st.divider()
st.caption("SimTherm v1.0 · INSTI Lokossa / UNSTIM, Bénin · 2026")
