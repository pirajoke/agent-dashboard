"""Fixed public information pages for the private JARVIS–DOCXX module.

These pages read no runtime state and make no API calls. Only the three exact
routes below are public; the owner dashboard keeps its existing authorization.
"""
from __future__ import annotations

import base64
import hashlib
from types import MappingProxyType


STYLE = """
:root{color-scheme:light;--ink:#182e32;--muted:#50656a;--accent:#126b60;--line:#d6e0dc;--paper:#f7f8f4}
*{box-sizing:border-box}html{scroll-behavior:auto}body{margin:0;background:var(--paper);color:var(--ink);font:17px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
a{color:var(--accent);text-underline-offset:.22em}a:hover{text-decoration-thickness:2px}a:focus-visible{outline:3px solid var(--accent);outline-offset:5px;border-radius:2px}
.skip{position:absolute;left:20px;top:-80px;background:white;padding:8px 14px;z-index:2}.skip:focus{top:12px}
.wrap{width:min(100% - 48px,1040px);margin-inline:auto}header{padding:28px 0 22px;border-bottom:1px solid var(--line)}.masthead{display:flex;justify-content:space-between;gap:24px;align-items:center;flex-wrap:wrap}
.brand{font-weight:750;letter-spacing:-.035em;font-size:22px;text-decoration:none;color:var(--ink)}.brand span{color:var(--accent)}nav{display:flex;gap:22px;flex-wrap:wrap;font-size:14px}nav a{color:var(--muted);text-decoration:none}nav a[aria-current="page"]{color:var(--ink);text-decoration:underline;text-decoration-thickness:2px}
main{padding:58px 0 64px}.eyebrow{font-size:12px;text-transform:uppercase;letter-spacing:.13em;font-weight:700;color:var(--accent);margin:0 0 18px}h1{font:500 clamp(32px,5vw,52px)/1.12 Georgia,"Times New Roman",serif;letter-spacing:-.035em;max-width:800px;margin:0 0 24px}h2{font-size:20px;line-height:1.35;letter-spacing:-.02em;margin:0 0 12px}p{margin:0 0 16px}.lead{font-size:20px;line-height:1.6;max-width:800px;color:var(--muted)}
.sections{margin-top:40px;max-width:800px}.sections section{border-top:1px solid var(--line);padding:26px 0 10px}.note{border-left:3px solid var(--accent);padding:4px 0 4px 20px;margin-top:28px;max-width:800px}.note p:last-child{margin-bottom:0}ul{padding-left:23px;margin:0 0 16px}li{margin-bottom:8px}.scope{color:var(--muted);font-size:15px}code{font:14px ui-monospace,SFMono-Regular,Consolas,monospace;overflow-wrap:anywhere;background:#e8eee8;padding:2px 5px;border-radius:3px}
footer{border-top:1px solid var(--line);padding:24px 0 36px;color:var(--muted);font-size:13px}.foot{display:flex;gap:14px;justify-content:space-between;flex-wrap:wrap}footer p{margin:0}
@media(max-width:560px){.wrap{width:calc(100% - 36px)}header{padding-top:22px}.masthead{gap:16px}nav{gap:17px}main{padding-top:38px;padding-bottom:42px}.lead{font-size:18px}.sections{margin-top:30px}}
""".strip()

_STYLE_HASH = base64.b64encode(hashlib.sha256(STYLE.encode()).digest()).decode()
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; style-src 'sha256-" + _STYLE_HASH + "'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'"
)

_NAVIGATION = (
    ("/jarvis-docxx/", "Présentation"),
    ("/jarvis-docxx/privacy/", "Confidentialité"),
    ("/jarvis-docxx/terms/", "Conditions"),
)


