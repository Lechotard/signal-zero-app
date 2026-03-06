import streamlit as st
import os
import json
import requests
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

# --- CONFIGURATION DE LA PAGE ---
st.set_page_config(page_title="Signal Zero - Sentinelle", page_icon="🌍", layout="wide", initial_sidebar_state="collapsed")

load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# --- LA MÉMOIRE DE LA PAGE ET COMPTEUR FREEMIUM ---
if 'crise_actuelle' not in st.session_state: st.session_state.crise_actuelle = None
if 'flotte_actuelle' not in st.session_state: st.session_state.flotte_actuelle = []
if 'meteo_actuelle' not in st.session_state: st.session_state.meteo_actuelle = None
if 'scans_utilises' not in st.session_state: st.session_state.scans_utilises = 0
if 'est_premium' not in st.session_state: st.session_state.est_premium = False

# --- SÉLECTION DE LA LANGUE & MODE ADMIN (SIDEBAR) ---
st.sidebar.title("⚙️ Paramètres / Settings")
langue_choisie = st.sidebar.selectbox("🌐 Langue du système :", ("Français", "English", "Español", "中文 (Chinois)", "हिन्दी (Hindi)"))

st.sidebar.divider()
st.sidebar.markdown("### 🔑 Accès VIP / Admin")
# Le client tape le code, les lettres sont cachées par des petits points (type="password")
code_admin = st.sidebar.text_input("Code d'activation PRO :", type="password")

# LE CADENAS : Si le code tapé est "CEO2026" (tu peux changer ce mot de passe !)
if code_admin == "CEO2026":
    st.session_state.est_premium = True
    st.sidebar.success("💎 Mode Premium Déverrouillé !")
    
    # Ton bouton de remise à zéro n'apparaît QUE si le mot de passe est bon
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

# --- LES MOULES DE DONNÉES SÉCURISÉS ---
class TimelineEvent(BaseModel):
    date_heure: str = Field(..., description="Date ET Heure de l'info")
    evenement: str = Field(..., description="Résumé de l'événement")
    source: str = Field(..., description="Nom du média")

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
    type_navire: str = Field(..., description="Type de navire. Mets 'Inconnu' si introuvable.")
    pavillon: str = Field(..., description="Pays d'enregistrement. Mets 'Inconnu' si introuvable.")
    destination: str = Field(..., description="Destination. Mets 'Inconnue' si introuvable.")
    vitesse_statut: str = Field(..., description="Vitesse/Statut. Mets 'Inconnu' si introuvable.")
    details_techniques: str = Field(..., description="Détails techniques. Mets 'Inconnu' si introuvable.")
    historique_recent: str = Field(..., description="Historique. Mets 'Inconnu' si introuvable.")
    latitude: float = Field(..., description="Latitude GPS. Obligatoire. Devine-la si nécessaire.")
    longitude: float = Field(..., description="Longitude GPS. Obligatoire. Devine-la si nécessaire.")
    tirant_d_eau_actuel: str = Field(..., description="Tirant d'eau. Mets 'Non disponible' si introuvable.")

class WeatherAlert(BaseModel):
    titre: str = Field(...)
    description: str = Field(...)
    latitude: float = Field(...)
    longitude: float = Field(...)

class WeatherReport(BaseModel):
    alertes: list[WeatherAlert] = Field(...)

# --- L'AGENT VEILLEUR ---
def scanner_actualites_maritimes():
    mots_cles = "cargo ship grounded OR tanker blocked OR port strike OR shipping disrupted OR vessel hijacked OR maritime collision OR cargo fire OR port congestion OR canal drought OR supply chain bottleneck OR Red Sea shipping OR piracy attack"
    try:
        resultats = DDGS().news(mots_cles, max_results=15, timelimit='w')
        if not resultats: return ""
        texte_propre = ""
        for article in resultats:
            date_brute = article.get('date', 'Date inconnue')
            date_nettoyee = date_brute.replace('T', ' ')[:19] 
            source = article.get('source', 'Inconnue')
            texte_propre += f"Titre: {article['title']}\nSource: {source}\nDate: {date_nettoyee}\nRésumé: {article['body']}\n---\n"
        return texte_propre
    except Exception:
        return ""

