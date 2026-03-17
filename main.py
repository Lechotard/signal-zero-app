import streamlit as st
import os
import json
import requests
import time
import math
from datetime import datetime
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS
import folium
from streamlit_folium import st_folium
import streamlit.components.v1 as components
import yfinance as yf
import plotly.graph_objects as go
from fpdf import FPDF
import pandas as pd

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Signal Zero - Sentinelle", page_icon="🌍", layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
    <style>
        .block-container { padding-top: 2rem; padding-bottom: 0rem; }
        .stTabs [data-baseweb="tab-list"] { gap: 2rem; }
        .stTabs [data-baseweb="tab"] { height: 50px; white-space: pre-wrap; font-size: 18px; }
        
        /* --- DESIGN WORLD MONITOR --- */
        .trade-restriction-card { background-color: #1e1e24; border: 1px solid #333; border-radius: 6px; padding: 15px; margin-bottom: 12px; font-family: sans-serif; transition: 0.3s; }
        .trade-restriction-card:hover { border-color: #555; background-color: #222229; }
        .trade-restriction-header { display: flex; align-items: center; margin-bottom: 10px; }
        .trade-country { font-weight: bold; color: white; flex-grow: 1; font-size: 1.1em; }
        .sc-status-dot { height: 10px; width: 10px; border-radius: 50%; display: inline-block; margin-right: 8px; }
        .sc-dot-red { background-color: #ff4b4b; box-shadow: 0 0 8px #ff4b4b; }
        .sc-dot-yellow { background-color: #faca2b; box-shadow: 0 0 8px #faca2b; }
        .sc-dot-green { background-color: #21c354; box-shadow: 0 0 8px #21c354; }
        .trade-badge { background-color: #333; padding: 3px 8px; border-radius: 4px; font-size: 0.85em; color: #ddd; margin-right: 10px; font-weight: bold;}
        .trade-status { font-size: 0.75em; text-transform: uppercase; font-weight: bold; letter-spacing: 1px; }
        .status-active { color: #ff4b4b; }
        .status-notified { color: #faca2b; }
        .status-terminated { color: #21c354; }
        .trade-restriction-body { padding-left: 2px; }
        .trade-sector { font-size: 0.8em; color: #888; margin-bottom: 8px; font-weight: 500;}
        .trade-description { font-size: 0.9em; color: #ccc; margin-bottom: 8px; line-height: 1.4; }
        .trade-affected { font-size: 0.85em; color: #999; font-style: italic; border-top: 1px solid #333; padding-top: 6px; }
    </style>
""", unsafe_allow_html=True)

load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# --- LA MÉMOIRE DE LA PAGE ---
if 'crise_actuelle' not in st.session_state: st.session_state.crise_actuelle = None
if 'chokepoints_data' not in st.session_state: st.session_state.chokepoints_data = None
if 'scans_utilises' not in st.session_state: st.session_state.scans_utilises = 0
if 'est_premium' not in st.session_state: st.session_state.est_premium = False
if 'flotte_actuelle' not in st.session_state: st.session_state.flotte_actuelle = [] 

# --- SIDEBAR ---
st.sidebar.title("⚙️ Paramètres / Settings")
langue_choisie = st.sidebar.selectbox("🌐 Langue du système :", ("Français", "English", "Español", "中文 (Chinois)", "हिन्दी (Hindi)"))

st.sidebar.divider()
st.sidebar.markdown("### 🔑 Accès VIP / Admin")
code_admin = st.sidebar.text_input("Code d'activation PRO :", type="password")
if code_admin == "CEO2026":
    st.session_state.est_premium = True
    st.sidebar.success("💎 Mode Premium Déverrouillé !")
    if st.sidebar.button("🔄 Reset des scans (Admin)"):
        st.session_state.scans_utilises = 0
else:
    st.session_state.est_premium = False

def tr(fr, en, es, zh, hi):
    if langue_choisie == "English": return en
    if langue_choisie == "Español": return es
    if langue_choisie == "中文 (Chinois)": return zh
    if langue_choisie == "हिन्दी (Hindi)": return hi
    return fr

# --- FONCTION MATHÉMATIQUE (MOTEUR RADAR) ---
def calculer_distance_gps(lat1, lon1, lat2, lon2):
    """Calcule la distance en kilomètres entre deux points GPS sur Terre."""
    R = 6371.0 # Rayon moyen de la Terre en km
    lat1_rad, lon1_rad = math.radians(lat1), math.radians(lon1)
    lat2_rad, lon2_rad = math.radians(lat2), math.radians(lon2)
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    a = math.sin(dlat / 2)**2 + math.cos(lat1_rad) * math.cos(lat2_rad) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

# --- LES MOULES DE DONNÉES (AJOUT DU PORT ET ETA) ---
class TimelineEvent(BaseModel):
    date_heure: str = Field(...)
    evenement: str = Field(...)
    source: str = Field(...)

class CrisisAlert(BaseModel):
    crise_detectee: bool = Field(...)
    titre_alerte: str = Field(...)
    nom_cible: str = Field(...)
    resume_incident: str = Field(...)
    matieres_premieres_impactees: list[str] = Field(...)
    consequences_supply_chain: str = Field(...)
    recommandation_action: str = Field(...)
    latitude: float = Field(...)
    longitude: float = Field(...)
    chronologie_semaine: list[TimelineEvent] = Field(...)

class ShipDossier(BaseModel):
    nom: str = Field(..., description="Nom exact du navire. Mets 'Inconnu' si introuvable.")
    imo: str = Field(..., description="Numéro IMO.")
    type_navire: str = Field(..., description="Type de navire.")
    pavillon: str = Field(..., description="Pays d'enregistrement.")
    destination: str = Field(..., description="Destination finale annoncée.")
    date_arrivee_prevue: str = Field(default="Inconnue", description="ETA ou Date d'arrivée prévue à la destination. Mets 'Inconnue' si introuvable.")
    dernier_port: str = Field(default="Inconnu", description="Dernier port visité ou port de provenance (Previous Port). Mets 'Inconnu' si introuvable.")
    date_depart_dernier_port: str = Field(default="Inconnue", description="Date et heure de départ du dernier port. Mets 'Inconnue' si introuvable.")
    vitesse_statut: str = Field(..., description="Vitesse actuelle et statut (ex: Under way, Moored).")
    details_techniques: str = Field(...)
    latitude: float = Field(..., description="Latitude EXACTE si présente dans le texte. Sinon, latitude EXACTE du 'dernier_port'.")
    longitude: float = Field(..., description="Longitude EXACTE si présente dans le texte. Sinon, longitude EXACTE du 'dernier_port'.")
    precision_gps: str = Field(default="Inconnue", description="Écris 'Exacte (Détectée)' si tu as les vrais chiffres GPS, ou 'Port (Déduit)' si tu t'es basé sur le dernier port.")
    tirant_d_eau_actuel: str = Field(...)

class ChokepointAnalyse(BaseModel):
    nom: str = Field(...)
    score: int = Field(..., description="Score de risque de 0 à 100")
    avertissements: int = Field(default=0, description="Nombre d'avertissements de sécurité")
    perturbations: int = Field(default=0, description="Nombre de perturbations physiques/AIS")
    description: str = Field(...)
    impact: str = Field(..., description="Marchandises ou routes impactées (ex: Gulf Oil Exports)")

class ListeChokepoints(BaseModel):
    points: list[ChokepointAnalyse]

class PortCongestion(BaseModel):
    nom_port: str = Field(..., description="Nom EXACT du port (ex: Port of Los Angeles, Port of Antwerp). INTERDIT de mettre une région vague.")
    pays: str = Field(...)
    cause_delai: str = Field(..., description="Raison courte : Grève, Météo, Congestion...")
    niveau_gravite: str = Field(..., description="Critique, Élevé, ou Modéré")
    latitude: float = Field(..., description="Latitude GPS décimale exacte du port (ex: 33.7294)")
    longitude: float = Field(..., description="Longitude GPS décimale exacte du port (ex: -118.2620)")

class ListePortsCongestionnes(BaseModel):
    ports: list[PortCongestion]

class TradeBarrier(BaseModel):
    pays: str = Field(..., description="Pays appliquant la barrière (ex: Inde, Chine, USA)")
    niveau_protection: str = Field(..., description="Ex: Protection Haute, Modérée, Faible")
    secteur_concerne: str = Field(..., description="Ex: Produits Agricoles vs Non-agricoles")
    ecart_taxe: str = Field(..., description="Le chiffre ou l'écart (ex: +36.7% ou Taxe à 15%)")
    resume: str = Field(..., description="Explication très courte de la politique")

class ListeTradeBarriers(BaseModel):
    barriers: list[TradeBarrier]

# --- FONCTION POUR GÉNÉRER LE PDF ---
def generer_rapport_pdf(rapport):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=15)
    def txt_safe(texte): return str(texte).encode('latin-1', 'replace').decode('latin-1')
    pdf.set_font("Arial", 'B', 20)
    pdf.set_text_color(0, 51, 102) 
    pdf.cell(0, 15, txt_safe("Signal Zero - Report"), ln=True, align='C')
    pdf.set_font("Arial", 'I', 12)
    pdf.set_text_color(100, 100, 100) 
    pdf.cell(0, 10, txt_safe("Automated Intelligence & Geopolitical Analysis"), ln=True, align='C')
    pdf.ln(10) 
    pdf.set_font("Arial", 'B', 16)
    pdf.set_text_color(220, 53, 69) 
    pdf.cell(0, 10, txt_safe(f"ALERT: {rapport['titre_alerte']}"), ln=True)
    pdf.ln(5)
    pdf.set_text_color(0, 0, 0)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, txt_safe(f"Target : {rapport['nom_cible']}"), ln=True)
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, txt_safe("Incident Summary :"), ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 6, txt_safe(rapport['resume_incident']))
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, txt_safe("Supply Chain Impact :"), ln=True)
    pdf.set_font("Arial", '', 11)
    pdf.multi_cell(0, 6, txt_safe(rapport['consequences_supply_chain']))
    pdf.ln(5)
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 8, txt_safe("Strategic Recommendations :"), ln=True)
    pdf.set_font("Arial", 'I', 11)
    pdf.multi_cell(0, 6, txt_safe(rapport['recommandation_action']))
    return pdf.output(dest='S').encode('latin-1')

# --- AGENTS VEILLEURS ---
def scanner_actualites_maritimes():
    try:
        resultats = DDGS().news("maritime shipping OR cargo attack OR port strike OR vessel grounded OR canal blocked OR Cargo ships OR container ships OR tankers", max_results=15, timelimit='w')
        if not resultats: return "Aucune dépêche maritime majeure détectée."
        texte_propre = ""
        for i, r in enumerate(resultats):
            date_brute = r.get('date', 'Date inconnue')
            date_nettoyee = date_brute.replace('T', ' ')[:19] 
            source = r.get('source', f'Source {i+1}')
            texte_propre += f"Source: {source} | Date: {date_nettoyee} | Titre: {r['title']} | Résumé: {r['body']}\n---\n"
        return texte_propre
    except: return "Erreur lors de la récupération des actualités."

def scanner_chokepoints_news():
    try:
        # Requête élargie pour capter tous les blocages stratégiques
        resultats = DDGS().news("strait OR canal OR cape shipping disruption OR maritime bottleneck OR energy infrastructure OR canal blocked", max_results=20, timelimit='w')
        if not resultats: return "Aucune perturbation majeure signalée dans la presse. Trafic fluide sur tous les détroits."
        texte_propre = ""
        for r in resultats: texte_propre += f"Titre: {r['title']}\nRésumé: {r['body']}\n---\n"
        return texte_propre
    except: return "Aucune perturbation majeure signalée dans la presse."

# --- INTERFACE UTILISATEUR ---

st.title(tr("🌍 Signal Zero : Centre de Commandement", "🌍 Signal Zero: Command Center", "🌍 Signal Zero: Centro de Mando", "🌍 Signal Zero：指挥中心", "🌍 सिग्नल ज़ीरो: कमांड सेंटर"))

# ==========================================
# LE CERVEAU GLOBAL (MOTEUR IA EN ARRIÈRE-PLAN)
# ==========================================
@st.cache_resource
def obtenir_memoire_serveur():
    return {"heure_dernier_scan": 0.0, "crise_actuelle": None, "heure_crise": 0.0, "ports_accumules": {}}

memoire_serveur = obtenir_memoire_serveur()
maintenant = time.time()

# 🔄 BOUTON DE DÉBOGAGE (Dans la barre latérale)
if st.sidebar.button("🔄 Forcer le scan IA (Ignorer le délai d'1h)"):
    memoire_serveur["heure_dernier_scan"] = 0.0 # On remet le chrono à zéro !

# ⏳ LE MOTEUR D'ACCUMULATION (1 heure)
if maintenant - memoire_serveur["heure_dernier_scan"] > 3600:
    
    # 1. SCAN DES CRISES
    try:
        actualites = scanner_actualites_maritimes()
        client = genai.Client(api_key=GEMINI_KEY)
        prompt_crise = f"Tu es analyste. Lis ces dépêches : {actualites}. Y a-t-il un incident GRAVE ? Si OUI, 'crise_detectee' à True. Rédige en {langue_choisie}."
        res_c = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_crise, config={'response_mime_type': 'application/json', 'response_schema': CrisisAlert, 'temperature': 0.1})
        nouvelle_crise = json.loads(res_c.text)
        if nouvelle_crise and nouvelle_crise.get('crise_detectee'):
            memoire_serveur["crise_actuelle"] = nouvelle_crise
            memoire_serveur["heure_crise"] = maintenant
    except Exception: pass

    # 2. SCAN DES PORTS
    try:
        actus_ports = DDGS().news("port congestion OR port strike OR terminal backlog OR maritime delays", max_results=15, timelimit='w')
        if actus_ports:
            texte_actus = "".join([f"- {r['title']}: {r['body']}\n" for r in actus_ports])
            prompt_ports = f"Cartographe expert. Lis ça : {texte_actus}. Dresse la liste des PORTS avec des congestions. Donne le nom EXACT et GPS exact. Rédige en {langue_choisie}."
            res_p = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_ports, config={'response_mime_type': 'application/json', 'response_schema': ListePortsCongestionnes, 'temperature': 0.1})
            nouveaux_ports = json.loads(res_p.text)
            
            if nouveaux_ports and nouveaux_ports.get('ports'):
                for port in nouveaux_ports['ports']:
                    nom = port.get('nom_port')
                    port['heure_ajout'] = maintenant 
                    memoire_serveur["ports_accumules"][nom] = port 
    except Exception: pass

    # 3. LE GRAND NETTOYAGE DES 24H
    if memoire_serveur["crise_actuelle"] and (maintenant - memoire_serveur["heure_crise"] > 86400):
        memoire_serveur["crise_actuelle"] = None
        
    ports_recents = {nom: port for nom, port in memoire_serveur["ports_accumules"].items() if maintenant - port['heure_ajout'] <= 86400}
    memoire_serveur["ports_accumules"] = ports_recents
    memoire_serveur["heure_dernier_scan"] = maintenant

# On transfère dans la session courante
st.session_state.crise_actuelle = memoire_serveur["crise_actuelle"]
st.session_state.donnees_ports = {"ports": list(memoire_serveur["ports_accumules"].values())}

# 🛑 CRÉATION DE L'ESPACE RÉSERVÉ POUR LE BANDEAU KPI
# On réserve la place en haut de l'écran, mais on le remplira plus tard !
bandeau_kpi_placeholder = st.empty()

onglets = st.tabs(["🌍 Radar Global & Chokepoints", "🚢 Suivi de Flotte", "📈 Marchés & Finance", "🌩️ Météo Extrême", "⚖️ Guerre Commerciale"])

# ==========================================
# ONGLET 1 : LE RADAR GLOBAL & CHOKEPOINTS
# ==========================================
with onglets[0]:
    col_gauche, col_droite = st.columns([2, 1])
    
    with col_gauche:
        st.markdown("### 📡 Fil d'Actualité Automatisé (OSINT)")
        st.markdown("<span style='font-size: 0.85em; color: #888;'>Mise à jour automatique toutes les heures.</span>", unsafe_allow_html=True)
        
        rapport = st.session_state.crise_actuelle
        if rapport:
            if rapport.get('chronologie_semaine'):
                for event in rapport['chronologie_semaine']:
                    st.info(f"🕒 **{event.get('date_heure', '')}** : {event.get('evenement', '')}  \n*(📰 {event.get('source', '')})*")

            if rapport.get('crise_detectee'):
                st.error(f"🚨 **{rapport.get('titre_alerte', '')}**")
                st.write(f"**Cible :** {rapport.get('nom_cible', '')}\n\n{rapport.get('resume_incident', '')}")
                if rapport.get('matieres_premieres_impactees'): st.write("**Matières :**", ", ".join(rapport['matieres_premieres_impactees']))
                st.write("**Impact Supply Chain :**", rapport.get('consequences_supply_chain', ''))
                st.success(f"**Analyse :**\n{rapport.get('recommandation_action', '')}")
                
                if st.session_state.est_premium:
                    pdf_bytes = generer_rapport_pdf(rapport)
                    st.download_button("📥 Télécharger le Rapport PDF", data=pdf_bytes, file_name="Report_Signal_Zero.pdf", mime="application/pdf", type="primary")
            else:
                st.success("✅ **Scan de routine :** Océans calmes.")
        else:
            st.warning("⚠️ Chargement des données satellitaires en cours...")

    with col_droite:
        st.markdown("### ⚓ Chokepoints (Status Live)")
        
        # 🧠 LA BASE DE DONNÉES TEMPORAIRE (Mise à jour toutes les heures !)
        @st.cache_data(ttl=3600) 
        def obtenir_donnees_chokepoints():
            actus = scanner_chokepoints_news()
            try:
                client = genai.Client(api_key=GEMINI_KEY)
                prompt_chk = f"""Tu es le moteur d'analyse d'un tableau de bord OSINT militaire. 
                Analyse ces données sur ces 13 points d'étranglement : Strait of Hormuz, Kerch Strait, Bab el-Mandeb, Suez Canal, Bosporus Strait, Taiwan Strait, Cape of Good Hope, Dover Strait, Strait of Malacca, Panama Canal, Strait of Gibraltar, Korea Strait, Lombok Strait.
                Actualités récentes : {actus}
                
                RÈGLES : 
                - Tu DOIS évaluer et lister CHACUN des 13 détroits, même si le trafic est totalement fluide.
                - Compte le nombre 'avertissements' (menaces) et 'perturbations' (blocages).
                - Donne un 'score' sur 100 : 0 = Fluide, 1-49 = Tensions, 50-79 = Perturbations, 80-100 = Attaque/Guerre.
                Rédige en {langue_choisie}."""
                res_chk = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_chk, config={'response_mime_type': 'application/json', 'response_schema': ListeChokepoints, 'temperature': 0.0})
                return json.loads(res_chk.text)
            except:
                return {"points": []}

        # On appelle la fonction (si elle a déjà tourné, elle recrache le résultat instantanément sans recalculer !)
        with st.spinner("🔄 Synchronisation des points d'étranglements en cours..."):
            chokepoints_data = obtenir_donnees_chokepoints()
        
        # AFFICHAGE HTML WORLD MONITOR
        if chokepoints_data and len(chokepoints_data.get('points', [])) > 0:
            # 📦 ON OUVRE LA BOÎTE AVEC LA MOLETTE DE DÉFILEMENT (550px de haut max)
            html_chokepoints = '<div style="max-height: 550px; overflow-y: auto; padding-right: 10px;">'
            
            for cp in chokepoints_data['points']:
                score = cp.get('score', 0)
                
                # 🎨 LOGIQUE STRICTE DES COULEURS
                if score >= 80:
                    color = "red"
                    status_text = "active"
                elif score >= 50:
                    color = "yellow"
                    status_text = "notified"
                else:
                    color = "green"
                    status_text = "terminated"
                    
                html_chokepoints += f"""<div class="trade-restriction-card">
<div class="trade-restriction-header">
<span class="trade-country">{cp.get('nom', 'N/A')}</span>
<span class="sc-status-dot sc-dot-{color}"></span>
<span class="trade-badge">{score}/100</span>
<span class="trade-status status-{status_text}">{color}</span>
</div>
<div class="trade-restriction-body">
<div class="trade-sector">{cp.get('avertissements', 0)} avertissement(s) · {cp.get('perturbations', 0)} Perturbation(s) AIS</div>
<div class="trade-description">{cp.get('description', '')}</div>
<div class="trade-affected">Affecte : {cp.get('impact', '')}</div>
</div>
</div>"""
                
            html_chokepoints += "</div>"
            
            st.markdown(html_chokepoints, unsafe_allow_html=True)
            st.markdown('<div style="text-align: right; margin-top: 5px;"><span style="font-size: 0.75em; color: #555;">Mise à jour : Toutes les heures</span></div>', unsafe_allow_html=True)

        # --- NOUVEAU MODULE : CONGESTION PORTUAIRE ---
        st.divider()
        st.markdown("### 🏗️ Alerte Congestion Portuaire")
        
        @st.cache_data(ttl=3600) # Mise à jour toutes les heures max
        def obtenir_donnees_ports():
            try:
                # 1. On fouille le web pour les retards portuaires
                actus_ports = DDGS().news("port congestion OR port strike OR terminal backlog OR maritime delays", max_results=15, timelimit='w')
                if not actus_ports: return {"ports": []}
                
                texte_actus = "".join([f"- {r['title']}: {r['body']}\n" for r in actus_ports])
                
                # 2. On demande à l'IA d'analyser la gravité
                client = genai.Client(api_key=GEMINI_KEY)
                prompt_ports = f"""Tu es un directeur logistique mondial et un cartographe expert. 
                Lis ces dépêches récentes : {texte_actus}
                Dresse la liste des PORTS COMMERCIAUX SPÉCIFIQUES qui subissent actuellement des congestions ou retards.
                
                RÈGLES STRICTES :
                1. INTERDIT de lister des régions vagues (comme 'Côte Est' ou 'Ports Chinois'). Donne le nom EXACT du port (ex: Port de Savannah, Port de Ningbo).
                2. Pour chaque port, tu DOIS fournir sa 'latitude' et 'longitude' exacte en format décimal. Cherche-les dans ta base de connaissances.
                3. Ne liste que les ports avec des problèmes réels mentionnés dans les dépêches.
                
                Rédige en {langue_choisie}."""
                
                res_ports = client.models.generate_content(
                    model='gemini-2.5-flash', 
                    contents=prompt_ports, 
                    config={'response_mime_type': 'application/json', 'response_schema': ListePortsCongestionnes, 'temperature': 0.1}
                )
                return json.loads(res_ports.text)
            except Exception:
                return {"ports": []}

        # On sauvegarde dans session_state pour que la carte y ait accès
        if 'donnees_ports' not in st.session_state: st.session_state.donnees_ports = None
        
        with st.spinner("Analyse du trafic portuaire mondial..."):
            st.session_state.donnees_ports = obtenir_donnees_ports()
            donnees_ports = st.session_state.donnees_ports
            
        if donnees_ports and donnees_ports.get('ports'):
            for port in donnees_ports['ports']:
                gravite = port.get('niveau_gravite', 'Modéré')
                # Code couleur selon la gravité
                icone = "🔴" if "Critique" in gravite else "🟠" if "Élevé" in gravite else "🟡"
                
                st.info(f"{icone} **{port.get('nom_port', '')} ({port.get('pays', '')})** \n*Cause :* {port.get('cause_delai', '')} | *Gravité :* **{gravite}**")
        else:
            st.success("✅ Aucun blocage portuaire majeur détecté par notre IA actuellement.")



# ==========================================
# ONGLET 2 : LE SUIVI DE FLOTTE & LOGISTIQUE
# ==========================================
with onglets[1]:
    # --- RECHERCHE IMO SIMPLE ---
    st.subheader(tr("🎯 Ciblage par Numéro IMO", "🎯 IMO Number Targeting", "🎯 Búsqueda por IMO", "🎯 IMO号码定位", "🎯 IMO नंबर खोजना"))
    col_search, col_btn = st.columns([3, 1])
    with col_search: imo_recherche = st.text_input("IMO", placeholder="Ex: 9903413")
    with col_btn: st.write(""); bouton_recherche = st.button(tr("🔍 Extraire", "🔍 Extract", "🔍 Extraer", "🔍 提取", "🔍 निकालें"), use_container_width=True)

    if bouton_recherche and imo_recherche:
        with st.status(f"Extraction IMO {imo_recherche}...", expanded=True) as status:
            try:
                url_cible = f"https://www.vesselfinder.com/vessels/details/{imo_recherche}"
                reponse = requests.get(url_cible, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                if reponse.status_code == 200:
                    soup = BeautifulSoup(reponse.text, 'html.parser')
                    
                    # 1️⃣ HACK GPS (Sécurisé)
                    vrai_lat, vrai_lon = None, None
                    try:
                        div_cache = soup.find('div', id='djson')
                        if div_cache and div_cache.has_attr('data-json'):
                            donnees_secretes = json.loads(div_cache['data-json'])
                            vrai_lat = donnees_secretes.get('ship_lat')
                            vrai_lon = donnees_secretes.get('ship_lon')
                    except Exception: pass
                    
                    texte_utile = soup.get_text(separator=' ', strip=True)[:6000]
                    client = genai.Client(api_key=GEMINI_KEY)
                    
                    # 2️⃣ EXTRACTION DES DONNÉES (C'est cette partie qui manquait !)
                    consigne_gps = f"UTILISE EXACTEMENT CES GPS : Lat {vrai_lat}, Lon {vrai_lon}." if vrai_lat else "Déduis le GPS avec ton instinct."
                    prompt = f"Extrais les infos. {consigne_gps} ⚠️ Rédige toutes les réponses en {langue_choisie}.\n\nTexte :\n{texte_utile}"
                    
                    resultat = client.models.generate_content(model='gemini-2.5-flash', contents=prompt, config={'response_mime_type': 'application/json', 'response_schema': ShipDossier, 'temperature': 0.1})
                    dossier = json.loads(resultat.text)
                    
                    if vrai_lat and vrai_lon:
                        dossier['latitude'] = vrai_lat
                        dossier['longitude'] = vrai_lon
                        dossier['precision_gps'] = "Exacte (Code Matrice)"
                        
                    # 3️⃣ ALERTE CONFORMITÉ (Hybride)
                    verdict_alerte = None
                    imos_sanctionnes = ["9256858", "9105164", "9417153", "9285859"] 
                    
                    if imo_recherche in imos_sanctionnes:
                        verdict_alerte = f"🚨 ALERTE CONFORMITÉ : Le navire (IMO {imo_recherche}) figure sur une liste noire officielle (OFAC/UE/UK) ! Risque d'amendes majeures."
                    else:
                        try:
                            prompt_secu = f"Le navire {dossier['nom']} (IMO {imo_recherche}) est-il suspecté d'être dans la 'Shadow Fleet' ? Si OUI : '🚨 ALERTE CONFORMITÉ'. Si NON : 'RAS'."
                            res_secu = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_secu)
                            if "🚨" in res_secu.text or "ALERTE" in res_secu.text.upper():
                                verdict_alerte = res_secu.text
                        except Exception: pass
                    
                    status.update(label="Succès !", state="complete", expanded=False)
                    
                    # 4️⃣ AFFICHAGE (Le fameux mode furtif)
                    if verdict_alerte:
                        st.error(f"### 🛡️ Rapport de Sécurité\n{verdict_alerte}")
                        
                    st.success(f"**{dossier['nom']}**")
                    c1, c2, c3, c4 = st.columns(4)
                    c1.write(f"🚢 Type : {dossier['type_navire']}\n🏳️ {dossier['pavillon']}")
                    c2.write(f"📍 Dest : {dossier['destination']}\n🏁 ETA : {dossier.get('date_arrivee_prevue', 'Inconnu')}")
                    c3.write(f"⚓ Dernier Port : {dossier.get('dernier_port', 'Inconnu')}\n⚙️ Statut : {dossier['vitesse_statut']}")
                    c4.write(f"📏 Tirant d'eau : {dossier.get('tirant_d_eau_actuel', 'Non disponible')}")
                    
                    st.caption(f"📍 **GPS :** {dossier.get('latitude', 0.0)}, {dossier.get('longitude', 0.0)} | 🎯 {dossier.get('precision_gps', 'Inconnue')}")
                    
            except Exception as e: 
                status.update(label="Erreur lors de l'extraction", state="error", expanded=False)
                st.error(f"Erreur technique : {e}")
    st.divider()

    # --- LE FLEET TRACKER (PREMIUM) ---
    st.subheader(tr("🚢 Suivi de Flotte Privée (PRO)", "🚢 Private Fleet Tracker (PRO)", "🚢 Rastreador de Flota (PRO)", "🚢 船队追踪器 (PRO)", "🚢 निजी बेड़ा ट्रैकर (PRO)"))
    col_flotte, col_btn_flotte = st.columns([3, 1])
    with col_flotte: imos_input = st.text_input("IMO (1, 2, 3...)", value="9811000, 9295842", key="flotte_input")
    with col_btn_flotte: st.write(""); bouton_flotte = st.button(tr("🛰️ Analyser la flotte", "🛰️ Analyze Fleet", "🛰️ Analizar Flota", "🛰️ 分析船队", "🛰️ बेड़े का विश्लेषण करें"), use_container_width=True)

    if bouton_flotte and imos_input:
        if not st.session_state.est_premium:
            st.warning("🔒 Le suivi simultané de flotte est réservé aux membres PRO.")
        else:
            liste_imos = [imo.strip() for imo in imos_input.split(',')]
            flotte_resultats = [] 
            with st.status("Analyse de la flotte en cours...", expanded=True) as status_flotte:
                for imo_cible in liste_imos:
                    try:
                        url_cible = f"https://www.vesselfinder.com/vessels/details/{imo_cible}"
                        reponse = requests.get(url_cible, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
                        if reponse.status_code == 200:
                            soup = BeautifulSoup(reponse.text, 'html.parser')
                            
                            # 🎯 LE HACK GPS "MATRIX" (POUR LA FLOTTE)
                            vrai_lat, vrai_lon = None, None
                            div_cache = soup.find('div', id='djson')
                            if div_cache and div_cache.has_attr('data-json'):
                                try:
                                    donnees_secretes = json.loads(div_cache['data-json'])
                                    vrai_lat = donnees_secretes.get('ship_lat')
                                    vrai_lon = donnees_secretes.get('ship_lon')
                                except: pass

                            texte_utile = soup.get_text(separator=' ', strip=True)[:6000]
                            client = genai.Client(api_key=GEMINI_KEY)
                            
                            date_du_jour = datetime.now().strftime("%Y-%m-%d %H:%M")
                            
                            consigne_gps = f"⚠️ BINGO SATELLITE : Coordonnées exactes interceptées : Latitude {vrai_lat}, Longitude {vrai_lon}. UTILISE STRICTEMENT CES CHIFFRES, et mets 'precision_gps' à 'Exacte (Détectée)'." if vrai_lat and vrai_lon else "⚠️ Applique la règle du Dead Reckoning."
                            
                            prompt_flotte = f"""Tu es un expert logistique. Aujourd'hui nous sommes le {date_du_jour}.
                            Extrais les infos de ce navire. Ne laisse AUCUN champ vide.
                            {consigne_gps}
                            ⚠️ Rédige tout en {langue_choisie}.
                            Texte brut : {texte_utile}"""
                            
                            resultat = client.models.generate_content(
                                model='gemini-2.5-flash', 
                                contents=prompt_flotte, 
                                config={'response_mime_type': 'application/json', 'response_schema': ShipDossier, 'temperature': 0.1}
                            )
                            
                            # 1️⃣ On sauvegarde le bateau dans la liste de la flotte
                            flotte_resultats.append(json.loads(resultat.text))
                            
                            # 2️⃣ LE FREIN TACTIQUE (3 secondes de pause pour éviter l'erreur 503)
                            st.caption(f"⏳ Temporisation anti-saturation après le navire {imo_cible}...")
                            time.sleep(3)
                            
                    except Exception as e:
                        st.error(f"Erreur sur le navire {imo_cible} : {e}")
                        
                status_flotte.update(label="Terminé !", state="complete", expanded=False)
            st.session_state.flotte_actuelle = flotte_resultats

   # AFFICHAGE DE LA FLOTTE (AVEC RADAR DE PROXIMITÉ DE CRISE)
    if st.session_state.flotte_actuelle:
        for navire in st.session_state.flotte_actuelle:
            # Code couleur de base : Vert (en mer) ou Orange (à quai)
            couleur = "🟠" if "moored" in navire.get('vitesse_statut', '').lower() or "anchor" in navire.get('vitesse_statut', '').lower() else "🟢"
            
            # 🚨 LE NOUVEAU SYSTÈME DE GESTION DES RISQUES
            alerte_proximite = ""
            distance_km = None
            if st.session_state.crise_actuelle and st.session_state.crise_actuelle.get('crise_detectee'):
                crise_lat = st.session_state.crise_actuelle.get('latitude', 0.0)
                crise_lon = st.session_state.crise_actuelle.get('longitude', 0.0)
                nav_lat = navire.get('latitude', 0.0)
                nav_lon = navire.get('longitude', 0.0)
                
                # Si le bateau a un GPS valide et qu'il y a une crise confirmée
                if crise_lat != 0.0 and nav_lat != 0.0:
                    distance_km = calculer_distance_gps(crise_lat, crise_lon, nav_lat, nav_lon)
                    if distance_km < 1000:  # Rayon de danger = 1000 km (Tu peux modifier cette valeur)
                        alerte_proximite = " ⚠️ EN ZONE DE DANGER !"
                        couleur = "🔴" # On force le voyant au rouge écarlate

            with st.expander(f"{couleur} {navire.get('nom', 'Inconnu')} (IMO: {navire.get('imo', '')}) - {navire.get('vitesse_statut', '')}{alerte_proximite}"):
                
                # Si le navire est dans la zone rouge, on affiche l'alerte !
                if alerte_proximite and distance_km is not None:
                    st.error(f"🚨 **ALERTE DE PROXIMITÉ :** Ce navire est estimé à environ **{int(distance_km)} km** de la zone de crise actuelle ({st.session_state.crise_actuelle.get('nom_cible', 'Inconnue')}).")

                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"📍 **Dest:** {navire.get('destination', 'Inconnue')}")
                c1.caption(f"🏁 **ETA:** {navire.get('date_arrivee_prevue', 'Inconnue')}")
                
                c2.write(f"⚓ **Dernier Port:** {navire.get('dernier_port', 'Inconnu')}")
                c2.caption(f"🛫 **Départ:** {navire.get('date_depart_dernier_port', 'Inconnue')}")
                
                c3.write(f"🚢 **Type:** {navire.get('type_navire', 'Inconnu')}")
                c3.write(f"🏳️ **Pavillon:** {navire.get('pavillon', 'Inconnu')}")
                
                c4.write(f"📏 **Tirant d'eau:** {navire.get('tirant_d_eau_actuel', 'Non dispo')}")
                st.caption(f"📍 GPS : {navire.get('latitude', 0.0)} , {navire.get('longitude', 0.0)} | 🎯 {navire.get('precision_gps', 'Inconnue')}")
    # --- EXPORT EXCEL / CSV DE LA FLOTTE (RESERVÉ PRO) ---
    if st.session_state.flotte_actuelle and st.session_state.est_premium:
        st.divider()
        st.markdown("### 📊 Export des données de la flotte")
        
        # On transforme la mémoire de l'app en tableau de données (DataFrame)
        df_flotte = pd.DataFrame(st.session_state.flotte_actuelle)
        
        # On sélectionne uniquement les colonnes utiles pour le client
        colonnes_a_garder = ['nom', 'imo', 'type_navire', 'pavillon', 'destination', 'date_arrivee_prevue', 'dernier_port', 'date_depart_dernier_port', 'vitesse_statut', 'latitude', 'longitude']
        df_propre = df_flotte[[c for c in colonnes_a_garder if c in df_flotte.columns]]
        
        # On convertit en CSV formaté pour l'Excel européen (séparateur point-virgule)
        csv_flotte = df_propre.to_csv(index=False, sep=';', encoding='utf-8-sig').encode('utf-8-sig')
        
        st.download_button(
            label="📥 Télécharger le Rapport (Excel/CSV)",
            data=csv_flotte,
            file_name=f"SignalZero_Fleet_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True,
            type="primary"
        )          

# ==========================================
# ONGLET 3 : MARCHÉS FINANCIERS
# ==========================================
with onglets[2]:
    st.markdown("### 📊 Impact Économique & Marchés")
    def afficher_cours_bourse(symbole, nom_affichage):
        try:
            historique = yf.Ticker(symbole).history(period="7d", interval="30m")
            if not historique.empty:
                st.write(f"**{nom_affichage}**")
                prix_min, prix_max = historique['Close'].min(), historique['Close'].max()
                marge = (prix_max - prix_min) * 0.1  
                fig = go.Figure(data=go.Scatter(x=historique.index, y=historique['Close'], mode='lines', line=dict(color='#00ffcc', width=2)))
                fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=150, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[prix_min - marge, prix_max + marge], showgrid=True, gridcolor='rgba(255,255,255,0.1)'), xaxis=dict(showgrid=False))
                st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
        except Exception: pass

    c_m1, c_m2, c_m3 = st.columns(3)
    with c_m1: afficher_cours_bourse("CL=F", "🛢️ Pétrole (WTI)")
    with c_m2: afficher_cours_bourse("NG=F", "🔥 Gaz Naturel")
    with c_m3: afficher_cours_bourse("ZW=F", "🌾 Blé")
    
    st.divider()
    c_m4, c_m5, c_m6 = st.columns(3)
    with c_m4: afficher_cours_bourse("MAERSK-B.CO", "A.P. Møller - Mærsk")
    with c_m5: afficher_cours_bourse("HLAG.DE", "Hapag-Lloyd")
    with c_m6: afficher_cours_bourse("ZIM", "ZIM Integrated Shipping")
    

# ==========================================
# ONGLET 4 : MÉTÉO EXTRÊME & ROUTAGE
# ==========================================
with onglets[3]:
    st.markdown("### 🌩️ Climat & Conditions Océaniques")
    
    # 1️⃣ Calcul du centre de gravité de la flotte
    centre_lat, centre_lon = 20.0, 0.0
    zoom_meteo = 300 # Zoom mondial par défaut
    
    if st.session_state.flotte_actuelle:
        lats = [nav['latitude'] for nav in st.session_state.flotte_actuelle if nav.get('latitude', 0.0) != 0.0]
        lons = [nav['longitude'] for nav in st.session_state.flotte_actuelle if nav.get('longitude', 0.0) != 0.0]
        
        if lats and lons:
            # On fait la moyenne des GPS pour centrer la caméra au milieu de la flotte
            centre_lat = sum(lats) / len(lats)
            centre_lon = sum(lons) / len(lons)
            zoom_meteo = 800 # On zoome puissamment car on a une cible précise !
            st.success(f"🎯 Radar météo braqué sur votre flotte (Lat: {centre_lat:.2f}, Lon: {centre_lon:.2f})")
        else:
            st.info("ℹ️ Aucun GPS valide trouvé dans la flotte. Vue globale affichée.")
    else:
        st.info("ℹ️ Analysez une flotte dans l'Onglet 2 pour que le satellite météo se centre automatiquement dessus !")

    # 2️⃣ Interface B2B (Filtres et Projection)
    c_meteo1, c_meteo2 = st.columns([1, 3])
    
    with c_meteo1:
        st.markdown("#### ⚙️ Réglages Satellite")
        calque_meteo = st.radio("Filtre d'Analyse :", ("💨 Vents (Surface)", "🌊 Vagues (Houle)", "🌀 Courants (Océan)"))
        type_vue = st.selectbox("Projection :", ("Globe 3D (Orthographique)", "Carte 2D (Équirectangulaire)"))
    
    projection = "orthographic" if "3D" in type_vue else "equirectangular"

    # 3️⃣ Construction de l'URL Dynamique (Correction du Centrage et du Curseur)
    if "Vents" in calque_meteo: 
        base_url = "https://earth.nullschool.net/#current/wind/surface/level"
    elif "Vagues" in calque_meteo: 
        base_url = "https://earth.nullschool.net/#current/ocean/primary/waves/overlay=significant_wave_height"
    else: 
        base_url = "https://earth.nullschool.net/#current/ocean/surface/currents/overlay=currents"
        
    # Ajustement du zoom selon la vue (la 3D a besoin d'un chiffre plus grand pour zoomer)
    vrai_zoom = 800 if "3D" in type_vue else 500
    if not st.session_state.flotte_actuelle:
        vrai_zoom = 300 # Dézoom global si on n'a pas de flotte
        
    # L'URL magique avec "loc=" pour poser un curseur clignotant sur la cible !
    url_carte = f"{base_url}/{projection}={centre_lon:.2f},{centre_lat:.2f},{vrai_zoom}/loc={centre_lon:.2f},{centre_lat:.2f}"
    
    with c_meteo2:
        components.html(f"""
        <iframe width="100%" height="550" src="{url_carte}" frameborder="0" 
        style="border-radius: 8px; border: 1px solid #444; box-shadow: 0 4px 8px rgba(0,0,0,0.5);">
        </iframe>
        """, height=550)

# ==========================================
# ONGLET 5 : GUERRE COMMERCIALE & POLITIQUES
# ==========================================
with onglets[4]:
    st.markdown("### ⚖️ Renseignement Douanier & Politiques Commerciales")
    col_gta, col_macmap = st.columns([2, 1])
    
    with col_gta:
        st.markdown("#### 🚨 Radar Type 'Global Trade Alert' (IA)")
        if st.button("⚖️ Lancer le Scan des Sanctions (24h)", type="primary", use_container_width=True):
            if not st.session_state.est_premium:
                st.warning("🔒 Le scan des guerres commerciales est une fonction PRO.")
            else:
                with st.status("Recherche de nouvelles barrières commerciales...", expanded=True) as status_trade:
                    try:
                        trade_news = DDGS().news("export ban OR new import tariff OR trade sanctions OR WTO dispute OR customs duty", max_results=10, timelimit='d')
                        if trade_news:
                            texte_trade = "\n".join([f"- {r['title']} : {r['body']}" for r in trade_news])
                            client = genai.Client(api_key=GEMINI_KEY)
                            prompt_trade = f"""Tu es un expert de l'OMC. Lis ces dépêches : {texte_trade}
                            Identifie UNIQUEMENT les NOUVELLES mesures d'état (Taxes, Embargos, Sanctions).
                            S'il n'y a rien de nouveau aujourd'hui, dis simplement 'Aucune nouvelle mesure protectionniste majeure détectée aujourd'hui.' Rédige en {langue_choisie}."""
                            resultat_trade = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_trade, config={'temperature': 0.1})
                            st.info(f"**Analyse OSINT du jour :**\n\n{resultat_trade.text}")
                            status_trade.update(label="Analyse Trade Terminée", state="complete", expanded=False)
                        else:
                            st.success("Aucune guerre commerciale détectée dans la presse ces dernières 24h.")
                            status_trade.update(label="Terminé", state="complete", expanded=False)
                    except Exception as e:
                        st.error(f"Erreur du scanner : {e}")

    with col_macmap:
        st.markdown("#### 🛂 Simulateur de Douane (Expert IA)")
        st.markdown("<span style='font-size: 0.9em; color: #888;'>Les taxes dépendent des accords bilatéraux. Définissez la route :</span>", unsafe_allow_html=True)
        
        c_orig, c_dest = st.columns(2)
        with c_orig: pays_origine = st.text_input("🌍 Pays d'Origine :", placeholder="ex: Chine, France...")
        with c_dest: pays_destination = st.text_input("🎯 Pays de Destination :", placeholder="ex: USA, Brésil...")
        
        produits_phares = [
            "⚡ Véhicules Électriques (EV)", 
            "💻 Semi-conducteurs / Puces", 
            "🌾 Blé agricole", 
            "🛢️ Pétrole Brut",
            "Autre (Précisez manuellement)"
        ]
        choix_produit = st.selectbox("📦 Marchandise :", produits_phares)
        
        produit_final = choix_produit
        if "Autre" in choix_produit:
            produit_final = st.text_input("Nom de la marchandise :", placeholder="ex: Acier, Panneaux solaires...")

        if st.button("⚖️ Analyser les Taxes et Sanctions", use_container_width=True):
            if not pays_origine or not pays_destination:
                st.warning("⚠️ Veuillez indiquer un pays d'origine et de destination.")
            else:
                with st.spinner("Analyse des traités de l'OMC et des guerres commerciales en cours..."):
                    try:
                        client = genai.Client(api_key=GEMINI_KEY)
                        prompt_douane = f"""Tu es un expert en douane internationale et géopolitique commerciale.
                        Un logisticien veut exporter la marchandise suivante : '{produit_final}'
                        Depuis : {pays_origine}
                        Vers : {pays_destination}
                        
                        MISSION :
                        1. Donne une estimation du taux de droits de douane habituel (ou Clause de la Nation la plus favorisée).
                        2. Surtout, alerte le client s'il y a une GUERRE COMMERCIALE, un EMBARGO, ou des surtaxes récentes (ex: taxes anti-dumping) sur cet axe précis.
                        3. Reste ultra-concis, factuel, format B2B. Pas de grandes phrases.
                        Rédige en {langue_choisie}."""
                        
                        res_douane = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_douane, config={'temperature': 0.2})
                        st.info(f"**Analyse Douanière ({pays_origine} ➡️ {pays_destination}) :**\n\n{res_douane.text}")
                    except Exception as e:
                        st.error(f"Erreur d'analyse : {e}")
    # --- RADAR AUTOMATISÉ DES BARRIÈRES DOUANIÈRES (OMC / OSINT) ---
    st.divider()
    st.markdown("### 🌾 Indice Mondial du Protectionnisme")
    st.markdown("<span style='font-size: 0.85em; color: #888;'>Actualisé via les rapports OMC et l'OSINT douanier.</span>", unsafe_allow_html=True)
    
    # Cache de 24h (86400 secondes) car les taxes d'état ne changent pas toutes les heures !
    @st.cache_data(ttl=86400) 
    def obtenir_donnees_wto():
        try:
            # L'agent cherche les rapports récents sur les tarifs douaniers (OMC/WTO)
            recherche_wto = DDGS().text("WTO agricultural non-agricultural tariff gaps protectionism ranking country", max_results=10)
            texte_wto = "\n".join([f"- {r['title']} : {r['body']}" for r in recherche_wto])
            
            client = genai.Client(api_key=GEMINI_KEY)
            prompt_wto = f"""Tu es un analyste macro-économique de l'OMC. Lis ces extraits de rapports : {texte_wto}
            Dresse la liste des 5 à 6 pays avec les plus fortes barrières douanières ou écarts de taxes (notamment agricoles).
            Si tu manques de données dans le texte, utilise tes connaissances internes fiables sur les tarifs douaniers moyens de l'OMC (ex: Inde, Corée du Sud, etc.).
            Rédige en {langue_choisie}."""
            
            res_wto = client.models.generate_content(
                model='gemini-2.5-flash', 
                contents=prompt_wto, 
                config={'response_mime_type': 'application/json', 'response_schema': ListeTradeBarriers, 'temperature': 0.1}
            )
            return json.loads(res_wto.text)
        except Exception:
            return {"barriers": []}

    with st.spinner("Synchronisation avec les bases de données tarifaires mondiales..."):
        donnees_wto = obtenir_donnees_wto()

    # --- AFFICHAGE DYNAMIQUE STREAMLIT ---
    if donnees_wto and donnees_wto.get('barriers'):
        # On affiche les pays sous forme de jolies cartes "Metrics"
        colonnes_wto = st.columns(3) # On fait 3 colonnes par ligne
        
        for index, barrier in enumerate(donnees_wto['barriers']):
            col_actuelle = colonnes_wto[index % 3] # On répartit dans les colonnes
            
            with col_actuelle:
                # Couleur selon le niveau de protection
                couleur_statut = "🔴" if "Haut" in barrier.get('niveau_protection', '') or "High" in barrier.get('niveau_protection', '') else "🟠"
                
                with st.container(border=True):
                    st.markdown(f"**{couleur_statut} {barrier.get('pays', 'Inconnu')}**")
                    st.metric(label=barrier.get('secteur_concerne', 'Secteur'), value=barrier.get('ecart_taxe', 'N/A'), delta=barrier.get('niveau_protection', ''), delta_color="inverse")
                    st.caption(f"{barrier.get('resume', '')}")
    else:
        st.info("Données tarifaires temporairement indisponibles.") 

# ==========================================
# LA CARTE FOLIUM UNIFIÉE (RADAR STRATÉGIQUE)
# ==========================================
st.divider()
st.subheader("🚨 Radar Stratégique Unifié")

centre_lat, centre_lon, zoom = 20.0, 0.0, 2

if st.session_state.crise_actuelle and st.session_state.crise_actuelle.get('crise_detectee'):
    centre_lat, centre_lon, zoom = st.session_state.crise_actuelle.get('latitude', 20.0), st.session_state.crise_actuelle.get('longitude', 0.0), 4
elif st.session_state.flotte_actuelle and len(st.session_state.flotte_actuelle) > 0:
    for navire in st.session_state.flotte_actuelle:
        if navire.get('latitude', 0.0) != 0.0:
            centre_lat, centre_lon, zoom = navire['latitude'], navire['longitude'], 3; break

carte_monde = folium.Map(location=[centre_lat, centre_lon], zoom_start=zoom, tiles="CartoDB dark_matter")

if st.session_state.crise_actuelle and st.session_state.crise_actuelle.get('crise_detectee'): 
    folium.Marker(
        [st.session_state.crise_actuelle['latitude'], st.session_state.crise_actuelle['longitude']], 
        popup=f"<b>{st.session_state.crise_actuelle['nom_cible']}</b>", 
        icon=folium.Icon(color="red", icon="warning", prefix='fa')
    ).add_to(carte_monde)

if st.session_state.flotte_actuelle:
    for navire in st.session_state.flotte_actuelle:
        if navire.get('latitude', 0.0) != 0.0 and navire.get('longitude', 0.0) != 0.0: 
            folium.Marker(
                [navire['latitude'], navire['longitude']], 
                popup=f"<b>{navire.get('nom', 'Inconnu')}</b>", 
                tooltip=f"🚢 {navire.get('nom', 'Inconnu')}", 
                icon=folium.Icon(color="blue", icon="ship", prefix='fa')
            ).add_to(carte_monde)

# --- AJOUT DES PORTS CONGESTIONNÉS SUR LA CARTE ---
if st.session_state.get('donnees_ports') and st.session_state.donnees_ports.get('ports'):
    for port in st.session_state.donnees_ports['ports']:
        lat = port.get('latitude', 0.0)
        lon = port.get('longitude', 0.0)
        
        # Si l'IA a bien trouvé le GPS
        if lat != 0.0 and lon != 0.0:
            gravite = port.get('niveau_gravite', 'Modéré')
            # Couleur dynamique : Rouge = Critique, Orange = Élevé, Beige = Modéré
            couleur_marqueur = "red" if "Critique" in gravite else "orange" if "Élevé" in gravite else "beige"
            
            # Le texte qui s'affichera au clic sur le port
            popup_texte = f"<b>🏗️ {port.get('nom_port')} ({port.get('pays')})</b><br><i>{port.get('cause_delai')}</i><br><b>Gravité:</b> {gravite}"
            
            folium.Marker(
                [lat, lon],
                popup=popup_texte,
                tooltip=f"⚠️ Congestion: {port.get('nom_port')}",
                icon=folium.Icon(color=couleur_marqueur, icon="anchor", prefix='fa')
            ).add_to(carte_monde)
st_folium(carte_monde, height=500, use_container_width=True)

st.subheader(tr("📡 Radar AIS Mondial", "📡 Global AIS Radar", "📡 Radar AIS Global", "📡 全球 AIS 雷达", "📡 ग्लोबल एआईएस रडार"))
components.html("""<script type="text/javascript">width="100%";height="500";names=true;lat="25.2";lon="55.3";zoom="5";maptype="3";trackvessel="0";fleet="";</script><script type="text/javascript" src="https://www.vesselfinder.com/aismap.js"></script>""", height=500)
st.divider()

# ==========================================
# AFFICHAGE DU BANDEAU DE MÉTRIQUES (Remplissage de l'espace réservé en haut)
# ==========================================
with bandeau_kpi_placeholder.container():
    # 1. On compte les éléments en direct (après que tout le code ait tourné)
    nb_navires = len(st.session_state.get('flotte_actuelle', [])) if st.session_state.get('flotte_actuelle') else 0
    nb_crises = 1 if st.session_state.get('crise_actuelle') and st.session_state.crise_actuelle.get('crise_detectee') else 0
    
    donnees_ports = st.session_state.get('donnees_ports', {})
    liste_ports = donnees_ports.get('ports', [])
    nb_ports_bloques = len(liste_ports)

    # 2. On dessine les colonnes
    col_kpi1, col_kpi2, col_kpi3, col_kpi4 = st.columns(4)
    with col_kpi1: st.metric(label="🚢 Flotte Surveillée", value=nb_navires)
    with col_kpi2: st.metric(label="🚨 Crises Majeures", value=nb_crises, delta="- Risque" if nb_crises > 0 else "Océans Calmes", delta_color="inverse")
    with col_kpi3: st.metric(label="🏗️ Ports Bloqués", value=nb_ports_bloques, delta=f"{nb_ports_bloques} alertes/24h" if nb_ports_bloques > 0 else "Fluide", delta_color="inverse")
    with col_kpi4: st.metric(label="💎 Statut Licence", value="PRO (VIP)" if st.session_state.est_premium else "Standard")
    
    st.markdown("<br>", unsafe_allow_html=True)