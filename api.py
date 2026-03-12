from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import re
import httpx

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois v2")

# ─────────────────────────────────────────────
# DICTIONNAIRE DES LOIS BELGES CONNUES
# Clé : alias sémantiques multiples → valeur : numac + métadonnées
# ─────────────────────────────────────────────

LOIS_CONNUES = {
    # ── Droit du travail ──────────────────────────────────────────────────
    "contrat_travail": {
        "numac": "1978070301",
        "titre": "Loi du 3 juillet 1978 relative aux contrats de travail",
        "aliases": [
            "licenciement", "préavis", "contrat travail", "rupture contrat",
            "démission", "période essai", "contrat durée déterminée",
            "contrat durée indéterminée", "cdi", "cdd", "employé", "ouvrier",
            "maladie incapacité", "licenciement maladie", "salaire",
            "rémunération", "travailleur"
        ]
    },
    "bien_etre_travail": {
        "numac": "1996060304",
        "titre": "Loi du 4 août 1996 relative au bien-être des travailleurs",
        "aliases": [
            "harcèlement", "harcèlement moral", "harcèlement sexuel",
            "bien-être travail", "bien être travail", "violence travail",
            "risques psychosociaux", "sécurité travail", "prévention",
            "conseiller prévention", "cppt", "stress travail"
        ]
    },
    "duree_travail": {
        "numac": "1971030655",
        "titre": "Loi du 16 mars 1971 sur le travail",
        "aliases": [
            "durée travail", "heures travail", "temps travail",
            "heures supplémentaires", "repos compensatoire", "travail nuit",
            "travail dimanche", "38 heures", "semaine travail"
        ]
    },
    "statut_unique": {
        "numac": "2013200006",
        "titre": "Loi du 26 décembre 2013 concernant l'introduction d'un statut unique",
        "aliases": [
            "statut unique", "préavis harmonisé", "préavis ouvrier",
            "préavis employé", "loi statut unique", "harmonisation préavis",
            "carenz jour", "jour carence"
        ]
    },
    "protection_maternite": {
        "numac": "2002012347",
        "titre": "Loi du 16 mars 1971 - protection maternité (AR consolidé)",
        "aliases": [
            "maternité", "congé maternité", "grossesse licenciement",
            "protection maternité", "allaitement travail"
        ]
    },

    # ── Anti-discrimination ───────────────────────────────────────────────
    "anti_discrimination": {
        "numac": "2007002099",
        "titre": "Loi du 10 mai 2007 tendant à lutter contre certaines formes de discrimination",
        "aliases": [
            "discrimination", "anti-discrimination", "égalité traitement",
            "discrimination raciale", "discrimination âge", "discrimination handicap",
            "discrimination religion", "discrimination sexe", "inégalité"
        ]
    },
    "egalite_hommes_femmes": {
        "numac": "2007002098",
        "titre": "Loi du 10 mai 2007 tendant à lutter contre la discrimination entre hommes et femmes",
        "aliases": [
            "égalité hommes femmes", "discrimination genre",
            "écart salarial", "pay gap", "sexisme travail"
        ]
    },

    # ── Droit des sociétés ────────────────────────────────────────────────
    "code_societes": {
        "numac": "2019040723",
        "titre": "Code des sociétés et des associations (CSA/WVV)",
        "aliases": [
            "société", "csa", "wvv", "sprl", "bv", "sa", "nv",
            "administrateur", "gérant", "assemblée générale",
            "responsabilité dirigeant", "faillite société",
            "dissolution société", "liquidation"
        ]
    },

    # ── Droit économique ──────────────────────────────────────────────────
    "code_droit_economique": {
        "numac": "2013009743",
        "titre": "Code de droit économique (CDE)",
        "aliases": [
            "pratiques commerce", "concurrence déloyale", "publicité trompeuse",
            "protection consommateur", "clause abusive", "contrat consommation",
            "droit économique"
        ]
    },

    # ── Droit pénal ───────────────────────────────────────────────────────
    "code_penal": {
        "numac": "1867060801",
        "titre": "Code pénal belge",
        "aliases": [
            "infraction pénale", "vol", "fraude", "escroquerie",
            "abus confiance", "faux", "usage faux", "coups blessures",
            "harcèlement pénal", "droit pénal"
        ]
    },

    # ── Insolvabilité ─────────────────────────────────────────────────────
    "insolvabilite": {
        "numac": "2017030524",
        "titre": "Code de droit de l'insolvabilité (Livre XX CDE)",
        "aliases": [
            "faillite", "insolvabilité", "réorganisation judiciaire",
            "concordat", "curateur", "débiteur insolvable",
            "procédure collective", "liquidation judiciaire"
        ]
    },
}