# --- L'INTERFACE UTILISATEUR ---
st.title(tr("🌍 Signal Zero : Centre de Commandement", "🌍 Signal Zero: Command Center", "🌍 Signal Zero: Centro de Mando", "🌍 Signal Zero：指挥中心", "🌍 सिग्नल ज़ीरो: कमांड सेंटर"))

# --- RADAR IA DES CRISES (FREEMIUM) ---
titre_btn_scan = tr("📡 Lancer le Scan Mondial des Crises", "📡 Launch Global Crisis Scan", "📡 Iniciar Escaneo Global", "📡 启动全球危机扫描", "📡 ग्लोबल क्राइसिस स्कैन शुरू करें")

if st.button(titre_btn_scan, type="primary", use_container_width=True):
    if st.session_state.scans_utilises >= 1 and not st.session_state.est_premium:
        st.error(tr("🔒 Vous avez utilisé votre scan gratuit de la journée.", "🔒 Free daily scan limit reached.", "🔒 Límite de escaneo diario alcanzado.", "🔒 免费扫描次数已用完。", "🔒 दैनिक निःशुल्क स्कैन सीमा समाप्त।"))
        st.info(tr("Passez à Signal Zero PRO pour débloquer les scans illimités, le suivi de flotte et les rapports PDF.", "Upgrade to PRO for unlimited scans, fleet tracking, and PDF reports.", "Mejora a PRO para escaneos ilimitados, rastreo de flota y PDFs.", "升级至 PRO 获取无限扫描、船队追踪和 PDF 报告。", "असीमित स्कैन, बेड़े ट्रैकिंग और पीडीएफ रिपोर्ट के लिए PRO में अपग्रेड करें।"))
        st.link_button(tr("💎 S'abonner (7 jours d'essai)", "💎 Subscribe (7-day trial)", "💎 Suscribirse (7 días gratis)", "💎 订阅 (7天免费试用)", "💎 सदस्यता लें (7 दिन निःशुल्क)"), "https://buy.stripe.com/bJefZg4LAfTP1NO1RWdwc00")
    else:
        st.session_state.scans_utilises += 1 
        with st.status(tr("Analyse en cours...", "Analyzing...", "Analizando...", "分析中...", "विश्लेषण हो रहा है..."), expanded=True) as status:
            actualites = scanner_actualites_maritimes()
            if actualites:
                try:
                    client = genai.Client(api_key=GEMINI_KEY)
                    prompt = f"""Tu es un analyste géopolitique et financier stratégique. Lis ces dépêches :
                    {actualites}
                    MISSION 1 : Crée un récapitulatif chronologique ('chronologie_semaine'). Précise la DATE ET L'HEURE EXACTE et la SOURCE pour chaque événement. Transforme la date en format lisible (ex: '04 Mars à 19h10').
                    MISSION 2 : Y a-t-il un incident maritime GRAVE en cours ? Si OUI, mets 'crise_detectee' à True.
                    IMPORTANT : Dans 'recommandation_action', rédige ton analyse de risques à COURT et MOYEN TERME comme un analyste financier et un geopoliticien sur les implications géopolitiques et financières.
                    ⚠️ Rédige ABSOLUMENT TOUTE ta réponse en {langue_choisie}.
                    """
                    resultat = client.models.generate_content(model='gemini-2.5-flash', contents=prompt, config={'response_mime_type': 'application/json', 'response_schema': CrisisAlert, 'temperature': 0.1})
                    st.session_state.crise_actuelle = json.loads(resultat.text)
                    status.update(label="Terminé !", state="complete", expanded=False)
                except Exception as e:
                    st.error(f"Erreur d'analyse : {e}")

if not st.session_state.est_premium:
    st.caption(f"Scans gratuits utilisés aujourd'hui : {st.session_state.scans_utilises} / 1")