def _page(path: str, title: str, heading: str, lead: str, content: str) -> bytes:
    navigation = "".join(
        f'<a href="{url}"' + (' aria-current="page"' if path == url else '') + f'>{label}</a>'
        for url, label in _NAVIGATION
    )
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>{title} · JARVIS–DOCXX</title>
<meta name="description" content="Informations sur le module privé JARVIS–DOCXX pour l’organisation des documents personnels.">
<style>{STYLE}</style>
</head>
<body>
<a class="skip" href="#contenu">Aller au contenu</a>
<header><div class="wrap masthead">
<a class="brand" href="/jarvis-docxx/">JARVIS<span>–DOCXX</span></a>
<nav aria-label="Informations du module">{navigation}</nav>
</div></header>
<main id="contenu" class="wrap">
<p class="eyebrow">Assistant documentaire privé</p>
<h1>{heading}</h1>
<p class="lead">{lead}</p>
{content}
</main>
<footer><div class="wrap foot"><p>JARVIS–DOCXX · Usage personnel privé</p><p>Version du 23 octobre 2026</p></div></footer>
</body>
</html>""".encode("utf-8")


PAGES = MappingProxyType({
    "/jarvis-docxx/": _page(
        "/jarvis-docxx/", "Présentation", "Des documents personnels, organisés et suivis.",
        "JARVIS–DOCXX aide son propriétaire à rassembler les documents utiles dans sa bibliothèque Google Drive. "
        "Le suivi des traitements reste dans un Command Center réservé au propriétaire.",
        """<div class="sections">
<section><h2>1. Repérer les documents</h2>
<p>Le module peut consulter les métadonnées des messages Gmail reçus depuis le 23 octobre 2026 et télécharger leurs pièces jointes admissibles, notamment les PDF, les images de documents et certains fichiers bureautiques.</p>
</section>
<section><h2>2. Lire et classer localement</h2>
<p>Les fichiers sont conservés dans un espace local de préparation. Leur texte est extrait sur l’ordinateur du propriétaire, avec reconnaissance optique de caractères (OCR) si nécessaire. Des règles de classement orientent les documents reconnus ; les cas incertains restent à vérifier.</p>
<p>Ce traitement automatique en arrière-plan n’appelle pas de modèle de langage.</p>
</section>
<section><h2>3. Retrouver les documents retenus</h2>
<p>Les documents retenus sont copiés dans le Google Drive du propriétaire. Le suivi distingue les traitements en attente, les documents à vérifier et les copies dont la présence dans Drive a été confirmée.</p>
</section>
</div>
<aside class="note" aria-label="Périmètre de l’accès Gmail">
<h2>Gmail en lecture seule</h2>
<p>L’autorisation Gmail utilisée par ce module est <code>gmail.readonly</code>. Le module n’envoie, ne modifie, n’archive et ne supprime aucun message.</p>
</aside>
<p class="scope">Ces informations concernent uniquement le module documentaire JARVIS–DOCXX, pas les autres intégrations de JARVIS. Le service est privé et ne propose pas d’inscription publique.</p>""",
    ),
    "/jarvis-docxx/privacy/": _page(
        "/jarvis-docxx/privacy/", "Confidentialité", "Confidentialité du module documentaire.",
        "Cette notice décrit le traitement des documents par JARVIS–DOCXX, un module privé utilisé par son propriétaire. "
        "Elle ne décrit pas les autres intégrations de JARVIS.",
        """<div class="sections">
