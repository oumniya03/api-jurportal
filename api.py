from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from playwright.sync_api import sync_playwright
import re

app = FastAPI(title="API Jurisprudence JURPORTAL")

# Définition du format de la requête attendue
class QueryModel(BaseModel):
    mot_cle: str

@app.post("/scrape")
def scrape_jurisprudence(query: QueryModel):
    mot_cle = query.mot_cle
    resultats_texte = f"--- JURISPRUDENCE TROUVÉE POUR '{mot_cle}' ---\n"
    
    with sync_playwright() as p:
        try:
            # Toujours en mode headless pour le serveur
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            
            page.goto("https://juportal.be/moteur/formulaire")
            page.locator("input#texpression").fill(mot_cle)
            page.locator("button[type='submit']:has-text('Rechercher')").first.click()
            
            page.wait_for_timeout(3000)
            
            liens_elements = page.locator("a[href*='ECLI']").element_handles()
            
            # NOUVEAU : On utilise un dictionnaire pour stocker l'URL ET son année
            liens_pertinents = {}
            
            for lien in liens_elements:
                url = lien.get_attribute("href")
                if url and "ECLI" in url:
                    url_propre = url.split('?')[0].split('#')[0]
                    # On extrait l'année de l'ECLI (ex: 2022)
                    match = re.search(r"ECLI:BE:[A-Z]+:(\d{4}):", url_propre)
                    
                    if match:
                        annee = int(match.group(1))
                        # Filtrage strict >= 2019
                        if annee >= 2019:
                            url_complete = "https://juportal.be" + url_propre
                            # On sauvegarde l'URL avec son année
                            liens_pertinents[url_complete] = annee

            # NOUVEAU : Le TRI HYBRIDE
            # On trie notre dictionnaire en fonction de l'année (reverse=True pour avoir les plus récents d'abord)
            liens_tries = sorted(liens_pertinents.items(), key=lambda item: item[1], reverse=True)
            
            # On prend les 3 arrêts les plus récents parmi les plus pertinents
            # J'ai augmenté à 3 (au lieu de 2) pour donner un peu plus de choix à l'IA
            liens_a_visiter = [item[0] for item in liens_tries][:3]
            
            for url in liens_a_visiter:
                page.goto(url)
                page.wait_for_timeout(1000)
                # On limite à 2500 caractères par arrêt pour ne pas surcharger l'IA
                texte = page.locator("body").inner_text()[:2500]
                resultats_texte += f"\nSOURCE URL: {url}\nRÉSUMÉ/TEXTE: {texte}...\n"
                
            browser.close()
            return {"status": "success", "data": resultats_texte}

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))