# --- RADAR AIS LIVE ---
st.subheader(tr("📡 Radar AIS Mondial", "📡 Global AIS Radar", "📡 Radar AIS Global", "📡 全球 AIS 雷达", "📡 ग्लोबल एआईएस रडार"))
components.html("""<script type="text/javascript">width="100%";height="500";names=true;lat="25.2";lon="55.3";zoom="5";maptype="3";trackvessel="0";fleet="";</script><script type="text/javascript" src="https://www.vesselfinder.com/aismap.js"></script>""", height=500)
st.divider()

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
                texte_utile = soup.get_text(separator=' ', strip=True)[:6000]
                client = genai.Client(api_key=GEMINI_KEY)
                prompt = f"Extrais les infos. Déduis le GPS. ⚠️ Rédige toutes les réponses en {langue_choisie}.\n\nTexte :\n{texte_utile}"
                resultat = client.models.generate_content(model='gemini-2.5-flash', contents=prompt, config={'response_mime_type': 'application/json', 'response_schema': ShipDossier, 'temperature': 0.1})
                dossier = json.loads(resultat.text)
                status.update(label="Succès !", state="complete", expanded=False)
                
                st.success(f"**{dossier['nom']}**")
                c1, c2, c3, c4 = st.columns(4)
                c1.write(f"🚢 Type : {dossier['type_navire']}\n🏳️ {dossier['pavillon']}")
                c2.write(f"📍 Dest : {dossier['destination']}\n⚙️ Statut : {dossier['vitesse_statut']}")
                c3.write(f"📏 Tech : {dossier['details_techniques']}")
                c4.write(f"⚓ Tirant d'eau : {dossier.get('tirant_d_eau_actuel', 'Non disponible')}")
        except Exception as e: st.error(f"Erreur : {e}")
st.divider()

# --- LE FLEET TRACKER (PREMIUM) ---
st.subheader(tr("🚢 Suivi de Flotte Privée (PRO)", "🚢 Private Fleet Tracker (PRO)", "🚢 Rastreador de Flota (PRO)", "🚢 船队追踪器 (PRO)", "🚢 निजी बेड़ा ट्रैकर (PRO)"))
col_flotte, col_btn_flotte = st.columns([3, 1])
with col_flotte: imos_input = st.text_input("IMO (1, 2, 3...)", value="9811000, 9463061", key="flotte_input")
with col_btn_flotte: st.write(""); bouton_flotte = st.button(tr("🛰️ Analyser la flotte", "🛰️ Analyze Fleet", "🛰️ Analizar Flota", "🛰️ 分析船队", "🛰️ बेड़े का विश्लेषण करें"), use_container_width=True)

if bouton_flotte and imos_input:
    if not st.session_state.est_premium:
        st.warning(tr("🔒 Le suivi simultané de flotte est réservé aux membres PRO.", "🔒 Simultaneous fleet tracking is a PRO feature.", "🔒 El rastreo simultáneo es una función PRO.", "🔒 同步船队追踪是 PRO 功能。", "🔒 एक साथ बेड़े की ट्रैकिंग एक PRO सुविधा है।"))
        st.link_button(tr("💎 S'abonner pour débloquer", "💎 Subscribe to unlock", "💎 Suscríbete para desbloquear", "💎 订阅解锁", "💎 अनलॉक करने के लिए सदस्यता लें"), "https://buy.stripe.com/bJefZg4LAfTP1NO1RWdwc00")
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
                        texte_utile = soup.get_text(separator=' ', strip=True)[:6000]
                        client = genai.Client(api_key=GEMINI_KEY)
                        
                        # LE FAMEUX PROMPT STRICT POUR FORCER LE GPS ET LES DONNÉES !
                        prompt_flotte = f"""Tu es un expert logistique. Extrais les infos de ce navire.
                        ⚠️ RÈGLE 1 : Ne laisse AUCUN champ vide. S'il manque une info, écris "Non disponible".
                        ⚠️ RÈGLE 2 (GPS) : Utilise tes connaissances pour déduire une Latitude et Longitude approximatives selon le port ou la mer mentionnée.
                        ⚠️ Rédige tout en {langue_choisie}.
                        Texte brut : {texte_utile}"""
                        
                        resultat = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_flotte, config={'response_mime_type': 'application/json', 'response_schema': ShipDossier, 'temperature': 0.1})
                        flotte_resultats.append(json.loads(resultat.text))
                except Exception as e:
                    st.error(f"Erreur sur le navire {imo_cible} : {e}")
            status_flotte.update(label="Terminé !", state="complete", expanded=False)
        st.session_state.flotte_actuelle = flotte_resultats

