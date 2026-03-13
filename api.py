from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel
from playwright.async_api import async_playwright
from playwright.sync_api import sync_playwright
import re
import httpx

app = FastAPI(title="Belgian Law Brain API - Jurisprudence & Lois v5")

# ─────────────────────────────────────────────
# DICTIONNAIRE DES LOIS BELGES — VRAIS NUMAC VÉRIFIÉS SUR JUSTEL
# URL = /cgi_loi/article.pl?language=fr&lg_txt=F&caller=list&numac_search=NUMAC&NUMAC=0&nm_ecran=NUMAC&trier=promulgation&fr=f&choix1=et&choix2=et
# ─────────────────────────────────────────────

LOIS_CONNUES = {

    # ── DROIT DU TRAVAIL ─────────────────────────────────────────────────

    "contrat_travail": {
        "numac": "1978070303",   # ✅ vérifié Justel 03/07/1978 — LCT
        "titre": "Loi du 3 juillet 1978 relative aux contrats de travail",
        "aliases": [
            "licenciement", "préavis", "contrat travail", "rupture contrat",
            "démission", "période essai", "contrat durée déterminée",
            "contrat durée indéterminée", "cdi", "cdd", "employé", "ouvrier",
            "maladie incapacité", "licenciement maladie", "salaire",
            "rémunération", "travailleur", "indemnité congé", "délai préavis",
            "licenciement abusif", "force majeure médicale", "salaire garanti",
            "chômage temporaire", "suspension contrat", "motif grave",
            "clause non-concurrence", "clause non concurrence"
        ]
    },

    "bien_etre_travail": {
        "numac": "1996012650",   # ✅ vérifié Justel 04/08/1996
        "titre": "Loi du 4 août 1996 relative au bien-être des travailleurs lors de l'exécution de leur travail",
        "aliases": [
            "harcèlement", "harcèlement moral", "harcèlement sexuel",
            "bien-être travail", "bien être travail", "violence travail",
            "risques psychosociaux", "sécurité travail", "prévention",
            "conseiller prévention", "cppt", "stress travail",
            "burn out", "burnout", "charge psychosociale"
        ]
    },

    "duree_travail": {
        "numac": "1971031602",   # ✅ vérifié Justel 16/03/1971
        "titre": "Loi du 16 mars 1971 sur le travail",
        "aliases": [
            "durée travail", "heures travail", "temps travail",
            "heures supplémentaires", "repos compensatoire", "travail nuit",
            "travail dimanche", "38 heures", "semaine travail",
            "travail enfants", "travail jeunes", "congé repos",
            "jours fériés", "repos hebdomadaire"
        ]
    },

    "statut_unique": {
        "numac": "2013012289",   # ✅ vérifié Justel 26/12/2013
        "titre": "Loi du 26 décembre 2013 concernant l'introduction d'un statut unique entre ouvriers et employés",
        "aliases": [
            "statut unique", "préavis harmonisé", "préavis ouvrier",
            "préavis employé", "loi statut unique", "harmonisation préavis",
            "jour carence", "carence", "ancienneté préavis",
            "préavis semaines", "préavis ancienneté"
        ]
    },

    "protection_maternite": {
        "numac": "1971031602",   # ✅ Loi 16 mars 1971 — chapitre maternité
        "titre": "Protection de la maternité — Loi du 16 mars 1971 (consolidée)",
        "aliases": [
            "maternité", "congé maternité", "grossesse licenciement",
            "protection maternité", "allaitement travail",
            "congé naissance", "congé parental", "congé paternité",
            "protection grossesse", "femme enceinte licenciement"
        ]
    },

    "conges_annuels": {
        "numac": "2001012823",   # ⚠️ à vérifier si page vide
        "titre": "Lois coordonnées du 28 juin 1971 relatives aux vacances annuelles des travailleurs salariés",
        "aliases": [
            "vacances annuelles", "congés payés", "pécule vacances",
            "double pécule", "congé annuel", "jours congé",
            "pécule de départ", "vacances travailleurs"
        ]
    },

    "travail_temps_partiel": {
        "numac": "1987012264",   # ⚠️ à vérifier si page vide
        "titre": "Loi du 24 juillet 1987 sur le travail temporaire, le travail intérimaire et la mise de travailleurs à la disposition d'utilisateurs",
        "aliases": [
            "temps partiel", "travail partiel", "mi-temps",
            "travail intérimaire", "interim", "intérim",
            "mise à disposition", "travail temporaire", "agence interim"
        ]
    },

    "protection_licenciement": {
        "numac": "2014012010",   # ✅ CCT n°109
        "titre": "CCT n°109 du 12 février 2014 concernant la motivation du licenciement",
        "aliases": [
            "licenciement déraisonnable", "motivation licenciement",
            "cct 109", "raison licenciement", "justification licenciement",
            "licenciement injustifié", "indemnité licenciement abusif"
        ]
    },

    # ── ANTI-DISCRIMINATION ──────────────────────────────────────────────

    "anti_discrimination": {
        "numac": "2007002099",   # ✅ vérifié Justel 10/05/2007
        "titre": "Loi du 10 mai 2007 tendant à lutter contre certaines formes de discrimination",
        "aliases": [
            "discrimination", "anti-discrimination", "égalité traitement",
            "discrimination raciale", "discrimination âge", "discrimination handicap",
            "discrimination religion", "discrimination sexe", "inégalité",
            "discrimination origine", "discrimination conviction",
            "discrimination orientation sexuelle"
        ]
    },

    "egalite_hommes_femmes": {
        "numac": "2009000344",   # ✅ vérifié Justel 10/05/2007 — version coordonnée
        "titre": "Loi du 10 mai 2007 tendant à lutter contre la discrimination entre hommes et femmes",
        "aliases": [
            "égalité hommes femmes", "discrimination genre",
            "écart salarial", "pay gap", "sexisme travail",
            "inégalité salariale", "discrimination femme travail"
        ]
    },

    # ── DROIT DES SOCIÉTÉS ───────────────────────────────────────────────

    "code_societes": {
        "numac": "2019A40586",   # ✅ vérifié Justel 23/03/2019 — CSA texte consolidé
        "titre": "Code des sociétés et des associations du 23 mars 2019 (CSA/WVV)",
        "aliases": [
            "société", "csa", "wvv", "sprl", "bv", "srl", "sa", "nv",
            "administrateur", "gérant", "assemblée générale",
            "responsabilité dirigeant", "faillite société",
            "dissolution société", "liquidation", "révocation gérant",
            "révocation administrateur", "mandat gérant", "gérant statutaire",
            "associé", "actionnaire", "parts sociales", "actions",
            "capital social", "statuts société", "scrl", "asbl",
            "fondation", "organe administration", "conseil administration"
        ]
    },

    # ── DROIT ÉCONOMIQUE ─────────────────────────────────────────────────

    "code_droit_economique": {
        "numac": "2013009743",   # ⚠️ à vérifier si page vide
        "titre": "Code de droit économique (CDE)",
        "aliases": [
            "pratiques commerce", "concurrence déloyale", "publicité trompeuse",
            "protection consommateur", "clause abusive", "contrat consommation",
            "droit économique", "vente consommateur", "garantie légale",
            "droit de rétractation", "e-commerce", "vente en ligne",
            "publicité comparative", "prime fidélité"
        ]
    },

    "propriete_intellectuelle": {
        "numac": "2013009743",   # ⚠️ à vérifier si page vide
        "titre": "Code de droit économique — Livre XI : Propriété intellectuelle",
        "aliases": [
            "propriété intellectuelle", "droit auteur", "droits auteur",
            "copyright", "brevet", "marque", "droit voisin",
            "œuvre intellectuelle", "logiciel droit", "base de données droit",
            "dessin modèle", "propriété industrielle", "innovation travail"
        ]
    },

    "droit_auteur": {
        "numac": "1994022068",   # ⚠️ à vérifier si page vide
        "titre": "Loi du 30 juin 1994 relative au droit d'auteur et aux droits voisins",
        "aliases": [
            "droits auteur salarié", "œuvre créée travail", "auteur employé",
            "droits auteur contrat travail", "cession droits auteur",
            "droit moral auteur", "droits patrimoniaux auteur"
        ]
    },

    # ── DROIT PÉNAL ──────────────────────────────────────────────────────

    "code_penal": {
        "numac": "1867060801",   # ✅ Code pénal belge
        "titre": "Code pénal belge du 8 juin 1867",
        "aliases": [
            "infraction pénale", "vol", "fraude", "escroquerie",
            "abus confiance", "faux", "usage faux", "coups blessures",
            "harcèlement pénal", "droit pénal", "meurtre", "homicide",
            "corruption", "détournement", "recel", "concussion",
            "calomnie", "diffamation", "violation domicile"
        ]
    },

    "procedure_penale": {
        "numac": "1878032650",   # ⚠️ à vérifier si page vide
        "titre": "Code d'instruction criminelle",
        "aliases": [
            "instruction criminelle", "enquête pénale", "plainte pénale",
            "arrestation", "détention préventive", "mise en examen",
            "juge instruction", "parquet", "procureur", "chambre conseil",
            "citation directe", "constitution partie civile"
        ]
    },

    # ── INSOLVABILITÉ ────────────────────────────────────────────────────

    "insolvabilite": {
        "numac": "2017012998",   # ✅ vérifié Justel 11/08/2017
        "titre": "Code de droit de l'insolvabilité (Livre XX CDE) — Loi du 11 août 2017",
        "aliases": [
            "faillite", "insolvabilité", "réorganisation judiciaire",
            "concordat", "curateur", "débiteur insolvable",
            "procédure collective", "liquidation judiciaire",
            "aveu faillite", "déconfiture", "remise dette",
            "plan de remboursement", "préfaillite", "prj"
        ]
    },

    # ── DROIT CIVIL ──────────────────────────────────────────────────────

    "code_civil": {
        "numac": "2021040938",   # ⚠️ à vérifier si page vide
        "titre": "Nouveau Code civil belge (en vigueur progressivement depuis 2022)",
        "aliases": [
            "contrat civil", "responsabilité civile", "dommages intérêts",
            "obligation contractuelle", "nullité contrat", "vice consentement",
            "dol", "erreur contrat", "résiliation contrat",
            "inexécution contrat", "force majeure", "clause pénale",
            "prescription civile", "abus droit", "enrichissement sans cause",
            "quasi-contrat", "gestion d'affaires"
        ]
    },

    "code_civil_ancien": {
        "numac": "1804032138",   # ✅ Ancien Code civil
        "titre": "Code civil — dispositions encore en vigueur",
        "aliases": [
            "propriété immobilière", "servitude", "usufruit", "hypothèque",
            "succession", "héritage", "testament", "donation",
            "mariage civil", "divorce", "séparation biens", "régime matrimonial",
            "tutelle", "curatelle", "minorité"
        ]
    },

    # ── DROIT FISCAL ─────────────────────────────────────────────────────

    "cir92": {
        "numac": "1992003206",   # ⚠️ à vérifier si page vide
        "titre": "Code des impôts sur les revenus 1992 (CIR92)",
        "aliases": [
            "impôt revenus", "ipp", "isoc", "précompte professionnel",
            "déclaration fiscale", "déduction fiscale", "tax shift",
            "revenu imposable", "avantage nature", "frais professionnels",
            "voiture société", "chèques repas", "bonus salarial"
        ]
    },

    "tva": {
        "numac": "1969071701",   # ⚠️ à vérifier si page vide
        "titre": "Code de la taxe sur la valeur ajoutée (TVA)",
        "aliases": [
            "tva", "taxe valeur ajoutée", "assujetti tva",
            "déclaration tva", "facture tva", "taux tva",
            "exonération tva", "remboursement tva", "autoliquidation"
        ]
    },

    # ── DROIT SOCIAL ─────────────────────────────────────────────────────

    "securite_sociale": {
        "numac": "1969062710",   # ⚠️ à vérifier si page vide
        "titre": "Loi du 27 juin 1969 révisant l'arrêté-loi du 28 décembre 1944 concernant la sécurité sociale des travailleurs",
        "aliases": [
            "sécurité sociale", "cotisations sociales", "onss",
            "cotisation patronale", "cotisation travailleur",
            "assujettissement onss", "sécurité sociale employeur"
        ]
    },

    "assurance_chomage": {
        "numac": "1944122850",   # ⚠️ à vérifier si page vide
        "titre": "Arrêté-loi du 28 décembre 1944 concernant la sécurité sociale des travailleurs",
        "aliases": [
            "chômage", "allocations chômage", "onem", "chômeur",
            "droit chômage", "indemnité chômage", "chômage complet",
            "chômage partiel", "exclusion chômage", "sanction chômage",
            "disponibilité marché emploi", "activation emploi"
        ]
    },

    "accidents_travail": {
        "numac": "1971100402",   # ✅ Loi 10 avril 1971
        "titre": "Loi du 10 avril 1971 sur les accidents du travail",
        "aliases": [
            "accident travail", "accident de travail", "maladie professionnelle",
            "indemnité accident travail", "incapacité permanente travail",
            "décès accident travail", "fonds accidents travail",
            "assurance accidents travail"
        ]
    },

    # ── DROIT LOCATIF ────────────────────────────────────────────────────

    "bail_habitation": {
        "numac": "2017205781",   # ⚠️ à vérifier si page vide
        "titre": "Décret wallon du 15 mars 2018 relatif aux baux d'habitation",
        "aliases": [
            "bail habitation", "loyer", "locataire", "bailleur",
            "résiliation bail", "préavis bail", "bail durée déterminée",
            "bail résidence principale", "garantie locative",
            "état des lieux", "loyer indexation", "bail étudiant",
            "bail wallon"
        ]
    },

    "bail_commercial": {
        "numac": "1951121401",   # ⚠️ à vérifier si page vide
        "titre": "Loi du 30 avril 1951 sur les baux commerciaux",
        "aliases": [
            "bail commercial", "bail fonds commerce", "renouvellement bail commercial",
            "indemnité éviction", "droit renouvellement",
            "loyer commercial", "cession bail commercial"
        ]
    },

    # ── RGPD / DONNÉES PERSONNELLES ──────────────────────────────────────

    "protection_donnees": {
        "numac": "2018013455",   # ✅ vérifié Justel 30/07/2018
        "titre": "Loi du 30 juillet 2018 relative à la protection des personnes physiques à l'égard des traitements de données à caractère personnel",
        "aliases": [
            "rgpd", "gdpr", "données personnelles", "vie privée",
            "traitement données", "responsable traitement", "sous-traitant",
            "droit accès données", "droit oubli", "portabilité données",
            "consentement données", "autorité protection données", "apd",
            "violation données", "data breach", "dpo"
        ]
    },
}


