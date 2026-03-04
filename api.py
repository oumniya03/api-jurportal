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

# --- FONCTION POUR BLOQUER LES IMAGES ET ACCÉLÉRER LE CHARGEMENT ---
def bloquer_ressources_inutiles(route):
    if route.request.resource_type in ["image", "stylesheet", "font", "media"]:
        route.abort()
    else:
        route.continue_()

# --- OUTIL 1 : RECHERCHE GLOBALE ET TRI HYBRIDE ---
@app.post("/scrape")
def scrape_jurisprudence(query: QueryModel):
    mot_cle = query.mot_cle
    resultats_texte = f"--- JURISPRUDENCE TROUVÉE POUR '{mot_cle}' ---\n"
    
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # Optimisation : On bloque les images pour aller plus vite
            page.route("**/*", bloquer_ressources_inutiles)
            
            page.goto("https://juportal.be/moteur/formulaire")
            page.locator("input#texpression").fill(mot_cle)
            page.locator("button[type='submit']:has-text('Rechercher')").first.click()
            
            page.wait_for_timeout(2000) # Réduit à 2 secondes grâce au blocage des images
            
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
                page.wait_for_timeout(500) # Réduit à 0.5 sec
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
    
    if "juportal.be" not in url:
        raise HTTPException(status_code=400, detail="L'URL doit provenir de juportal.be")
        
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            
            # Optimisation : On bloque les images pour charger la longue page instantanément
            page.route("**/*", bloquer_ressources_inutiles)
            
            page.goto(url)
            page.wait_for_timeout(1000) # Réduit à 1 seconde
            
            texte_complet = page.locator("body").inner_text()
            
            # Optimisation Mémoire IA : 5000 début + 5000 fin (10 000 caractères max)
            if len(texte_complet) > 10000:
                texte_limite = texte_complet[:5000] + "\n\n[... PARTIE CENTRALE COUPÉE POUR ALLÉGER LA LECTURE ...]\n\n" + texte_complet[-5000:]
            else:
                texte_limite = texte_complet
            
            # CORRECTION CRUCIALE : On force l'URL et l'ECLI dans le texte renvoyé à l'IA
            reponse_finale = f"VOICI L'URL SOURCE QUE TU DOIS DONNER AU CLIENT : {url}\n\nTEXTE DE L'ARRÊT:\n{texte_limite}"
            
            browser.close()
            return {"status": "success", "data": reponse_finale}

        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))
