import os
import json
import requests
from google import genai
from pydantic import BaseModel, Field
from duckduckgo_search import DDGS

# On récupère les clés secrètes du Cloud
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
DISCORD_WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL")

class CrisisAlert(BaseModel):
    crise_detectee: bool = Field(..., description="True si crise grave, sinon False")
    titre_alerte: str = Field(..., description="Titre accrocheur")
    nom_cible: str = Field(..., description="Navire ou port impliqué")
    resume_incident: str = Field(..., description="Résumé factuel")
    recommandation_action: str = Field(..., description="Conseil d'investissement/logistique")

def run_bot():
    print("🤖 Démarrage du scan automatique (Robot de l'ombre)...")
    
    # 1. Le Veilleur cherche les actualités
    try:
        resultats = DDGS().news("cargo ship grounded OR oil tanker blocked OR major port strike", max_results=10, timelimit='w')
        if not resultats:
            print("Océan calme. Fin du scan.")
            return
            
        actualites = "\n".join([f"Titre: {r['title']}\nRésumé: {r['body']}" for r in resultats])
    except Exception as e:
        print(f"Erreur DuckDuckGo : {e}")
        return

    # 2. L'Analyste IA cherche une crise
    client = genai.Client(api_key=GEMINI_KEY)
    prompt = f"Tu es un analyste de crise. Cherche une urgence absolue dans ces actus :\n\n{actualites}"
    
    resultat = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config={'response_mime_type': 'application/json', 'response_schema': CrisisAlert, 'temperature': 0.2},
    )
    rapport = json.loads(resultat.text)
    
    # 3. L'envoi sur Discord (si une crise est trouvée)
    if rapport['crise_detectee']:
        message = (
            f"🚨 **NOUVELLE ALERTE MAJEURE : {rapport['titre_alerte']}** 🚨\n"
            f"🎯 **Cible :** {rapport['nom_cible']}\n"
            f"📝 **Incident :** {rapport['resume_incident']}\n\n"
            f"💡 **Recommandation :** {rapport['recommandation_action']}"
        )
        if DISCORD_WEBHOOK:
            requests.post(DISCORD_WEBHOOK, json={"content": message})
            print("✅ Alerte envoyée sur Discord !")
    else:
        print("✅ Scan terminé. Aucune crise ne nécessite une alerte immédiate.")

if __name__ == "__main__":
    run_bot()