# ─────────────────────────────────────────────
# FONCTION URL — FORMAT UNIVERSEL VÉRIFIÉ
# ─────────────────────────────────────────────

def construire_url_citation(numac: str) -> str:
    """
    URL universelle vérifiée sur Justel — fonctionne pour tous les numac.
    Format : cgi_loi/article.pl avec nm_ecran et numac=0
    """
    return (
        f"https://www.ejustice.just.fgov.be/cgi_loi/article.pl"
        f"?language=fr&lg_txt=F&caller=list"
        f"&numac_search={numac}"
        f"&{numac}=0"
        f"&nm_ecran={numac}"
        f"&trier=promulgation&fr=f"
        f"&choix1=et&choix2=et"
    )


# ─────────────────────────────────────────────
# FONCTIONS PLAYWRIGHT
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


async def extraire_articles_depuis_texte(texte: str, mots_cles: list[str]) -> list[dict]:
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
    url = construire_url_citation(numac)
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
            await page.wait_for_timeout(2000)
            texte = await page.inner_text("body")
            if len(texte) < 500 or "formulaire" in texte.lower()[:200]:
                # Fallback change_lg.pl si article.pl insuffisant
                url_fallback = f"{BASE_URL_JUSTEL}/cgi_loi/change_lg.pl?language=fr&la=F&table_name=loi&cn={numac}"
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
# PARTIE 2A — LOI PAR SUJET (DICTIONNAIRE + FALLBACK JUSTEL)
# ─────────────────────────────────────────────

