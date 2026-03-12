from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import re
import httpx

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois v2")


# ─────────────────────────────────────────────
# FONCTIONS UTILITAIRES PLAYWRIGHT
# ─────────────────────────────────────────────

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


def construire_url_citation(numac: str) -> str:
    """
    URL valide pour citation — page CGI qui existe toujours pour n'importe quel numac.
    C'est la même URL utilisée pour le scraping, donc toujours accessible.
    """
    return f"{BASE_URL_JUSTEL}/cgi_loi/change_lg.pl?language=fr&la=F&table_name=loi&cn={numac}"


def construire_url_scraping(numac: str) -> str:
    """
    URL optimisée pour le scraping Playwright — retourne le texte consolidé complet.
    """
    return f"{BASE_URL_JUSTEL}/cgi_loi/change_lg.pl?language=fr&la=F&table_name=loi&cn={numac}"


async def extraire_articles_depuis_texte(texte: str, mots_cles: list[str]) -> list[dict]:
    """
    Extrait et score les articles d'un texte de loi selon les mots-clés.
    """
    texte = re.sub(r'\n{3,}', '\n\n', texte)
    blocs = re.split(r'(?=\bArt(?:icle)?\.?\s*\d)', texte)

    articles = []
    for bloc in blocs[:120]:
        art_match = re.match(r'\bArt(?:icle)?\.?\s*(\S+)', bloc)
        if not art_match:
            continue
        art_num = art_match.group(1).strip().rstrip('.')
        score = sum(1 for mot in mots_cles if mot in bloc.lower())
        if score >= 1:
            articles.append({
                "article": art_num,
                "texte": bloc.strip()[:1500],
                "score": score
            })

    articles.sort(key=lambda x: x["score"], reverse=True)
    return articles[:5]