# AFFICHAGE DE LA FLOTTE
if st.session_state.flotte_actuelle:
    for navire in st.session_state.flotte_actuelle:
        couleur = "🟠" if "moored" in navire['vitesse_statut'].lower() or "anchor" in navire['vitesse_statut'].lower() else "🟢"
        with st.expander(f"{couleur} {navire['nom']} (IMO: {navire['imo']}) - {navire['vitesse_statut']}"):
            c1, c2, c3, c4 = st.columns(4)
            c1.write(f"**Dest:** {navire['destination']}")
            c2.write(f"**Type:** {navire['type_navire']}")
            c3.write(f"**Pavillon:** {navire['pavillon']}")
            c4.write(f"**Tirant d'eau:** {navire.get('tirant_d_eau_actuel', 'Non disponible')}")
            # On vérifie visuellement le GPS !
            st.caption(f"📍 GPS (~)  : {navire.get('latitude', 0.0)} , {navire.get('longitude', 0.0)}")

st.divider()

# --- CARTE INTERACTIVE FOLIUM (Radar Unifié) ---
st.subheader(tr("🚨 Focus GPS : Radar Stratégique", "🚨 GPS Focus: Strategic Radar", "🚨 Enfoque GPS: Radar Estratégico", "🚨 GPS焦点：战略雷达", "🚨 जीपीएस फोकस: रणनीतिक रडार"))
centre_lat, centre_lon, zoom = 20.0, 0.0, 2

if st.session_state.crise_actuelle and st.session_state.crise_actuelle.get('crise_detectee'):
    centre_lat, centre_lon, zoom = st.session_state.crise_actuelle.get('latitude', 20.0), st.session_state.crise_actuelle.get('longitude', 0.0), 4
elif st.session_state.flotte_actuelle and len(st.session_state.flotte_actuelle) > 0:
    for navire in st.session_state.flotte_actuelle:
        if navire.get('latitude', 0.0) != 0.0:
            centre_lat, centre_lon, zoom = navire['latitude'], navire['longitude'], 3; break

carte_monde = folium.Map(location=[centre_lat, centre_lon], zoom_start=zoom, tiles="CartoDB dark_matter")
if st.session_state.crise_actuelle and st.session_state.crise_actuelle.get('crise_detectee'): folium.Marker([st.session_state.crise_actuelle['latitude'], st.session_state.crise_actuelle['longitude']], popup=f"<b>{st.session_state.crise_actuelle['nom_cible']}</b>", icon=folium.Icon(color="red", icon="warning", prefix='fa')).add_to(carte_monde)

# ⚓ DESSIN DES BATEAUX SUR LA CARTE
if st.session_state.flotte_actuelle:
    for navire in st.session_state.flotte_actuelle:
        if navire.get('latitude', 0.0) != 0.0 and navire.get('longitude', 0.0) != 0.0: 
            folium.Marker([navire['latitude'], navire['longitude']], popup=f"<b>{navire['nom']}</b>", tooltip=f"🚢 {navire['nom']}", icon=folium.Icon(color="blue", icon="ship", prefix='fa')).add_to(carte_monde)