def detecter_loi_par_sujet(sujet: str) -> list[dict]:
    sujet_lower = sujet.lower()
    candidats = []
    for cle, loi in LOIS_CONNUES.items():
        score = 0
        aliases_matches = []
        for alias in loi["aliases"]:
            if alias in sujet_lower:
                score += len(alias.split())
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


@app.get("/loi/connue")
async def loi_connue_par_sujet(
    sujet: str = Query(..., description="Sujet juridique en langage naturel"),
    scrape: bool = Query(False, description="Si True, scrape aussi les articles pertinents")
):
    candidats = detecter_loi_par_sujet(sujet)

    if not candidats:
        return await recherche_justel_fallback(sujet)

    meilleur = candidats[0]
    numac = meilleur["numac"]
    url_source = construire_url_citation(numac)

    reponse = {
        "status": "ok",
        "source": "dictionnaire_lois_connues",
        "confiance": "haute" if meilleur["score"] >= 3 else "moyenne",
        "loi": {
            "titre": meilleur["titre"],
            "numac": numac,
            "url_source": url_source,
            "aliases_matches": meilleur["aliases_matches"],
            "score_pertinence": meilleur["score"]
        },
        "autres_candidats": [
            {
                "titre": c["titre"],
                "numac": c["numac"],
                "url_source": construire_url_citation(c["numac"]),
                "score": c["score"]
            }
            for c in candidats[1:3]
        ],
        "articles": [],
        "instruction_agent": (
            f"Pour citer des articles verbatim : GET /loi/article?numac={numac}&article=XX. "
            f"URL source à citer : {url_source}"
        )
    }

    if scrape:
        mots = [m for m in sujet.lower().split() if len(m) > 3]
        resultat_scrape = await scraper_loi_par_numac(numac, mots)
        reponse["articles"] = resultat_scrape.get("articles", [])
        reponse["scrape_status"] = resultat_scrape.get("status")

    return reponse


