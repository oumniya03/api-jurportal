from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
import asyncio
import re
from typing import Optional

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois")

# --- MODÈLES DE DONNÉES ---
class QueryModel(BaseModel):
    mot_cle: str

class UrlModel(BaseModel):
    url: str

# --- CONSTANTES JUSTEL ---
BASE_URL_JUSTEL = "https://www.ejustice.just.fgov.be"
LOIS_CONNUES = {
    "loi_1978": "1978070301",
    "code_bienetre": "1996012650",
    "loi_1971": "1971030655",
    "anti_discrimination": "2007002099",
    "code_penal": "1867060801",
    "statut_unique": "2013122601",
}

# --- UTILITAIRES ---
async def bloquer_ressources(route):
    if route.request.resource_type in ["image", "font", "media"]:
        await route.abort()
    else:
        await route.continue_()

# --- PARTIE 1 : JURISPRUDENCE (JUPORTAL) ---

@app.post("/scrape")
async def scrape_jurisprudence(query: QueryModel):
    mot_cle = query.mot_cle
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.route("**/*", bloquer_ressources)
        
        try:
            await page.goto("https://juportal.be/moteur/formulaire", timeout=60000)
            await page.locator("input#texpression").fill(mot_cle)
            await page.locator("button[type='submit']:has-text('Rechercher')").first.click()
            await page.wait_for_timeout(3000)

            liens_elements = await page.locator("a[href*='ECLI']").all()
            resultats = []
            
            for lien in liens_elements:
                url = await lien.get_attribute("href")
                if url and "ECLI" in url:
                    url_propre = url.split('?')[0].split('#')[0]
                    match_ecli = re.search(r"(ECLI:BE:[A-Z]+:\d{4}:[A-Z0-9.]+)", url_propre)
                    match_annee = re.search(r"ECLI:BE:[A-Z]+:(\d{4}):", url_propre)
                    if match_ecli and match_annee:
                        ecli, annee = match_ecli.group(1), int(match_annee.group(1))
                        if annee >= 2019:
                            type_doc = "ARRÊT" if ":ARR." in ecli else "DÉCISION"
                            resultats.append({"ecli": ecli, "annee": annee, "type": type_doc, "url": "https://juportal.be" + url_propre})

            resultats_tries = sorted(resultats, key=lambda x: x['annee'], reverse=True)[:10]
            
            texte = f"--- RÉSULTATS POUR '{mot_cle}' (post-2019) ---\n"
            for i, r in enumerate(resultats_tries):
                texte += f"ARR{i+1}: [{r['type']}] ECLI={r['ecli']} | ANNÉE={r['annee']} | URL={r['url']}\n"
            
            await browser.close()
            return {"status": "success", "data": texte}
        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))

# --- PARTIE 2 : LÉGISLATION (JUSTEL) ---

@app.get("/loi/sujet")
async def recherche_par_sujet(sujet: str = Query(...), langue: str = "fr"):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            search_url = f"{BASE_URL_JUSTEL}/cgi_loi/loi.pl?language={langue}&la={langue.upper()}&rech={sujet.replace(' ', '+')}&sort=pub-desc"
            await page.goto(search_url, wait_until="networkidle")
            
            first_link = await page.query_selector("table tr:nth-child(2) td a")
            if not first_link:
                await browser.close()
                return {"status": "aucun_resultat", "message": "Aucune loi trouvée."}

            href = await first_link.get_attribute("href")
            numac = re.search(r"numac[_=](\w+)", href).group(1)
            
            loi_url = f"{BASE_URL_JUSTEL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"
            await page.goto(loi_url)
            texte_complet = await page.inner_text("body")
            
            # Extraction simplifiée des articles mentionnant le sujet
            articles = []
            blocs = re.split(r'(?=Art\.?\s*\d)', texte_complet)
            for bloc in blocs[:30]:
                if any(word.lower() in bloc.lower() for word in sujet.split()):
                    articles.append({"article": "Extrait", "texte": bloc.strip()[:800]})
            
            await browser.close()
            return {"status": "ok", "loi": numac, "url": loi_url, "articles": articles[:3]}
        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    return {"status": "online", "version": "Phase 2 - Jurisprudence & Justel"}