if st.session_state.meteo_actuelle and st.session_state.meteo_actuelle.get('alertes'):
    for alerte in st.session_state.meteo_actuelle['alertes']: folium.Marker([alerte['latitude'], alerte['longitude']], popup=f"<b>{alerte['titre']}</b>", tooltip=f"🌪️ {alerte['titre']}", icon=folium.Icon(color="orange", icon="cloud", prefix='fa')).add_to(carte_monde)

st_folium(carte_monde, height=450, use_container_width=True)
st.divider()

# --- RAPPORT D'ANALYSE & CHRONOLOGIE ---
if st.session_state.crise_actuelle:
    rapport = st.session_state.crise_actuelle
    st.subheader(tr("⏱️ Fil d'Actualité", "⏱️ News Timeline", "⏱️ Línea de Tiempo", "⏱️ 新闻时间轴", "⏱️ समाचार टाइमलाइन"))
    for event in rapport.get('chronologie_semaine', []):
        date_a_afficher = event.get('date_heure', 'Heure inconnue')
        source_a_afficher = event.get('source', 'Média inconnu')
        st.info(f"🕒 **{date_a_afficher}** : {event['evenement']}  \n*(📰 Source : {source_a_afficher})*")
        
    if rapport.get('crise_detectee'):
        st.error(f"🚨 **{rapport['titre_alerte']}**")
        st.write(f"**Cible :** {rapport['nom_cible']}\n\n{rapport['resume_incident']}")
        st.write("**Impact Supply Chain :**", rapport['consequences_supply_chain'])
        st.success(f"**Analyse financier & géopolitique (Court/Moyen) :**\n{rapport['recommandation_action']}")
        
        if st.session_state.est_premium:
            pdf_bytes = generer_rapport_pdf(rapport)
            st.download_button(label="📥 Download PDF", data=pdf_bytes, file_name="Report.pdf", mime="application/pdf", type="primary")
        else:
            st.warning(tr("🔒 L'export de rapports PDF est une fonctionnalité PRO.", "🔒 PDF report export is a PRO feature.", "🔒 La exportación de informes PDF es una función PRO.", "🔒 PDF 报告导出是 PRO 功能。", "🔒 पीडीएफ रिपोर्ट निर्यात एक PRO सुविधा है।"))
            st.link_button(tr("💎 S'abonner pour débloquer le PDF", "💎 Subscribe to unlock PDF", "💎 Suscríbete para desbloquear PDF", "💎 订阅解锁 PDF", "💎 पीडीएफ अनलॉक करने के लिए सदस्यता लें"), "https://buy.stripe.com/bJefZg4LAfTP1NO1RWdwc00")

st.divider()

# --- MÉTÉO PURE (PREMIUM) ---
st.subheader(tr("🌩️ Météo Extrême (PRO)", "🌩️ Extreme Weather (PRO)", "🌩️ Clima Extremo (PRO)", "🌩️ 极端天气 (PRO)", "🌩️ चरम मौसम (PRO)"))
calque_meteo = st.selectbox("", ("💨 Vents", "🌊 Vagues", "🌀 Courants"))
if "Vents" in calque_meteo: url_carte = "https://earth.nullschool.net/#current/wind/surface/level/equirectangular=-0.00,20.00,300"
elif "Vagues" in calque_meteo: url_carte = "https://earth.nullschool.net/#current/ocean/primary/waves/overlay=significant_wave_height/equirectangular=-0.00,20.00,300"
else: url_carte = "https://earth.nullschool.net/#current/ocean/surface/currents/overlay=currents/equirectangular=-0.00,20.00,300"

components.html(f"""<iframe width="100%" height="450" src="{url_carte}" frameborder="0"></iframe>""", height=450)