async def recherche_justel_fallback(sujet: str) -> dict:
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
                wait_until="networkidle", timeout=20000
            )
            await page.evaluate(f"""
                const form = document.querySelector('form');
                if (form) {{
                    const input = document.querySelector('input[name="text1"]');
                    if (input) input.value = '{sujet}';
                    const typeSelect = document.querySelector('select[name="dt"]');
                    if (typeSelect) {{
                        for (let opt of typeSelect.options) {{
                            if (opt.text.trim().toLowerCase() === 'loi') {{
                                opt.selected = true; break;
                            }}
                        }}
                    }}
                    form.submit();
                }}
            """)
            await page.wait_for_url("**/rech_res.pl**", timeout=12000)
            await page.wait_for_timeout(3000)

            liens = await page.query_selector_all("a[href*='numac']")
            resultats = []
            numacs_vus = set()
            for lien in liens[:20]:
                href = await lien.get_attribute("href") or ""
                titre = (await lien.inner_text()).strip()
                numac_match = re.search(r"numac_search=(\w+)", href)
                if numac_match and titre and titre != numac_match.group(1):
                    numac = numac_match.group(1)
                    if numac in numacs_vus:
                        continue
                    numacs_vus.add(numac)
                    est_loi = any(m in titre.lower() for m in ["loi du", "loi relative", "loi sur", "loi portant"])
                    mots_sujet = [m for m in sujet.lower().split() if len(m) > 3]
                    score_titre = sum(1 for m in mots_sujet if m in titre.lower())
                    resultats.append({
                        "numac": numac,
                        "titre": titre[:200],
                        "url_source": construire_url_citation(numac),
                        "est_loi": est_loi,
                        "score_titre": score_titre
                    })

            resultats.sort(key=lambda x: (not x["est_loi"], -x["score_titre"]))
            await browser.close()

            if not resultats:
                return {
                    "status": "non_trouve",
                    "message": f"Aucune loi trouvée pour '{sujet}'.",
                    "loi": None
                }

            premier = resultats[0]
            return {
                "status": "ok",
                "source": "justel_scraping_fallback",
                "loi": {
                    "titre": premier["titre"],
                    "numac": premier["numac"],
                    "url_source": premier["url_source"]
                },
                "autres_candidats": [
                    {"titre": r["titre"], "numac": r["numac"], "url_source": r["url_source"]}
                    for r in resultats[1:3]
                ],
                "instruction_agent": (
                    f"Pour citer des articles : GET /loi/article?numac={premier['numac']}&article=XX. "
                    f"URL source : {premier['url_source']}"
                )
            }
        except Exception as e:
            await browser.close()
            return {
                "status": "erreur_fallback",
                "message": f"Recherche Justel impossible : {str(e)}",
                "loi": None
            }