<section><h2>Données consultées</h2>
<p>L’autorisation Google <code>gmail.readonly</code> permet de consulter les messages Gmail. Dans ce module, le traitement porte sur le profil nécessaire à la vérification du compte, les métadonnées des messages et les pièces jointes admissibles des messages reçus depuis le 23 octobre 2026.</p>
<p>Les métadonnées utiles comprennent notamment les identifiants des messages et des pièces jointes, les dates, les noms de fichiers, leurs types et leurs tailles.</p>
</section>
<section><h2>Utilisation des données</h2>
<p>Les pièces jointes sélectionnées sont téléchargées dans un espace local de préparation. L’extraction de texte, l’OCR et les règles de classement s’exécutent sur l’ordinateur du propriétaire. Ce traitement automatique en arrière-plan n’envoie pas le contenu à un modèle de langage.</p>
<p>Les documents retenus sont copiés dans le Google Drive du propriétaire. Un journal privé conserve les identifiants, les empreintes des fichiers, les destinations et les résultats nécessaires au suivi et à la prévention des imports répétés.</p>
</section>
<section><h2>Accès et conservation</h2>
<p>Les fichiers et le journal de traitement sont conservés dans l’environnement privé du propriétaire. Le Command Center qui présente leur suivi nécessite un accès propriétaire. Ces pages publiques ne donnent accès ni aux documents ni à leurs journaux.</p>
<p>Les originaux restent dans Gmail. Les copies locales, les documents copiés dans Drive et le journal sont conservés jusqu’à leur suppression par le propriétaire. Les sauvegardes peuvent conserver leurs propres copies jusqu’à leur suppression dans ces sauvegardes.</p>
</section>
<section><h2>Contrôle par le propriétaire</h2>
<p>Le propriétaire peut mettre le module en pause dans sa configuration locale et révoquer l’accès de l’application dans les paramètres de son compte Google. La révocation empêche les accès futurs avec cette autorisation ; elle ne supprime pas les fichiers déjà copiés.</p>
<p>Pour retirer des données déjà importées, le propriétaire gère séparément les copies locales, les documents dans Drive et les sauvegardes.</p>
</section>
<section><h2>Ces pages d’information</h2>
<p>Elles ne comportent ni formulaire d’inscription, ni publicité, ni script de mesure d’audience, et ne chargent aucune ressource tierce. Elles ne consultent aucune donnée privée du Command Center.</p>
<p>L’accès à ce site implique le traitement de données techniques de connexion par les services d’hébergement et de protection d’accès, notamment l’adresse IP, la date et l’heure ainsi que les informations de la requête. Ces données servent à transmettre les pages et à contrôler l’accès.</p>
</section>
<section><h2>Contact</h2>
<p>Pour toute question sur ce module ou la gestion de ses données, utiliser l’adresse d’assistance indiquée sur l’écran de consentement Google de l’application.</p>
</section>
</div>""",
    ),
    "/jarvis-docxx/terms/": _page(
        "/jarvis-docxx/terms/", "Conditions d’utilisation", "Conditions d’utilisation personnelle.",
        "JARVIS–DOCXX est un outil privé d’organisation documentaire, réservé à son propriétaire. "
        "Ces conditions concernent uniquement ce module.",
        """<div class="sections">
<section><h2>Un usage privé</h2>
<p>Le module ne propose pas d’inscription publique ni d’accès public aux documents. Les pages de présentation, de confidentialité et de conditions expliquent son fonctionnement ; elles ne constituent pas un espace de dépôt de fichiers.</p>
</section>
<section><h2>Une aide à l’organisation</h2>
<p>Le propriétaire choisit les comptes et les documents qu’il autorise à traiter. Le classement et les noms de fichiers facilitent la recherche ; ils ne remplacent pas la vérification du contenu. Le propriétaire vérifie les documents importants et les éléments signalés comme incertains.</p>
<p>Les messages et les pièces jointes d’origine restent dans Gmail. La copie et le classement dans Drive sont des opérations distinctes du traitement des originaux.</p>
</section>
<section><h2>Un fonctionnement à suivre</h2>
<p>Le traitement dépend de l’ordinateur du propriétaire, de sa connexion et de la disponibilité des services utilisés. Une interruption, une autorisation expirée ou un document non reconnu peut nécessiter une intervention du propriétaire. Le suivi privé indique les étapes et les erreurs observées.</p>
</section>
<section><h2>Arrêter le traitement et gérer les copies</h2>
<p>Le propriétaire peut désactiver le module dans sa configuration locale et révoquer son autorisation dans les paramètres du compte Google. Les copies déjà créées restent présentes jusqu’à leur suppression par le propriétaire, y compris les copies éventuellement conservées dans les sauvegardes.</p>
</section>
<section><h2>Périmètre</h2>
<p>Les autres fonctions et intégrations de JARVIS ne sont pas décrites par ces pages. L’utilisation des données par ce module est détaillée dans la <a href="/jarvis-docxx/privacy/">notice de confidentialité</a>.</p>
</section>
</div>""",
    ),
})