if st.button(tr("🌪️ Scan Météo", "🌪️ Weather Scan", "🌪️ Escaneo Meteorológico", "🌪️ 天气扫描", "🌪️ मौसम स्कैन"), use_container_width=True):
    if not st.session_state.est_premium:
        st.warning(tr("🔒 L'analyse IA de la météo mondiale est réservée aux membres PRO.", "🔒 AI weather analysis is a PRO feature.", "🔒 El análisis de clima con IA es una función PRO.", "🔒 AI 天气分析是 PRO 功能。", "🔒 एआई मौसम विश्लेषण एक PRO सुविधा है।"))
        st.link_button(tr("💎 S'abonner pour débloquer", "💎 Subscribe to unlock", "💎 Suscríbete para desbloquear", "💎 订阅解锁", "💎 अनलॉक करने के लिए सदस्यता लें"), "https://buy.stripe.com/bJefZg4LAfTP1NO1RWdwc00")
    else:
        with st.status(tr("Analyse des perturbations climatiques...", "Analyzing weather disruptions...", "Analizando clima...", "分析天气...", "मौसम का विश्लेषण..."), expanded=True):
            mots_cles_meteo = "typhoon OR hurricane OR cyclone OR severe storm shipping OR maritime weather alert OR tsunami OR maritime fog OR rogue wave"
            resultats_meteo = DDGS().news(mots_cles_meteo, max_results=5, timelimit='w')
            if resultats_meteo:
                texte_meteo = "\n".join([f"- {r['title']}: {r['body']}" for r in resultats_meteo])
                client = genai.Client(api_key=GEMINI_KEY)
                prompt_meteo = f"""Tu es un expert en météorologie maritime. Trouve EXCLUSIVEMENT les événements climatiques extrêmes impactant la mer/les ports. 
                ⚠️ IGNORE tout ce qui concerne la géopolitique ou l'économie.
                Déduis la latitude et longitude des événements météo trouvés. ⚠️ Rédige en {langue_choisie}.\n\n{texte_meteo}"""
                resultat_meteo = client.models.generate_content(model='gemini-2.5-flash', contents=prompt_meteo, config={'response_mime_type': 'application/json', 'response_schema': WeatherReport, 'temperature': 0.1})
                st.session_state.meteo_actuelle = json.loads(resultat_meteo.text)
                
                if not st.session_state.meteo_actuelle['alertes']:
                    st.success(tr("✅ Océans calmes. Aucune tempête majeure détectée aujourd'hui.", "✅ Calm seas. No major storms detected today.", "✅ Mares en calma. No hay tormentas importantes hoy.", "✅ 海面平静。今天没有发现大风暴。", "✅ शांत समुद्र। आज कोई बड़ा तूफान नहीं।"))
                else:
                    for alerte in st.session_state.meteo_actuelle['alertes']:
                        st.write(f"- 🟠 **{alerte['titre']}** : {alerte['description']}")
            else:
                st.success(tr("✅ Océans calmes. Aucune alerte météo majeure.", "✅ Calm seas.", "✅ Mares en calma.", "✅ 海面平静。", "✅ शांत समुद्र।"))

st.divider()

# --- MARCHÉS FINANCIERS ---
st.subheader(tr("📊 Marchés Financiers", "📊 Financial Markets", "📊 Mercados Financieros", "📊 金融市场", "📊 वित्तीय बाजार"))
col_m1, col_m2, col_m3 = st.columns(3)
def afficher_cours_bourse(symbole, nom_affichage):
    try:
        historique = yf.Ticker(symbole).history(period="7d", interval="30m")
        if not historique.empty:
            st.write(nom_affichage)
            prix_min, prix_max = historique['Close'].min(), historique['Close'].max()
            marge = (prix_max - prix_min) * 0.1  
            fig = go.Figure(data=go.Scatter(x=historique.index, y=historique['Close'], mode='lines', line=dict(color='#00ffcc', width=2)))
            fig.update_layout(margin=dict(l=0, r=0, t=0, b=0), height=200, paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)", yaxis=dict(range=[prix_min - marge, prix_max + marge], showgrid=True, gridcolor='rgba(255,255,255,0.1)'), xaxis=dict(showgrid=False))
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})
    except Exception: pass

with col_m1: afficher_cours_bourse("CL=F", "🛢️ WTI")
with col_m2: afficher_cours_bourse("NG=F", "🔥 Natural Gas")

with col_m3: afficher_cours_bourse("ZW=F", "🌾 Wheat")

