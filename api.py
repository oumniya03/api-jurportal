from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import re

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois")

class QueryModel(BaseModel):
    mot_cle: str

class UrlModel(BaseModel):
    url: str

async def bloquer_ressources(route):
    if route.request.resource_type in ["image", "font", "media"]:
        await route.abort()
    else:
        await route.continue_()

def bloquer_ressources_inutiles(route):
    if route.request.resource_type in ["image", "font", "media"]:
        route.abort()
    else:
        route.continue_()

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
            page.route("**/*", bloquer_ressources_inutiles)
            page.goto(url)
            page.wait_for_timeout(2000)
            texte_complet = page.locator("body").inner_text()
            if len(texte_complet) > 10000:
                texte_limite = texte_complet[:5000] + "\n\n[... PARTIE CENTRALE COUPÉE POUR ALLÉGER LA LECTURE ...]\n\n" + texte_complet[-5000:]
            else:
                texte_limite = texte_complet
            match_ecli = re.search(r"(ECLI:BE:[A-Z]+:\d{4}:[A-Z0-9.]+)", url)
            ecli_confirme = match_ecli.group(1) if match_ecli else "ECLI non détecté dans l'URL"
            reponse_finale = f"ECLI DE CET ARRÊT : {ecli_confirme}\nURL SOURCE : {url}\n\nTEXTE DE L'ARRÊT:\n{texte_limite}"
            browser.close()
            return {"status": "success", "data": reponse_finale}
        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2 — LÉGISLATION (JUSTEL)
# ─────────────────────────────────────────────

@app.get("/loi/sujet")
async def recherche_par_sujet(sujet: str = Query(...), langue: str = Query("fr")):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.ejustice.just.fgov.be/cgi/rech.pl?language=fr", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            
            await page.evaluate(f"""
                const form = document.querySelector('form');
                if (form) {{
                    const input = document.querySelector('input[name="text1"]');
                    if (input) input.value = '{sujet}';
        
                    // Sélectionner type de document = Loi uniquement
                    const typeSelect = document.querySelector('select[name="dt"]');
                    if (typeSelect) {{
                        for (let opt of typeSelect.options) {{
                            if (opt.text.trim().toLowerCase() === 'loi') {{
                                opt.selected = true;
                                break;
                            }}
                        }}
                    }}
                    form.submit();
                }}
            """)

            await page.wait_for_url("**/rech_res.pl**", timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(4000)

            liens = await page.query_selector_all("a[href*='numac']")
            resultats = []
            numacs_vus = set()

            for lien in liens[:30]:
                href = await lien.get_attribute("href") or ""
                titre = (await lien.inner_text()).strip()
                numac_match = re.search(r"numac_search=(\w+)", href)
                if numac_match and titre:
                    numac = numac_match.group(1)
                    if numac in numacs_vus or titre == numac:
                        continue
                    est_loi = any(mot in titre.lower() for mot in ["loi du", "loi relative", "loi sur", "loi portant"])
                    est_cct = any(mot in titre.lower() for mot in ["convention collective", "sous-commission", "commission paritaire"])
                    numacs_vus.add(numac)
                    resultats.append({
                        "numac": numac,
                        "titre": titre[:200],
                        "url_loi": f"https://www.ejustice.just.fgov.be/cgi/{href}",
                        "est_loi": est_loi,
                        "est_cct": est_cct
                    })

            # Trier : lois générales d'abord, CCT en dernier
            resultats.sort(key=lambda x: (not x["est_loi"], x["est_cct"]))

            if not resultats:
                await browser.close()
                return {"status": "aucun_resultat", "message": "Aucune loi trouvée.", "articles": []}

            # Scorer chaque loi par pertinence du titre
            mots = [m for m in sujet.lower().split() if len(m) > 3]
            for r in resultats:
                r["score_titre"] = sum(1 for mot in mots if mot in r["titre"].lower())

            # Trier : lois générales avec score titre élevé d'abord
            resultats.sort(key=lambda x: (not x["est_loi"], x["est_cct"], -x["score_titre"]))

            premier = resultats[0]
            
            await page.goto(premier["url_loi"], wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            texte_complet = await page.inner_text("body")
            texte_complet = re.sub(r'\n{3,}', '\n\n', texte_complet)

            mots = [m for m in sujet.lower().split() if len(m) > 3]
            articles_trouves = []
            blocs = re.split(r'(?=Art\.?\s*\d)', texte_complet)

            for bloc in blocs[:80]:
                score = sum(1 for mot in mots if mot in bloc.lower())
                if score >= 2:
                    art_match = re.match(r'Art\.?\s*(\S+)', bloc)
                    art_num = art_match.group(1).strip() if art_match else "?"
                    articles_trouves.append({
                        "article": art_num,
                        "texte": bloc.strip()[:1000],
                        "score": score
                    })

            articles_trouves.sort(key=lambda x: x["score"], reverse=True)

            await browser.close()
            return {
                "status": "ok",
                "loi": premier["titre"],
                "numac": premier["numac"],
                "url_source": premier["url_loi"],
                "autres_resultats": [r["titre"] for r in resultats[1:3]],
                "articles": articles_trouves[:3]
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/loi/article")
async def lire_article(numac: str = Query(...), article: str = Query(...), langue: str = Query("fr")):
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
# DEBUG
# ─────────────────────────────────────────────

@app.get("/loi/debug")
async def debug_justel(sujet: str = Query(...)):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.ejustice.just.fgov.be/cgi/rech.pl?language=fr", wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)

            await page.evaluate(f"""
                const form = document.querySelector('form');
                if (form) {{
                    const input = document.querySelector('input[name="text1"]');
                    if (input) input.value = '{sujet}';
        
                    // Sélectionner type de document = Loi uniquement
                    const typeSelect = document.querySelector('select[name="dt"]');
                    if (typeSelect) {{
                        for (let opt of typeSelect.options) {{
                            if (opt.text.trim().toLowerCase() === 'loi') {{
                                opt.selected = true;
                                break;
                            }}
                        }}
                    }}
                    form.submit();
                }}
            """)

            await page.wait_for_url("**/rech_res.pl**", timeout=15000)
            await page.wait_for_load_state("networkidle", timeout=15000)
            await page.wait_for_timeout(4000)

            liens = await page.query_selector_all("a[href*='numac']")
            resultats = []
            numacs_vus = set()

            for lien in liens[:20]:
                href = await lien.get_attribute("href") or ""
                titre = (await lien.inner_text()).strip()
                numac_match = re.search(r"numac_search=(\w+)", href)
                if numac_match and titre:
                    numac = numac_match.group(1)
                    if numac in numacs_vus or titre == numac:
                        continue
                    numacs_vus.add(numac)
                    resultats.append({
                        "numac": numac,
                        "titre": titre[:200],
                        "url_loi": f"https://www.ejustice.just.fgov.be/cgi/{href}"
                    })

            await browser.close()
            return {"total": len(resultats), "resultats": resultats}

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
        "endpoints": ["POST /scrape", "POST /lire_arret", "GET /loi/sujet", "GET /loi/article", "GET /loi/debug", "GET /health"]
    }