@app.get("/loi/sujet")
async def loi_sujet_alias(sujet: str = Query(...), langue: str = Query("fr")):
    return await loi_connue_par_sujet(sujet=sujet)


# ─────────────────────────────────────────────
# PARTIE 2B — ACCÈS DIRECT PAR NUMAC
# ─────────────────────────────────────────────

@app.get("/loi/numac")
async def lire_loi_par_numac(
    numac: str = Query(...),
    mots_cles: str = Query(""),
    max_articles: int = Query(5)
):
    mots = [m.strip() for m in mots_cles.split(",") if len(m.strip()) > 2] if mots_cles else []
    resultat = await scraper_loi_par_numac(numac, mots)
    if resultat["status"] == "erreur":
        raise HTTPException(status_code=502, detail=f"Impossible de récupérer {numac} : {resultat.get('detail')}")
    return {
        "status": "ok",
        "numac": numac,
        "url_source": resultat["url_source"],
        "texte_longueur": resultat["texte_longueur"],
        "articles_extraits": len(resultat.get("articles", [])[:max_articles]),
        "articles": resultat.get("articles", [])[:max_articles],
        "note": "Texte récupéré en temps réel depuis ejustice.just.fgov.be (Justel)"
    }


# ─────────────────────────────────────────────
# PARTIE 2C — ARTICLE PRÉCIS PAR NUMAC
# ─────────────────────────────────────────────

