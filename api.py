from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
import re
from typing import Optional

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois")

# --- MODÈLES ---
class QueryModel(BaseModel):
    mot_cle: str

# --- UTILITAIRES ---
async def bloquer_ressources(route):
    if route.request.resource_type in ["image", "font", "media"]:
        await route.abort()
    else:
        await route.continue_()

BASE_URL_JUSTEL = "https://www.ejustice.just.fgov.be"

# ─────────────────────────────────────────────
# PARTIE 1 — JURISPRUDENCE (JUPORTAL)
# ─────────────────────────────────────────────

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
                        ecli = match_ecli.group(1)
                        annee = int(match_annee.group(1))
                        if annee >= 2019:
                            type_doc = "ARRÊT" if ":ARR." in ecli else "DÉCISION"
                            resultats.append({
                                "ecli": ecli,
                                "annee": annee,
                                "type": type_doc,
                                "url": "https://juportal.be" + url_propre
                            })

            resultats_tries = sorted(resultats, key=lambda x: x['annee'], reverse=True)[:10]

            texte = f"--- RÉSULTATS POUR '{mot_cle}' (post-2019) ---\n"
            for i, r in enumerate(resultats_tries):
                texte += f"ARR{i+1}: [{r['type']}] ECLI={r['ecli']} | ANNÉE={r['annee']} | URL={r['url']}\n"

            await browser.close()
            return {"status": "success", "data": texte}

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2 — LÉGISLATION (JUSTEL)
# ─────────────────────────────────────────────

@app.get("/loi/sujet")
async def recherche_par_sujet(
    sujet: str = Query(..., description="Ex: 'licenciement employé maladie secteur public'"),
    langue: str = Query("fr")
):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            search_url = (
                f"{BASE_URL_JUSTEL}/cgi_loi/loi.pl"
                f"?language={langue}&la={langue.upper()}"
                f"&rech={sujet.replace(' ', '+')}&sort=pub-desc"
            )
            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            first_link = await page.query_selector("table tr:nth-child(2) td a")
            if not first_link:
                await browser.close()
                return {
                    "status": "aucun_resultat",
                    "message": "Aucune loi trouvée sur ejustice pour ce sujet.",
                    "articles": []
                }

            href = await first_link.get_attribute("href") or ""
            titre_loi = (await first_link.inner_text()).strip()

            numac_match = re.search(r"numac[_=](\w+)", href)
            if not numac_match:
                await browser.close()
                return {"status": "erreur_numac", "message": "Impossible d'extraire le numac."}

            numac = numac_match.group(1)
            loi_url = f"{BASE_URL_JUSTEL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"

            await page.goto(loi_url, wait_until="networkidle", timeout=30000)
            texte_complet = await page.inner_text("body")
            texte_complet = re.sub(r'\n{3,}', '\n\n', texte_complet)

            # Extraire les articles pertinents
            mots = [m for m in sujet.lower().split() if len(m) > 3]
            articles_trouves = []
            blocs = re.split(r'(?=Art\.?\s*\d)', texte_complet)

            for bloc in blocs[:50]:
                score = sum(1 for mot in mots if mot in bloc.lower())
                if score >= 2:
                    art_match = re.match(r'Art\.?\s*(\S+)', bloc)
                    art_num = art_match.group(1).strip() if art_match else "?"
                    articles_trouves.append({
                        "article": art_num,
                        "texte": bloc.strip()[:800],
                        "score": score
                    })

            articles_trouves.sort(key=lambda x: x["score"], reverse=True)

            await browser.close()
            return {
                "status": "ok",
                "loi": titre_loi,
                "numac": numac,
                "url_source": loi_url,
                "articles": articles_trouves[:3]
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/loi/article")
async def lire_article(
    numac: str = Query(..., description="Ex: 1978070301"),
    article: str = Query(..., description="Ex: 34 ou 34§1"),
    langue: str = Query("fr")
):
    url = f"{BASE_URL_JUSTEL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            texte = await page.inner_text("body")
            texte = re.sub(r'\n{3,}', '\n\n', texte)

            patterns = [
                rf"Art\.?\s*{re.escape(article)}[\s\.\-](.+?)(?=Art\.?\s*\d|\Z)",
                rf"Article\s+{re.escape(article)}[\s\.\-](.+?)(?=Art|\Z)",
            ]
            texte_art = None
            for pat in patterns:
                m = re.search(pat, texte, re.DOTALL | re.IGNORECASE)
                if m:
                    texte_art = m.group(0)[:1500].strip()
                    break

            await browser.close()
            return {
                "status": "ok" if texte_art else "article_non_trouve",
                "numac": numac,
                "article": article,
                "texte_verbatim": texte_art or "Article non trouvé — vérifiez le numéro.",
                "url_source": url
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/health")
async def health():
    return {
        "status": "online",
        "version": "Phase 2 - Jurisprudence & Justel",
        "endpoints": [
            "POST /scrape",
            "GET /loi/sujet",
            "GET /loi/article",
            "GET /health"
        ]
    }
