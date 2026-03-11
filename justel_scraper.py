"""
JUSTEL SCRAPER — Belgian Law Brain
Scrape ejustice.just.fgov.be pour récupérer les articles de loi en temps réel.

Endpoints FastAPI à ajouter à ton projet Railway existant :
  GET /loi/recherche?q=licenciement+maladie&langue=fr
  GET /loi/article?numac=1978070301&article=34
  GET /loi/texte-complet?numac=1978070301
"""

from fastapi import FastAPI, HTTPException, Query
from playwright.async_api import async_playwright
import asyncio
import re
from typing import Optional

app = FastAPI()

# ─────────────────────────────────────────────
# CONSTANTES
# ─────────────────────────────────────────────

BASE_URL = "https://www.ejustice.just.fgov.be"

# Numac des lois les plus demandées (cache rapide)
LOIS_CONNUES = {
    "loi_1978": "1978070301",           # Loi contrats de travail 3 juillet 1978
    "code_bienetre": "1996012650",      # Code du bien-être au travail
    "loi_1971": "1971030655",           # Loi 16 mars 1971 sur le travail
    "anti_discrimination": "2007002099", # Loi anti-discrimination 10 mai 2007
    "code_penal": "1867060801",         # Code pénal
    "statut_unique": "2013122601",      # Loi statut unique 2013
}


# ─────────────────────────────────────────────
# ENDPOINT 1 — RECHERCHE PAR MOTS-CLÉS
# ─────────────────────────────────────────────

