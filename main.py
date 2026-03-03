import streamlit as st
import os
import json
from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS

st.set_page_config(page_title="Signal Zero - Sentinelle", page_icon="🌍", layout="wide")

load_dotenv()
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

# --- LE NOUVEAU MOULE : L'ALERTE DE CRISE ---
class CrisisAlert(BaseModel):
    crise_detectee: bool = Field(..., description="Mettre True si un incident grave (blocage, grève, accident) est mentionné dans les actualités. False sinon.")
    titre_alerte: str = Field(..., description="Titre accrocheur de la crise (ex: 'Blocage Pétrolier au Canal de Suez')")
    nom_cible: str = Field(..., description="Nom du navire ou du port impliqué")
    resume_incident: str = Field(..., description="Que s'est-il passé exactement selon les médias ?")
    matieres_premieres_impactees: list[str] = Field(..., description="Quelles matières (pétrole, gaz, blé, composants) risquent de manquer ?")
    consequences_supply_chain: str = Field(..., description="Effet domino prévu sur les usines ou les distributeurs.")
    recommandation_action: str = Field(..., description="Conseil pour un Hedge Fund ou Directeur Logistique (ex: Sécuriser des stocks, Shorter l'action X).")

# --- 1. L'AGENT VEILLEUR (Scan les infos mondiales) ---
def scanner_actualites_maritimes():
    # On cherche les mots-clés de crise logistique globale
    mots_cles = "cargo ship grounded OR oil tanker blocked OR major port strike OR shipping lane disrupted"
    try:
        # On demande à DuckDuckGo les 10 dernières dépêches d'actualité
        resultats = DDGS().news(mots_cles, max_results=10, timelimit='w')
        if not resultats:
            return ""
        
        # On compile tout ça dans un gros texte pour Gemini
        texte_brut = ""
        for article in resultats:
            texte_brut += f"Titre: {article['title']}\nRésumé: {article['body']}\nDate: {article['date']}\n---\n"
        return texte_brut
    except Exception as e:
        st.error(f"Erreur du radar d'actualité : {e}")
        return ""

# --- L'INTERFACE UTILISATEUR ---
st.title("🌍 Signal Zero : Mode Sentinelle Mondiale")
st.markdown("### Détection autonome des crises Supply Chain et signaux de trading")

st.info("Le radar écoute actuellement les médias mondiaux (Reuters, Bloomberg, journaux maritimes...) à la recherche d'incidents.")

# LE BOUTON D'ÉCOUTE
if st.button("📡 Lancer le Scan Mondial des Crises (Temps Réel)", type="primary", use_container_width=True):
    
    with st.status("Étape 1 : Interception des communications et médias mondiaux...", expanded=True) as status:
        actualites = scanner_actualites_maritimes()
        st.write("Dépêches interceptées. Transmission au cerveau IA...")
        
        if not actualites:
            status.update(label="Aucun signal reçu des médias.", state="error")
            st.stop()
            
        status.update(label="Étape 2 : L'Analyste IA cherche une crise à exploiter...", state="running")
        
        try:
            # On envoie les actus à Gemini
            client = genai.Client(api_key=GEMINI_KEY)
            
            prompt = f"""
            Tu es un analyste de crise travaillant pour un Hedge Fund.
            Lis attentivement ces dépêches d'actualité mondiales de ces dernières 24/48h :
            
            {actualites}
            
            TA MISSION :
            Y a-t-il un navire bloqué, échoué, attaqué, ou un grand port en grève ?
            Si OUI, extrais les infos, déduis quelles matières premières vont manquer, et donne un plan d'action financier/logistique agressif.
            Si NON, mets simplement 'crise_detectee' à False.
            """

            resultat = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': CrisisAlert,
                    'temperature': 0.2 # On veut de la précision analytique
                },
            )
            
            rapport = json.loads(resultat.text)
            status.update(label="Analyse terminée !", state="complete", expanded=False)
            
            # --- AFFICHAGE DU RÉSULTAT ---
            if rapport['crise_detectee']:
                st.error(f"🚨 **ALERTE MAJEURE DÉTECTÉE : {rapport['titre_alerte']}**")
                
                col1, col2 = st.columns(2)
                
                with col1:
                    st.subheader("📝 Détails de l'Incident")
                    st.write(f"**Cible impliquée :** {rapport['nom_cible']}")
                    st.write(rapport['resume_incident'])
                    
                    st.subheader("⚠️ Impact Supply Chain")
                    st.write(rapport['consequences_supply_chain'])

                with col2:
                    st.subheader("📉 Analyse Marché & Trading")
                    st.write("**Matières Premières impactées :**")
                    for matiere in rapport['matieres_premieres_impactees']:
                        st.markdown(f"- 🛢️ {matiere}")
                    
                    st.success(f"**💡 Recommandation d'Action :**\n{rapport['recommandation_action']}")
            else:
                st.success("✅ Océans calmes. Aucune anomalie logistique majeure détectée dans la presse mondiale pour le moment.")

        except Exception as e:
            st.error(f"Une erreur est survenue lors de l'analyse : {e}")