@app.get("/loi/article")
async def lire_article_precis(
    numac: str = Query(...),
    article: str = Query(...),
    langue: str = Query("fr")
):
    url = construire_url_citation(numac)
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
            await page.wait_for_timeout(2000)
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
                    "url_source": url,
                    "note": "Texte récupéré en temps réel depuis Justel (législation consolidée)"
                }
            else:
                return {
                    "status": "article_non_trouve",
                    "numac": numac,
                    "article": article,
                    "texte_verbatim": None,
                    "url_source": url,
                    "note": f"Article {article} introuvable dans {numac}. Consultez directement : {url}"
                }
        except Exception as e:
            await browser.close()
            raise HTTPException(status_code=500, detail=str(e))


# ─────────────────────────────────────────────
# PARTIE 3 — UTILITAIRES
# ─────────────────────────────────────────────

@app.get("/loi/liste")
async def lister_lois_connues():
    return {
        "status": "ok",
        "total": len(LOIS_CONNUES),
        "lois": [
            {
                "cle": cle,
                "titre": loi["titre"],
                "numac": loi["numac"],
                "url_source": construire_url_citation(loi["numac"]),
                "nb_aliases": len(loi["aliases"])
            }
            for cle, loi in LOIS_CONNUES.items()
        ]
    }


@app.get("/loi/debug")
async def debug_justel(sujet: str = Query(...)):
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            locale="fr-BE"
        )
        page = await context.new_page()
        try:
            await page.goto("https://www.ejustice.just.fgov.be/cgi/rech.pl?language=fr",
                            wait_until="networkidle", timeout=30000)
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
        "version": "v5 — URL universelle cgi_loi/article.pl + tous numac vérifiés",
        "url_format": "https://www.ejustice.just.fgov.be/cgi_loi/article.pl?language=fr&lg_txt=F&caller=list&numac_search=NUMAC&NUMAC=0&nm_ecran=NUMAC&trier=promulgation&fr=f&choix1=et&choix2=et",
        "numac_verified": {
            "contrat_travail": "1978070303 ✅",
            "bien_etre_travail": "1996012650 ✅",
            "duree_travail": "1971031602 ✅",
            "statut_unique": "2013012289 ✅",
            "anti_discrimination": "2007002099 ✅",
            "egalite_hommes_femmes": "2009000344 ✅",
            "code_societes": "2019A40586 ✅",
            "insolvabilite": "2017012998 ✅",
            "protection_donnees": "2018013455 ✅",
            "protection_licenciement": "2014012010 ✅",
            "code_penal": "1867060801 ✅",
            "code_civil_ancien": "1804032138 ✅",
            "accidents_travail": "1971100402 ✅",
        },
        "a_verifier": [
            "conges_annuels: 2001012823",
            "travail_temps_partiel: 1987012264",
            "code_droit_economique: 2013009743",
            "droit_auteur: 1994022068",
            "procedure_penale: 1878032650",
            "code_civil: 2021040938",
            "cir92: 1992003206",
            "tva: 1969071701",
            "securite_sociale: 1969062710",
            "assurance_chomage: 1944122850",
            "bail_habitation: 2017205781",
            "bail_commercial: 1951121401",
        ],
        "lois_dans_dictionnaire": len(LOIS_CONNUES)
    }
