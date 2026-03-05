import os
import json
import requests
from google import genai
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS

GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

# --- LE NOUVEAU MOULE EXIGEANT ---
class CrisisAlert(BaseModel):
    crise_nouvelle_detectee: bool = Field(..., description="True UNIQUEMENT s'il y a un NOUVEL incident précis aujourd'hui. False si c'est juste un article de fond sur un conflit en cours (ex: tensions générales).")
    titre_alerte: str = Field(..., description="Titre précis de l'incident.")
    noms_navires_confirmes: list[str] = Field(..., description="Noms exacts des navires (ex: 'MV Tutor'). Si aucun nom précis n'est mentionné dans les textes, laisse la liste vide.")
    sources_croisees: int = Field(..., description="Nombre de dépêches différentes qui parlent exactement de ce même événement.")
    resume_incident: str = Field(..., description="Résumé factuel de l'incident croisé entre les sources.")
    recommandation_action: str = Field(..., description="Conseil d'investissement ou d'action logistique.")

def run_bot():
    print("🤖 Démarrage du scan automatique (Mode Fact-Checker)...")
    
    try:
        # 1. On cherche UNIQUEMENT sur le dernier jour (timelimit='d') au lieu de la semaine ('w')
        # On augmente à 15 résultats pour avoir de quoi croiser les sources
        resultats = DDGS().news("cargo ship attacked OR oil tanker grounded OR port strike", max_results=15, timelimit='d')
        if not resultats:
            print("✅ Océan calme ces dernières 24h. Fin du scan.")
            return
            
        actualites = ""
        for i, r in enumerate(resultats):
            actualites += f"Source {i+1} | Titre: {r['title']} | Résumé: {r['body']}\n---\n"
            
    except Exception as e:
        print(f"Erreur DuckDuckGo : {e}")
        return

    # 2. Le Prompt Intransigeant
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"""
    Tu es un enquêteur et analyste Supply Chain ultra-strict.
    Lis ces dépêches des dernières 24 heures :
    
    {actualites}
    
    TES RÈGLES D'OR :
    1. ANTI-RADOTAGE : Ignore les articles généraux sur des tensions géopolitiques globales. Je ne veux que des INCIDENTS NOUVEAUX ET PRÉCIS (un bateau attaqué aujourd'hui, un port bloqué ce matin).
    2. PREUVES : Cherche le nom précis du ou des navires concernés.
    3. CROISEMENT : Vérifie si plusieurs sources parlent du même incident. Une seule source peut être une rumeur.
    
    S'il n'y a pas d'événement nouveau et précis avec au moins un nom de navire ou de port bloqué aujourd'hui, mets 'crise_nouvelle_detectee' à False.
    """
    
    resultat = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config={'response_mime_type': 'application/json', 'response_schema': CrisisAlert, 'temperature': 0.1}, # Température très basse pour éviter l'invention
    )
    rapport = json.loads(resultat.text)
    
    
# 3. L'envoi avec les nouvelles exigences
    if rapport['crise_nouvelle_detectee'] and len(rapport['noms_navires_confirmes']) > 0:
        navires_str = ", ".join(rapport['noms_navires_confirmes'])
        
        message = (
            f"🚨 **NOUVELLE ALERTE MAJEURE CONFIRMÉE : {rapport['titre_alerte']}** 🚨\n"
            f"🚢 **Navires confirmés :** {navires_str}\n"
            f"🗞️ **Sources croisées :** {rapport['sources_croisees']} articles concordants\n"
            f"📝 **Fait validé :** {rapport['resume_incident']}\n\n"
            f"💡 **Recommandation :** {rapport['recommandation_action']}"
        )
        if DISCORD_WEBHOOK:
            requests.post(DISCORD_WEBHOOK, json={"content": message})
            print("✅ Alerte vérifiée envoyée sur Discord !")
    else:
        # NOUVEAU : LE SIGNAL DE VIE
        message_calme = "✅ *Scan de routine Signal Zero : Océans calmes, aucune crise majeure détectée ces dernières 24h.*"
        if DISCORD_WEBHOOK:
            requests.post(DISCORD_WEBHOOK, json={"content": message_calme})
        print("✅ Scan terminé. Message de routine envoyé.")

if __name__ == "__main__":
    run_bot()