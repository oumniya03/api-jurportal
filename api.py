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

# --- OUTIL 1 : RECHERCHE GLOBALE — RETOURNE LA LISTE DES ECLI TRIÉS ---
@app.post("/scrape")
def scrape_jurisprudence(query: QueryModel):
    mot_cle = query.mot_cle

    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.route("**/*", bloquer_ressources_inutiles)

            page.goto("https://juportal.be/moteur/formulaire")
            page.locator("input#texpression").fill(mot_cle)
            page.locator("button[type='submit']:has-text('Rechercher')").first.click()
            page.wait_for_timeout(3000)

            liens_elements = page.locator("a[href*='ECLI']").element_handles()
            liens_pertinents = {}

            for lien in liens_elements:
                url = lien.get_attribute("href")
                if url and "ECLI" in url:
                    url_propre = url.split('?')[0].split('#')[0]
                    # Extraire l'ECLI complet depuis l'URL
                    match_ecli = re.search(r"(ECLI:BE:[A-Z]+:\d{4}:[A-Z0-9.]+)", url_propre)
                    match_annee = re.search(r"ECLI:BE:[A-Z]+:(\d{4}):", url_propre)
                    if match_ecli and match_annee:
                        ecli = match_ecli.group(1)
                        annee = int(match_annee.group(1))
                        url_complete = "https://juportal.be" + url_propre
                        # Filtre : uniquement jurisprudence récente (>= 2019)
                        if annee >= 2019:
                            liens_pertinents[url_complete] = (annee, ecli)

            # Trier du plus récent au plus ancien
            liens_tries = sorted(liens_pertinents.items(), key=lambda item: item[1][0], reverse=True)

            # ✅ CORRECTION CRUCIALE : Retourner la LISTE des ECLI avec URLs
            # L'IA pourra comparer avec Dernier_ECLI_Connu sans visiter chaque page
            resultats_liste = []
            for url, (annee, ecli) in liens_tries[:20]:  # Max 20 résultats
                resultats_liste.append({
                    "ecli": ecli,
                    "annee": annee,
                    "url": url
                })

            browser.close()

            # Format texte lisible pour l'IA
            resultats_texte = f"--- LISTE DES ARRÊTS TROUVÉS POUR '{mot_cle}' (triés du plus récent au plus ancien) ---\n\n"
            for i, r in enumerate(resultats_liste):
                resultats_texte += f"ARR{i+1}: ECLI={r['ecli']} | ANNÉE={r['annee']} | URL={r['url']}\n"

            resultats_texte += f"\nTOTAL: {len(resultats_liste)} arrêts trouvés."

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

            page.route("**/*", bloquer_ressources_inutiles)

            page.goto(url)
            page.wait_for_timeout(2000)

            texte_complet = page.locator("body").inner_text()

            if len(texte_complet) > 10000:
                texte_limite = texte_complet[:5000] + "\n\n[... PARTIE CENTRALE COUPÉE POUR ALLÉGER LA LECTURE ...]\n\n" + texte_complet[-5000:]
            else:
                texte_limite = texte_complet

            # Extraire l'ECLI depuis l'URL pour confirmation
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