async def scraper_loi_par_numac(numac: str, mots_cles: list[str] = None) -> dict:
    """
    Scrape le texte d'une loi depuis Justel via son numac.
    """
    url_scraping = construire_url_scraping(numac)
    url_citation = construire_url_citation(numac)
    mots_cles = mots_cles or []

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        await page.route("**/*", bloquer_ressources)

        try:
            await page.goto(url_scraping, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(1500)
            texte = await page.inner_text("body")

            if len(texte) < 500 or "formulaire" in texte.lower()[:200]:
                url_fallback = f"{BASE_URL_JUSTEL}/cgi_loi/loi_a1.pl?language=fr&tri=dd+AS+RANK&cn={numac}&caller=image_a1&fromtab=loi&la=F"
                await page.goto(url_fallback, wait_until="networkidle", timeout=30000)
                await page.wait_for_timeout(1500)
                texte = await page.inner_text("body")

            texte = re.sub(r'\n{3,}', '\n\n', texte)

            articles = []
            if mots_cles:
                mots_filtres = [m for m in mots_cles if len(m) > 3]
                articles = await extraire_articles_depuis_texte(texte, mots_filtres)

            await browser.close()
            return {
                "status": "ok",
                "numac": numac,
                "url_source": url_citation,
                "url_scraping": url_scraping,
                "texte_longueur": len(texte),
                "articles": articles
            }

        except Exception as e:
            await browser.close()
            return {"status": "erreur", "numac": numac, "detail": str(e)}


# ─────────────────────────────────────────────
# PARTIE 1 — JURISPRUDENCE (JUPORTAL)
# INCHANGÉ
# ─────────────────────────────────────────────

class QueryModel(BaseModel):
    mot_cle: str

class UrlModel(BaseModel):
    url: str


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
                texte_limite = (
                    texte_complet[:5000]
                    + "\n\n[... PARTIE CENTRALE COUPÉE POUR ALLÉGER LA LECTURE ...]\n\n"
                    + texte_complet[-5000:]
                )
            else:
                texte_limite = texte_complet
            match_ecli = re.search(r"(ECLI:BE:[A-Z]+:\d{4}:[A-Z0-9.]+)", url)
            ecli_confirme = match_ecli.group(1) if match_ecli else "ECLI non détecté dans l'URL"
            reponse_finale = (
                f"ECLI DE CET ARRÊT : {ecli_confirme}\n"
                f"URL SOURCE : {url}\n\n"
                f"TEXTE DE L'ARRÊT:\n{texte_limite}"
            )
            browser.close()
            return {"status": "success", "data": reponse_finale}
        except Exception as e:
            if 'browser' in locals():
                browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2A — LÉGISLATION : RECHERCHE PAR SUJET
# Remplace /loi/connue — scraping Justel direct, zéro dictionnaire hardcodé
# ─────────────────────────────────────────────

@app.get("/loi/recherche")
async def recherche_loi_par_sujet(
    sujet: str = Query(..., description="Sujet juridique en langage naturel"),
    langue: str = Query("fr")
):
    """
    Recherche une loi sur Justel par sujet — scraping direct, aucun dictionnaire hardcodé.
    Retourne le vrai numac + la vraie URL depuis Justel.

    Exemple : GET /loi/recherche?sujet=licenciement+maladie+employé
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        try:
            await page.goto(
                "https://www.ejustice.just.fgov.be/cgi/rech.pl?language=fr",
                wait_until="networkidle",
                timeout=30000
            )
            await page.wait_for_timeout(2000)

            await page.evaluate(f"""
                const form = document.querySelector('form');
                if (form) {{
                    const input = document.querySelector('input[name="text1"]');
                    if (input) input.value = '{sujet}';
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
                if numac_match and titre and titre != numac_match.group(1):
                    numac = numac_match.group(1)
                    if numac in numacs_vus:
                        continue
                    numacs_vus.add(numac)
                    est_loi = any(
                        mot in titre.lower()
                        for mot in ["loi du", "loi relative", "loi sur", "loi portant"]
                    )
                    est_cct = any(
                        mot in titre.lower()
                        for mot in ["convention collective", "sous-commission", "commission paritaire"]
                    )
                    mots_sujet = [m for m in sujet.lower().split() if len(m) > 3]
                    score_titre = sum(1 for m in mots_sujet if m in titre.lower())
                    resultats.append({
                        "numac": numac,
                        "titre": titre[:200],
                        "url_source": construire_url_citation(numac),
                        "est_loi": est_loi,
                        "est_cct": est_cct,
                        "score_titre": score_titre
                    })

            # Tri : lois générales > score titre > non-CCT
            resultats.sort(key=lambda x: (not x["est_loi"], x["est_cct"], -x["score_titre"]))

            await browser.close()

            if not resultats:
                return {
                    "status": "aucun_resultat",
                    "message": "Aucun résultat Justel. Vérifiez le sujet ou élargissez la recherche.",
                    "loi": None
                }

            premier = resultats[0]
            return {
                "status": "ok",
                "source": "justel_scraping_direct",
                "loi": {
                    "titre": premier["titre"],
                    "numac": premier["numac"],
                    "url_source": premier["url_source"],
                    "score_pertinence": premier["score_titre"]
                },
                "autres_candidats": [
                    {"titre": r["titre"], "numac": r["numac"], "url_source": r["url_source"]}
                    for r in resultats[1:3]
                ],
                "instruction_agent": (
                    f"Pour citer des articles verbatim : appelle GET /loi/article?numac={premier['numac']}&article=XX. "
                    f"L'URL source à citer est : {premier['url_source']}"
                )
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2B — LÉGISLATION : ACCÈS DIRECT PAR NUMAC
# INCHANGÉ
# ─────────────────────────────────────────────

@app.get("/loi/numac")
async def lire_loi_par_numac(
    numac: str = Query(..., description="Numéro NUMAC de la loi (ex: 1978070301)"),
    mots_cles: str = Query("", description="Mots-clés séparés par des virgules pour filtrer les articles"),
    max_articles: int = Query(5, description="Nombre max d'articles retournés")
):
    """
    Récupère le texte d'une loi depuis Justel via son numac.
    Exemple : GET /loi/numac?numac=1978070301&mots_cles=maladie,licenciement
    """
    mots = [m.strip() for m in mots_cles.split(",") if len(m.strip()) > 2] if mots_cles else []
    resultat = await scraper_loi_par_numac(numac, mots)

    if resultat["status"] == "erreur":
        raise HTTPException(
            status_code=502,
            detail=f"Impossible de récupérer la loi {numac} depuis Justel : {resultat.get('detail')}"
        )

    articles = resultat.get("articles", [])[:max_articles]

    return {
        "status": "ok",
        "numac": numac,
        "url_source": resultat["url_source"],
        "texte_longueur": resultat["texte_longueur"],
        "articles_extraits": len(articles),
        "articles": articles,
        "note": "Texte récupéré en temps réel depuis ejustice.just.fgov.be (Justel)"
    }


# ─────────────────────────────────────────────
# PARTIE 2C — LÉGISLATION : ARTICLE PRÉCIS PAR NUMAC
# url_source utilise construire_url_citation() — URL CGI valide pour tout numac
# ─────────────────────────────────────────────

@app.get("/loi/article")
async def lire_article_precis(
    numac: str = Query(..., description="Numéro NUMAC de la loi"),
    article: str = Query(..., description="Numéro d'article (ex: 38, 65bis, 1er)"),
    langue: str = Query("fr")
):
    """
    Récupère le texte verbatim d'un article précis d'une loi.
    Exemple : GET /loi/article?numac=1978070301&article=38
    """
    url_scraping = construire_url_scraping(numac)
    url_citation = construire_url_citation(numac)  # ← URL valide (CGI, pas ELI)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        await page.route("**/*", bloquer_ressources)

        try:
            await page.goto(url_scraping, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(1500)
            texte = await page.inner_text("body")
            texte = re.sub(r'\n{3,}', '\n\n', texte)

            article_escape = re.escape(article)
            patterns = [
                rf"(Art\.?\s*{article_escape}[\.< \t].+?)(?=\n\s*Art\.?\s*\d|\Z)",
                rf"(Article\s+{article_escape}[\. ].+?)(?=\n\s*Art\.?\s*\d|\Z)",
            ]

            texte_art = None
            for pat in patterns:
                m = re.search(pat, texte, re.DOTALL | re.IGNORECASE)
                if m:
                    texte_art = m.group(1)[:3000].strip()
                    break

            await browser.close()

            if texte_art:
                return {
                    "status": "ok",
                    "numac": numac,
                    "article": article,
                    "texte_verbatim": texte_art,
                    "url_source": url_citation,
                    "note": "Texte récupéré en temps réel depuis Justel (législation consolidée)"
                }
            else:
                return {
                    "status": "article_non_trouve",
                    "numac": numac,
                    "article": article,
                    "texte_verbatim": None,
                    "url_source": url_citation,
                    "note": (
                        f"Article {article} introuvable dans la loi {numac}. "
                        "Vérifiez le numéro d'article ou consultez l'URL source directement."
                    )
                }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2D — /loi/sujet conservé comme alias de /loi/recherche
# Pour compatibilité avec les anciens appels n8n
# ─────────────────────────────────────────────

@app.get("/loi/sujet")
async def loi_sujet_alias(
    sujet: str = Query(...),
    langue: str = Query("fr")
):
    """
    Alias de /loi/recherche — conservé pour compatibilité.
    Redirige vers le scraping Justel direct.
    """
    return await recherche_loi_par_sujet(sujet=sujet, langue=langue)


# Alias /loi/connue → /loi/recherche pour compatibilité workflow existant
@app.get("/loi/connue")
async def loi_connue_alias(
    sujet: str = Query(...),
    scrape: bool = Query(False)
):
    """
    Alias de /loi/recherche — conservé pour compatibilité workflow n8n.
    Le paramètre scrape est ignoré (scraping toujours actif).
    """
    return await recherche_loi_par_sujet(sujet=sujet)


# ─────────────────────────────────────────────
# PARTIE 3 — UTILITAIRES
# INCHANGÉ sauf suppression de /loi/liste (dictionnaire supprimé)
# ─────────────────────────────────────────────

@app.get("/loi/debug")
async def debug_justel(sujet: str = Query(...)):
    """
    Debug : affiche les résultats bruts de Justel sans traitement.
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        try:
            await page.goto(
                "https://www.ejustice.just.fgov.be/cgi/rech.pl?language=fr",
                wait_until="networkidle",
                timeout=30000
            )
            await page.wait_for_timeout(2000)
            await page.evaluate(f"""
                const form = document.querySelector('form');
                if (form) {{
                    const input = document.querySelector('input[name="text1"]');
                    if (input) input.value = '{sujet}';
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
                    if numac not in numacs_vus:
                        numacs_vus.add(numac)
                        resultats.append({
                            "numac": numac,
                            "titre": titre[:200],
                            "url_source": construire_url_citation(numac)
                        })
            await browser.close()
            return {"total": len(resultats), "resultats": resultats}
        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
async def health():
    return {
        "status": "online",
        "version": "v4 - Scraping Justel direct, zéro dictionnaire hardcodé",
        "endpoints": {
            "jurisprudence": ["POST /scrape", "POST /lire_arret"],
            "legislation_principal": [
                "GET /loi/recherche  ← PRINCIPAL : scraping Justel direct",
                "GET /loi/numac      ← accès direct par numac + extraction articles",
                "GET /loi/article    ← article précis verbatim",
            ],
            "legislation_compatibilite": [
                "GET /loi/connue     ← alias de /loi/recherche (rétrocompatibilité)",
                "GET /loi/sujet      ← alias de /loi/recherche (rétrocompatibilité)",
            ],
            "utilitaires": [
                "GET /loi/debug      ← debug Justel brut",
                "GET /health"
            ]
        },
        "architecture": "Scraping Justel en temps réel — URLs et numac toujours valides"
    }