# ─────────────────────────────────────────────
# FONCTION DE MATCHING SÉMANTIQUE
# ─────────────────────────────────────────────

def detecter_loi_par_sujet(sujet: str) -> list[dict]:
    """
    Retourne les lois candidates triées par score de pertinence.
    Score = nombre d'aliases matchés dans le sujet.
    """
    sujet_lower = sujet.lower()
    candidats = []

    for cle, loi in LOIS_CONNUES.items():
        score = 0
        aliases_matches = []
        for alias in loi["aliases"]:
            if alias in sujet_lower:
                score += len(alias.split())  # pondérer par longueur de l'alias
                aliases_matches.append(alias)
        if score > 0:
            candidats.append({
                "cle": cle,
                "numac": loi["numac"],
                "titre": loi["titre"],
                "score": score,
                "aliases_matches": aliases_matches
            })

    candidats.sort(key=lambda x: x["score"], reverse=True)
    return candidats


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


def construire_url_justel(numac: str) -> str:
    """
    Construit l'URL directe vers le texte consolidé d'une loi via son numac.
    Format ELI : /eli/loi/YYYY/MM/DD/NUMAC/justel
    """
    if len(numac) >= 8:
        annee = numac[:4]
        mois = numac[4:6]
        jour = numac[6:8]
        return f"{BASE_URL_JUSTEL}/eli/loi/{annee}/{mois}/{jour}/{numac}/justel"
    # Fallback sur l'ancienne URL CGI
    return f"{BASE_URL_JUSTEL}/cgi/loi_a1.pl?NUMAC={numac}&language=fr"


