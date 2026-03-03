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
            liens_uniques = set()
            
            for lien in liens_elements:
                url = lien.get_attribute("href")
                if url and "ECLI" in url:
                    url_propre = url.split('?')[0].split('#')[0]
                    match = re.search(r"ECLI:BE:[A-Z]+:(\d{4}):", url_propre)
                    # Filtrage strict >= 2019
                    if match and int(match.group(1)) >= 2019:
                        liens_uniques.add("https://juportal.be" + url_propre)

            # Limitation à 2 arrêts pour la rapidité
            liens = list(liens_uniques)[:2]
            
            for url in liens:
                page.goto(url)
                page.wait_for_timeout(1000)
                texte = page.locator("body").inner_text()[:3000]
                resultats_texte += f"\nSOURCE URL: {url}\nRÉSUMÉ/TEXTE: {texte}...\n"
                
            browser.close()
            return {"status": "success", "data": resultats_texte}

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))