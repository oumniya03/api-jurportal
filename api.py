from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
import re

app = FastAPI(title="API Jurisprudence JURPORTAL")

# --- MODÈLES DE DONNÉES ---
class QueryModel(BaseModel):
    mot_cle: str

class UrlModel(BaseModel):
    url: str

# --- OUTIL 1 : RECHERCHE GLOBALE ET TRI HYBRIDE ---
@app.post("/scrape")
def scrape_jurisprudence(query: QueryModel):
    mot_cle = query.mot_cle
    resultats_texte = f"--- JURISPRUDENCE TROUVÉE POUR '{mot_cle}' ---\n"
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto("https://juportal.be/moteur/formulaire")
            page.locator("input#texpression").fill(mot_cle)
            page.locator("button[type='submit']:has-text('Rechercher')").first.click()
            
            page.wait_for_timeout(3000)
            
            liens_elements = page.locator("a[href*='ECLI']").element_handles()
            liens_pertinents = {}
            
            for lien in liens_elements:
                url = lien.get_attribute("href")
                if url and "ECLI" in url:
                    url_propre = url.split('?')[0].split('#')[0]
                    match = re.search(r"ECLI:BE:[A-Z]+:(\d{4}):", url_propre)
                    if match:
                        annee = int(match.group(1))
                        if annee >= 2019:
                            url_complete = "https://juportal.be" + url_propre
                            liens_pertinents[url_complete] = annee

            liens_tries = sorted(liens_pertinents.items(), key=lambda item: item[1], reverse=True)
            liens_a_visiter = [item[0] for item in liens_tries][:3]
            
            for url in liens_a_visiter:
                page.goto(url)
                page.wait_for_timeout(1000)
                texte = page.locator("body").inner_text()[:2500]
                resultats_texte += f"\nSOURCE URL: {url}\nRÉSUMÉ/TEXTE: {texte}...\n"
                
            browser.close()
            return {"status": "success", "data": resultats_texte}

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))

# --- OUTIL 2 : LECTURE PROFONDE D'UN ARRÊT ---
@app.post("/lire_arret")
def lire_arret_complet(query: UrlModel):
    url = query.url
    
    # Sécurité : vérifier que l'URL est bien celle de JURPORTAL
    if "juportal.be" not in url:
        raise HTTPException(status_code=400, detail="L'URL doit provenir de juportal.be")
        
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto(url)
            page.wait_for_timeout(2000) # On laisse le temps au gros document de charger
            
            # On extrait tout le texte de la page
            texte_complet = page.locator("body").inner_text()
            
            # On limite à 30 000 caractères pour ne pas faire exploser la mémoire de l'IA dans n8n
            #texte_limite = texte_complet[:30000]
            # On prend le début (les faits) et la fin (la décision du juge)
            texte_limite = texte_complet[:15000] + "\n\n[... PARTIE CENTRALE COUPÉE POUR ALLÉGER LA LECTURE ...]\n\n" + texte_complet[-15000:]
            
            browser.close()
            return {"status": "success", "data": texte_limite}

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))