async def extraire_articles_depuis_texte(texte: str, mots_cles: list[str]) -> list[dict]:
    """
    Extrait et score les articles d'un texte de loi selon les mots-clés.
    Stratégie : split sur 'Art.' → score par occurrences de mots-clés.
    """
    texte = re.sub(r'\n{3,}', '\n\n', texte)
    blocs = re.split(r'(?=\bArt(?:icle)?\.?\s*\d)', texte)

    articles = []
    for bloc in blocs[:120]:  # limite à 120 blocs pour perf
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
    Retourne le texte brut + les articles pertinents si mots_cles fournis.
    """
    url = construire_url_justel(numac)
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
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(1500)

            # Vérifier si on a bien une page de loi (pas une homepage)
            titre_page = await page.title()
            texte = await page.inner_text("body")

            if len(texte) < 500 or "formulaire" in texte.lower()[:200]:
                # Fallback sur URL CGI alternative
                url_fallback = f"{BASE_URL_JUSTEL}/cgi/loi_a1.pl?NUMAC={numac}&language=fr"
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
                "url_source": url,
                "texte_longueur": len(texte),
                "articles": articles
            }

        except Exception as e:
            await browser.close()
            return {"status": "erreur", "numac": numac, "detail": str(e)}


# ─────────────────────────────────────────────
# PARTIE 1 — JURISPRUDENCE (JUPORTAL)
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
# PARTIE 2A — LÉGISLATION : LOI CONNUE PAR SUJET
# Endpoint principal — matching sémantique sur dictionnaire
# ─────────────────────────────────────────────

@app.get("/loi/connue")
async def loi_connue_par_sujet(
    sujet: str = Query(..., description="Sujet juridique en langage naturel"),
    scrape: bool = Query(False, description="Si True, scrape aussi le texte depuis Justel")
):
    """
    Identifie la loi belge applicable à un sujet via matching sémantique.
    
    - Retourne toujours la loi + son numac + son URL Justel.
    - Si scrape=True : va chercher les articles pertinents en temps réel.
    - Utilisé en PREMIER par l'agent n8n avant tout appel Pinecone ou Justel.
    
    Exemple : GET /loi/connue?sujet=licenciement+maladie&scrape=false
    """
    candidats = detecter_loi_par_sujet(sujet)

    if not candidats:
        return {
            "status": "non_trouve",
            "message": (
                f"Aucune loi connue identifiée pour '{sujet}'. "
                "Utilisez /loi/sujet pour une recherche Justel en temps réel, "
                "ou consultez Pinecone via RAG."
            ),
            "suggestion": "loi/sujet",
            "loi": None
        }

    meilleur = candidats[0]
    numac = meilleur["numac"]
    url_justel = construire_url_justel(numac)

    reponse = {
        "status": "ok",
        "source": "dictionnaire_lois_connues",
        "confiance": "haute" if meilleur["score"] >= 3 else "moyenne",
        "loi": {
            "titre": meilleur["titre"],
            "numac": numac,
            "url_justel": url_justel,
            "aliases_matches": meilleur["aliases_matches"],
            "score_pertinence": meilleur["score"]
        },
        "autres_candidats": [
            {"titre": c["titre"], "numac": c["numac"], "score": c["score"]}
            for c in candidats[1:3]
        ],
        "articles": [],
        "instruction_agent": (
            f"Pour citer des articles verbatim : appelle GET /loi/article?numac={numac}&article=XX. "
            f"Ou interroge Pinecone avec le numac {numac} pour les chunks déjà indexés."
        )
    }

    # Si scrape demandé : aller chercher les articles pertinents
    if scrape:
        mots = [m for m in sujet.lower().split() if len(m) > 3]
        resultat_scrape = await scraper_loi_par_numac(numac, mots)
        reponse["articles"] = resultat_scrape.get("articles", [])
        reponse["scrape_status"] = resultat_scrape.get("status")
        reponse["texte_longueur"] = resultat_scrape.get("texte_longueur", 0)

    return reponse


# ─────────────────────────────────────────────
# PARTIE 2B — LÉGISLATION : ACCÈS DIRECT PAR NUMAC
# Utilisé quand on connaît déjà le numac (depuis /loi/connue ou Pinecone)
# ─────────────────────────────────────────────

@app.get("/loi/numac")
async def lire_loi_par_numac(
    numac: str = Query(..., description="Numéro NUMAC de la loi (ex: 1978070301)"),
    mots_cles: str = Query("", description="Mots-clés séparés par des virgules pour filtrer les articles"),
    max_articles: int = Query(5, description="Nombre max d'articles retournés")
):
    """
    Récupère le texte d'une loi depuis Justel via son numac.
    
    - URL directe ELI : /eli/loi/YYYY/MM/DD/NUMAC/justel (HTML statique, pas de JS requis)
    - Extrait les articles pertinents si mots_cles fournis.
    - Retourne aussi l'URL source pour citation.
    
    Exemple : GET /loi/numac?numac=1978070301&mots_cles=maladie,licenciement
    """
    mots = [m.strip() for m in mots_cles.split(",") if len(m.strip()) > 2] if mots_cles else []
    resultat = await scraper_loi_par_numac(numac, mots)

    if resultat["status"] == "erreur":
        raise HTTPException(
            status_code=502,
            detail=f"Impossible de récupérer la loi {numac} depuis Justel : {resultat.get('detail')}"
        )

    # Limiter au max demandé
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
# Inchangé mais URL améliorée + fallback
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
    → Retourne l'article 38 de la Loi du 3 juillet 1978.
    """
    url = construire_url_justel(numac)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        await page.route("**/*", bloquer_ressources)

        try:
            await page.goto(url, wait_until="networkidle", timeout=45000)
            await page.wait_for_timeout(1500)
            texte = await page.inner_text("body")
            texte = re.sub(r'\n{3,}', '\n\n', texte)

            # Patterns de recherche d'article (robuste aux variantes belges)
            article_escape = re.escape(article)
            patterns = [
                rf"\bArt(?:icle)?\.?\s*{article_escape}[°\.\-\s](.+?)(?=\bArt(?:icle)?\.?\s*\d|\Z)",
                rf"\bArt(?:icle)?\.?\s*{article_escape}[°\.\-\s](.+?)(?=\n\n\n|\Z)",
            ]

            texte_art = None
            for pat in patterns:
                m = re.search(pat, texte, re.DOTALL | re.IGNORECASE)
                if m:
                    texte_art = m.group(0)[:2000].strip()
                    break

            await browser.close()

            if texte_art:
                return {
                    "status": "ok",
                    "numac": numac,
                    "article": article,
                    "texte_verbatim": texte_art,
                    "url_source": url,
                    "note": "Texte récupéré en temps réel depuis Justel"
                }
            else:
                return {
                    "status": "article_non_trouve",
                    "numac": numac,
                    "article": article,
                    "texte_verbatim": None,
                    "url_source": url,
                    "note": (
                        f"Article {article} introuvable dans la loi {numac}. "
                        "Vérifiez le numéro d'article ou consultez l'URL source directement."
                    )
                }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 2D — RECHERCHE JUSTEL (ancienne /loi/sujet améliorée)
# Utilisée en FALLBACK si /loi/connue ne trouve rien
# ─────────────────────────────────────────────