@app.get("/loi/recherche")
async def recherche_loi(
    q: str = Query(..., description="Mots-clés, ex: 'licenciement maladie protection'"),
    langue: str = Query("fr", description="fr ou nl")
):
    """
    Recherche une loi par mots-clés dans Justel.
    Retourne les 5 premiers résultats avec numac, titre, date.

    Exemple : GET /loi/recherche?q=licenciement+maladie+incapacite+travail
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # URL de recherche Justel
            search_url = (
                f"{BASE_URL}/cgi_loi/loi.pl"
                f"?language={langue}&la={langue.upper()}"
                f"&cn=&table_name=loi&caller=list"
                f"&F=&nature=&numac=&pub=&pdp=&ddfrom=2000-01-01"
                f"&txttype=&type=all&sort=pub-desc"
                f"&return_checksb=0&rowid=0&rech={q.replace(' ', '+')}"
            )

            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            # Parser les résultats
            resultats = []
            rows = await page.query_selector_all("table tr")

            for row in rows[1:6]:  # Max 5 résultats
                try:
                    cells = await row.query_selector_all("td")
                    if len(cells) < 3:
                        continue

                    # Extraire le lien et le numac
                    link_el = await cells[0].query_selector("a")
                    if not link_el:
                        continue

                    href = await link_el.get_attribute("href") or ""
                    titre = await link_el.inner_text()
                    titre = titre.strip()

                    # Extraire le numac depuis le href
                    numac_match = re.search(r"numac[_=](\w+)", href)
                    numac = numac_match.group(1) if numac_match else ""

                    # Date de publication
                    date_text = ""
                    if len(cells) > 1:
                        date_text = (await cells[1].inner_text()).strip()

                    if titre and numac:
                        resultats.append({
                            "numac": numac,
                            "titre": titre,
                            "date": date_text,
                            "url_texte": f"{BASE_URL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel",
                        })
                except Exception:
                    continue

            await browser.close()

            if not resultats:
                return {
                    "status": "aucun_resultat",
                    "message": f"Aucune loi trouvée pour : {q}",
                    "resultats": []
                }

            return {
                "status": "ok",
                "query": q,
                "total": len(resultats),
                "resultats": resultats
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur scraping recherche: {str(e)}")


# ─────────────────────────────────────────────
# ENDPOINT 2 — LIRE UN ARTICLE PRÉCIS
# ─────────────────────────────────────────────

@app.get("/loi/article")
async def lire_article(
    numac: str = Query(..., description="Numéro numac de la loi, ex: 1978070301"),
    article: str = Query(..., description="Numéro d'article, ex: 34 ou 34§1"),
    langue: str = Query("fr", description="fr ou nl")
):
    """
    Récupère le texte exact d'un article d'une loi.
    Retourne le texte verbatim tel que publié sur ejustice.

    Exemple : GET /loi/article?numac=1978070301&article=34
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # URL directe vers la loi consolidée
            url = f"{BASE_URL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"

            await page.goto(url, wait_until="networkidle", timeout=30000)

            # Chercher l'article dans le texte
            texte_complet = await page.inner_text("body")

            # Nettoyer le texte
            texte_complet = re.sub(r'\n{3,}', '\n\n', texte_complet)

            # Extraire l'article demandé
            article_num = article.replace("§", "").replace(" ", "").strip()

            # Patterns pour trouver l'article
            patterns = [
                rf"Art\.?\s*{re.escape(article)}[\s\.](.+?)(?=Art\.?\s*\d|$)",
                rf"Article\s*{re.escape(article)}[\s\.](.+?)(?=Article\s*\d|Art\.?\s*\d|$)",
                rf"Art\.\s*{re.escape(article_num)}[\s\.](.+?)(?=Art\.\s*\d|$)",
            ]

            texte_article = None
            for pattern in patterns:
                match = re.search(pattern, texte_complet, re.DOTALL | re.IGNORECASE)
                if match:
                    texte_article = match.group(0).strip()
                    # Limiter à 2000 caractères max
                    texte_article = texte_article[:2000]
                    break

            await browser.close()

            if not texte_article:
                return {
                    "status": "article_non_trouve",
                    "numac": numac,
                    "article": article,
                    "message": f"Article {article} non trouvé dans la loi {numac}. Vérifiez le numéro.",
                    "url_source": url
                }

            # Extraire le titre de la loi
            titre_match = re.search(r"(\d+\s+\w+\s+\d{4}[^\.]+)", texte_complet[:500])
            titre_loi = titre_match.group(1).strip() if titre_match else f"Loi numac {numac}"

            return {
                "status": "ok",
                "numac": numac,
                "titre_loi": titre_loi,
                "article": article,
                "texte_verbatim": texte_article,
                "url_source": url,
                "langue": langue
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur scraping article: {str(e)}")


# ─────────────────────────────────────────────
# ENDPOINT 3 — RECHERCHE INTELLIGENTE PAR SUJET
# ─────────────────────────────────────────────

@app.get("/loi/sujet")
async def recherche_par_sujet(
    sujet: str = Query(..., description="Sujet juridique, ex: 'licenciement maladie secteur public'"),
    langue: str = Query("fr", description="fr ou nl")
):
    """
    Endpoint principal utilisé par le bot n8n.
    Prend un sujet juridique, trouve la loi la plus pertinente,
    et retourne les articles les plus pertinents avec leur texte verbatim.

    Exemple : GET /loi/sujet?sujet=licenciement+maladie+incapacité+travail
    """
    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            # Construire la requête de recherche
            mots_cles = sujet.replace(" ", "+")

            search_url = (
                f"{BASE_URL}/cgi_loi/loi.pl"
                f"?language={langue}&la={langue.upper()}"
                f"&cn=&table_name=loi&caller=list"
                f"&nature=&sort=pub-desc&rech={mots_cles}"
            )

            await page.goto(search_url, wait_until="networkidle", timeout=30000)

            # Trouver le premier résultat pertinent
            first_link = await page.query_selector("table tr:nth-child(2) td a")

            if not first_link:
                await browser.close()
                return {
                    "status": "aucun_resultat",
                    "sujet": sujet,
                    "message": "Aucune loi trouvée pour ce sujet sur ejustice.just.fgov.be",
                    "articles": []
                }

            href = await first_link.get_attribute("href") or ""
            titre_loi = (await first_link.inner_text()).strip()

            # Extraire numac
            numac_match = re.search(r"numac[_=](\w+)", href)
            numac = numac_match.group(1) if numac_match else ""

            if not numac:
                await browser.close()
                return {"status": "erreur_numac", "message": "Impossible d'extraire le numac"}

            # Aller lire la loi complète
            loi_url = f"{BASE_URL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"
            await page.goto(loi_url, wait_until="networkidle", timeout=30000)

            texte_complet = await page.inner_text("body")
            texte_complet = re.sub(r'\n{3,}', '\n\n', texte_complet)

            # Extraire les articles pertinents (ceux qui mentionnent les mots-clés)
            mots = sujet.lower().split()
            articles_trouves = []

            # Découper par article
            blocs = re.split(r'(?=Art\.?\s*\d)', texte_complet)

            for bloc in blocs[:50]:  # Max 50 articles à analyser
                bloc_lower = bloc.lower()
                score = sum(1 for mot in mots if mot in bloc_lower and len(mot) > 3)

                if score >= 2:  # Au moins 2 mots-clés trouvés
                    # Extraire le numéro d'article
                    art_match = re.match(r'Art\.?\s*(\d+[^\.\n]*)', bloc)
                    art_num = art_match.group(1).strip() if art_match else "?"

                    articles_trouves.append({
                        "article": art_num,
                        "texte": bloc.strip()[:800],  # 800 chars max par article
                        "score_pertinence": score
                    })

            # Trier par pertinence
            articles_trouves.sort(key=lambda x: x["score_pertinence"], reverse=True)
            articles_top = articles_trouves[:3]  # Top 3

            await browser.close()

            return {
                "status": "ok",
                "sujet": sujet,
                "loi_trouvee": titre_loi,
                "numac": numac,
                "url_source": loi_url,
                "articles": articles_top,
                "total_articles_pertinents": len(articles_trouves)
            }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur scraping sujet: {str(e)}")


# ─────────────────────────────────────────────
# ENDPOINT 4 — ACCÈS DIRECT PAR NUMAC CONNU
# ─────────────────────────────────────────────

@app.get("/loi/numac")
async def loi_par_numac(
    numac: str = Query(..., description="Numac exact, ex: 1978070301"),
    article: Optional[str] = Query(None, description="Article spécifique (optionnel)"),
    langue: str = Query("fr", description="fr ou nl")
):
    """
    Accès direct à une loi par son numac.
    Si article est fourni, retourne uniquement cet article.
    Sinon retourne les 10 premiers articles.

    Lois connues :
      loi_1978         → 1978070301  (contrats de travail)
      code_bienetre    → 1996012650  (bien-être au travail)
      loi_1971         → 1971030655  (loi sur le travail)
      anti_discrim     → 2007002099  (anti-discrimination)
    """
    # Résoudre les alias
    if numac in LOIS_CONNUES:
        numac = LOIS_CONNUES[numac]

    url = f"{BASE_URL}/eli/loi/{numac[:4]}/{numac[4:6]}/{numac[6:8]}/{numac}/justel"

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            await page.goto(url, wait_until="networkidle", timeout=30000)
            texte_complet = await page.inner_text("body")
            texte_complet = re.sub(r'\n{3,}', '\n\n', texte_complet)

            # Titre de la loi
            titre_match = re.search(r"(\d+\s+\w+\s+\d{4}[^\.]{10,80})", texte_complet[:300])
            titre = titre_match.group(1).strip() if titre_match else f"Loi {numac}"

            if article:
                # Chercher l'article précis
                patterns = [
                    rf"Art\.?\s*{re.escape(article)}[\s\.\-](.+?)(?=Art\.?\s*\d|\Z)",
                    rf"Article\s+{re.escape(article)}[\s\.\-](.+?)(?=Art|\Z)",
                ]
                texte_art = None
                for pat in patterns:
                    m = re.search(pat, texte_complet, re.DOTALL | re.IGNORECASE)
                    if m:
                        texte_art = m.group(0)[:1500].strip()
                        break

                await browser.close()
                return {
                    "status": "ok" if texte_art else "article_non_trouve",
                    "numac": numac,
                    "titre_loi": titre,
                    "article": article,
                    "texte_verbatim": texte_art or "Article non trouvé",
                    "url_source": url
                }
            else:
                # Retourner les 10 premiers articles
                blocs = re.split(r'(?=Art\.?\s*\d)', texte_complet)
                premiers_articles = []
                for bloc in blocs[1:11]:
                    art_match = re.match(r'Art\.?\s*(\S+)', bloc)
                    art_num = art_match.group(1) if art_match else "?"
                    premiers_articles.append({
                        "article": art_num,
                        "texte": bloc.strip()[:600]
                    })

                await browser.close()
                return {
                    "status": "ok",
                    "numac": numac,
                    "titre_loi": titre,
                    "url_source": url,
                    "premiers_articles": premiers_articles
                }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erreur accès numac {numac}: {str(e)}")


# ─────────────────────────────────────────────
# ENDPOINT 5 — HEALTH CHECK
# ─────────────────────────────────────────────

@app.get("/loi/health")
async def health():
    return {
        "status": "ok",
        "service": "Justel Scraper — Belgian Law Brain",
        "endpoints": [
            "GET /loi/recherche?q=mots+cles",
            "GET /loi/article?numac=1978070301&article=34",
            "GET /loi/sujet?sujet=licenciement+maladie",
            "GET /loi/numac?numac=1978070301&article=34",
        ],
        "lois_connues": list(LOIS_CONNUES.keys())
    }