@app.get("/loi/sujet")
async def recherche_par_sujet_justel(
    sujet: str = Query(...),
    langue: str = Query("fr")
):
    """
    Recherche une loi sur Justel par sujet (scraping formulaire).
    ATTENTION : résultats triés par date décroissante côté Justel.
    
    ⚠️  Utiliser /loi/connue EN PREMIER.
    Ce endpoint est un FALLBACK pour les lois non présentes dans le dictionnaire.
    Le scoring de pertinence est appliqué mais reste limité.
    """
    # Vérifier d'abord si on connaît la loi
    candidats_connus = detecter_loi_par_sujet(sujet)
    if candidats_connus and candidats_connus[0]["score"] >= 2:
        meilleur = candidats_connus[0]
        return {
            "status": "redirige",
            "message": (
                f"Loi identifiée dans le dictionnaire interne avec confiance haute. "
                f"Utilisez plutôt GET /loi/connue?sujet={sujet} pour un résultat fiable."
            ),
            "loi_suggeree": {
                "titre": meilleur["titre"],
                "numac": meilleur["numac"],
                "url_justel": construire_url_justel(meilleur["numac"])
            }
        }

    # Fallback : recherche Justel via Playwright
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
                        for mot in ["loi du", "loi relative", "loi sur", "loi portant", "loi du "]
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
                        "url_loi": f"https://www.ejustice.just.fgov.be/cgi/{href}",
                        "est_loi": est_loi,
                        "est_cct": est_cct,
                        "score_titre": score_titre
                    })

            # Tri : lois générales > score titre > non-CCT
            resultats.sort(key=lambda x: (not x["est_loi"], x["est_cct"], -x["score_titre"]))

            if not resultats:
                await browser.close()
                return {
                    "status": "aucun_resultat",
                    "message": "Aucun résultat Justel. Vérifiez le sujet ou élargissez la recherche.",
                    "articles": []
                }

            premier = resultats[0]
            await page.goto(premier["url_loi"], wait_until="networkidle", timeout=30000)
            await page.wait_for_timeout(2000)
            texte_complet = await page.inner_text("body")

            mots = [m for m in sujet.lower().split() if len(m) > 3]
            articles = await extraire_articles_depuis_texte(texte_complet, mots)

            await browser.close()
            return {
                "status": "ok",
                "source": "justel_scraping_fallback",
                "avertissement": (
                    "Résultat issu du scraping Justel (tri par date). "
                    "Vérifiez que la loi retournée est bien celle applicable."
                ),
                "loi": premier["titre"],
                "numac": premier["numac"],
                "url_source": premier["url_loi"],
                "autres_resultats": [r["titre"] for r in resultats[1:3]],
                "articles": articles
            }

        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 3 — UTILITAIRES
# ─────────────────────────────────────────────

@app.get("/loi/liste")
async def lister_lois_connues():
    """
    Liste toutes les lois du dictionnaire interne avec leur numac et URL Justel.
    Utile pour l'agent n8n pour connaître la couverture du dictionnaire.
    """
    return {
        "status": "ok",
        "total": len(LOIS_CONNUES),
        "lois": [
            {
                "cle": cle,
                "titre": loi["titre"],
                "numac": loi["numac"],
                "url_justel": construire_url_justel(loi["numac"]),
                "nb_aliases": len(loi["aliases"])
            }
            for cle, loi in LOIS_CONNUES.items()
        ]
    }


@app.get("/loi/debug")
async def debug_justel(sujet: str = Query(...)):
    """
    Debug : affiche les résultats bruts de Justel sans traitement.
    À supprimer en production.
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
                            "url_loi": f"https://www.ejustice.just.fgov.be/cgi/{href}"
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
        "version": "v3 - Dictionnaire lois + Numac direct + RAG fallback",
        "endpoints": {
            "jurisprudence": ["POST /scrape", "POST /lire_arret"],
            "legislation_principal": [
                "GET /loi/connue   ← PRINCIPAL : matching sémantique dictionnaire",
                "GET /loi/numac    ← accès direct par numac + extraction articles",
                "GET /loi/article  ← article précis verbatim",
            ],
            "legislation_fallback": [
                "GET /loi/sujet    ← FALLBACK : scraping Justel (si hors dictionnaire)",
            ],
            "utilitaires": [
                "GET /loi/liste    ← liste toutes les lois connues",
                "GET /loi/debug    ← debug Justel brut (supprimer en prod)",
                "GET /health"
            ]
        },
        "lois_dans_dictionnaire": len(LOIS_CONNUES)
    }
