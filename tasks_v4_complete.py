# AnalyLit V4.0 - Tâches de traitement et d'analyse avec PostgreSQL via SQLAlchemy

import requests
import json
import time
import re
import subprocess
import uuid
from pathlib import Path
from datetime import datetime
from urllib.parse import urljoin, quote
import bs4
from rq import Queue
import redis
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from scipy import stats
import numpy as np
import pandas as pd
import matplotlib.ticker as mticker
import PyPDF2
from pyzotero import zotero
from config_v4 import get_config
from langchain.text_splitter import RecursiveCharacterTextSplitter
from sentence_transformers import SentenceTransformer
import chromadb
from chromadb.utils import embedding_functions
from socketio import RedisManager
import random
import hashlib
import xml.etree.ElementTree as ET
import arxiv
import crossref_commons.retrieval as cr
import os
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# Configuration
config = get_config()
redis_conn = redis.from_url(config.REDIS_URL)
PROJECTS_DIR = config.PROJECTS_DIR

# SQLAlchemy pour les tâches (processus séparés)
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
Session = sessionmaker(bind=engine)

# Gestionnaire Socket.IO pour les workers
sio_redis_manager = RedisManager(config.REDIS_URL, write_only=True)


# Models
embedding_model = SentenceTransformer(config.EMBEDDING_MODEL)

# Variables d'environnement pour la robustesse API
UNPAYWALL_EMAIL = config.UNPAYWALL_EMAIL
HTTP_MAX_RETRIES = config.MAX_RETRIES
HTTP_BACKOFF_BASE = 1.6
MIN_CHUNK_LEN = 250
NORMALIZE_LOWER = False
EMBED_BATCH = 32
USE_QUERY_EMBED = True
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://ollama:11434")

class DatabaseManager:
    """Gestionnaire centralisé pour les requêtes multi-bases de données."""

    def __init__(self):
        self.config = config.get_database_config()

    def get_available_databases(self):
        """Retourne la liste des bases de données disponibles."""
        databases = []

        # PubMed (toujours disponible)
        databases.append({
            'id': 'pubmed',
            'name': 'PubMed',
            'description': 'Base de données biomédicale de référence',
            'enabled': True,
            'type': 'biomedical'
        })

        # ArXiv (toujours disponible)
        databases.append({
            'id': 'arxiv',
            'name': 'arXiv',
            'description': 'Articles de pré-publication scientifique',
            'enabled': True,
            'type': 'preprint'
        })

        # CrossRef (toujours disponible)
        databases.append({
            'id': 'crossref',
            'name': 'CrossRef',
            'description': 'Métadonnées d\'articles académiques',
            'enabled': True,
            'type': 'metadata'
        })

        # IEEE (si clé API configurée)
        if self.config['ieee']['enabled']:
            databases.append({
                'id': 'ieee',
                'name': 'IEEE Xplore',
                'description': 'Articles d\'ingénierie et technologie',
                'enabled': True,
                'type': 'technical'
            })

        return databases

    def search_pubmed(self, query, max_results=50):
        """Recherche dans PubMed."""
        results = []
        try:
            # Recherche avec E-utilities
            search_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
            search_params = {
                'db': 'pubmed',
                'term': query,
                'retmax': max_results,
                'retmode': 'json'
            }

            response = requests.get(search_url, params=search_params, timeout=30)
            response.raise_for_status()
            search_data = response.json()

            pmids = search_data.get('esearchresult', {}).get('idlist', [])
            if not pmids:
                return results

            # Récupérer les détails
            fetch_url = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
            fetch_params = {
                'db': 'pubmed',
                'id': ','.join(pmids),
                'retmode': 'xml'
            }

            response = requests.get(fetch_url, params=fetch_params, timeout=30)
            response.raise_for_status()

            # Parser le XML
            root = ET.fromstring(response.text)
            for article in root.iter('PubmedArticle'):
                try:
                    # PMID
                    pmid_elem = article.find('.//PMID')
                    pmid = pmid_elem.text if pmid_elem is not None else ''

                    # Titre
                    title_elem = article.find('.//ArticleTitle')
                    title = title_elem.text if title_elem is not None else ''

                    # Abstract
                    abstract_elem = article.find('.//AbstractText')
                    abstract = abstract_elem.text if abstract_elem is not None else ''

                    # Auteurs
                    authors = []
                    for author in article.iter('Author'):
                        lastname = author.find('LastName')
                        forename = author.find('ForeName')
                        if lastname is not None and forename is not None:
                            authors.append(f"{forename.text} {lastname.text}")

                    # Journal
                    journal_elem = article.find('.//Journal/Title')
                    journal = journal_elem.text if journal_elem is not None else ''

                    # Date de publication
                    pub_date = article.find('.//PubDate/Year')
                    publication_date = pub_date.text if pub_date is not None else ''

                    # DOI
                    doi = ''
                    for article_id in article.iter('ArticleId'):
                        if article_id.get('IdType') == 'doi':
                            doi = article_id.text
                            break

                    results.append({
                        'id': pmid,
                        'title': title,
                        'abstract': abstract,
                        'authors': '; '.join(authors),
                        'publication_date': publication_date,
                        'journal': journal,
                        'doi': doi,
                        'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                        'database_source': 'pubmed'
                    })

                except Exception as e:
                    print(f"Erreur parsing article PubMed: {e}")
                    continue

        except Exception as e:
            print(f"Erreur recherche PubMed: {e}")

        return results

    def search_arxiv(self, query, max_results=50):
        """Recherche dans arXiv."""
        results = []
        try:
            client = arxiv.Client()
            search = arxiv.Search(
                query=query,
                max_results=max_results,
                sort_by=arxiv.SortCriterion.Relevance
            )

            for paper in client.results(search):
                results.append({
                    'id': paper.entry_id.split('/')[-1],
                    'title': paper.title,
                    'abstract': paper.summary,
                    'authors': '; '.join([str(author) for author in paper.authors]),
                    'publication_date': paper.published.strftime('%Y-%m-%d') if paper.published else '',
                    'journal': ', '.join(paper.categories),
                    'doi': paper.doi or '',
                    'url': paper.entry_id,
                    'database_source': 'arxiv'
                })

        except Exception as e:
            print(f"Erreur recherche arXiv: {e}")

        return results

    def search_crossref(self, query, max_results=50):
        """Recherche dans CrossRef."""
        results = []
        try:
            url = "https://api.crossref.org/works"
            params = {
                'query': query,
                'rows': max_results,
                'mailto': self.config['crossref']['email']
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            items = data.get('message', {}).get('items', [])
            for item in items:
                # Titre
                title = ''
                if 'title' in item and item['title']:
                    title = item['title'][0]

                # Auteurs
                authors = []
                if 'author' in item:
                    for author in item['author']:
                        given = author.get('given', '')
                        family = author.get('family', '')
                        if given and family:
                            authors.append(f"{given} {family}")

                # Journal
                journal = ''
                if 'container-title' in item and item['container-title']:
                    journal = item['container-title'][0]

                # Date de publication
                publication_date = ''
                if 'published-print' in item:
                    date_parts = item['published-print'].get('date-parts', [[]])[0]
                    if date_parts:
                        publication_date = f"{date_parts[0]}"
                        if len(date_parts) > 1:
                            publication_date += f"-{date_parts[1]:02d}"
                        if len(date_parts) > 2:
                            publication_date += f"-{date_parts[2]:02d}"

                # DOI et URL
                doi = item.get('DOI', '')
                url = f"https://doi.org/{doi}" if doi else item.get('URL', '')

                results.append({
                    'id': doi or item.get('URL', '').split('/')[-1],
                    'title': title,
                    'abstract': item.get('abstract', ''),
                    'authors': '; '.join(authors),
                    'publication_date': publication_date,
                    'journal': journal,
                    'doi': doi,
                    'url': url,
                    'database_source': 'crossref'
                })

        except Exception as e:
            print(f"Erreur recherche CrossRef: {e}")

        return results

    def search_ieee(self, query, max_results=50):
        """Recherche dans IEEE Xplore."""
        results = []
        if not self.config['ieee']['enabled']:
            return results

        try:
            url = "https://ieeexploreapi.ieee.org/api/v1/search/articles"
            params = {
                'apikey': self.config['ieee']['api_key'],
                'querytext': query,
                'max_records': max_results,
                'start_record': 1,
                'sort_field': 'article_number',
                'sort_order': 'desc'
            }

            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()

            articles = data.get('articles', [])
            for article in articles:
                # Auteurs
                authors = []
                if 'authors' in article:
                    if isinstance(article['authors'], dict):
                        for author_list in article['authors'].values():
                            if isinstance(author_list, list):
                                authors.extend([a.get('full_name', '') for a in author_list])
                    elif isinstance(article['authors'], list):
                        authors = [a.get('full_name', '') for a in article['authors']]

                results.append({
                    'id': article.get('article_number', ''),
                    'title': article.get('title', ''),
                    'abstract': article.get('abstract', ''),
                    'authors': '; '.join(authors),
                    'publication_date': article.get('publication_year', ''),
                    'journal': article.get('publication_title', ''),
                    'doi': article.get('doi', ''),
                    'url': article.get('html_url', ''),
                    'database_source': 'ieee'
                })

        except Exception as e:
            print(f"Erreur recherche IEEE: {e}")

        return results

# Instance globale du gestionnaire de bases de données
db_manager = DatabaseManager()

# NOUVEAU : Fonction de sanétisation unifiée
def sanitize_filename(article_id: str) -> str:
    """Convertit un identifiant d'article en un nom de fichier valide."""
    # Remplace les caractères non alphanumériques (sauf le point) par un underscore
    return re.sub(r'[^a-zA-Z0-9.-]', '_', article_id)

# Fonctions utilitaires
def http_get_with_retries(url, headers=None, timeout=15, max_retries=HTTP_MAX_RETRIES,
                         backoff_base=HTTP_BACKOFF_BASE, jitter=True, ok_statuses=(200,)):
    """Effectue une requête GET avec retry automatique et backoff exponentiel."""
    last_exc = None
    for attempt in range(max_retries):
        try:
            r = requests.get(url, headers=headers or {}, timeout=timeout)
            if r.status_code in ok_statuses:
                return r
            if r.status_code in (429, 500, 502, 503, 504):
                sleep_s = (backoff_base ** attempt)
                if jitter:
                    sleep_s += random.uniform(0, 0.3)
                print(f"⚠️ Status {r.status_code}, retry dans {sleep_s:.1f}s...")
                time.sleep(sleep_s)
                continue
            r.raise_for_status()
            return r
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as e:
            last_exc = e
            sleep_s = (backoff_base ** attempt)
            if jitter:
                sleep_s += random.uniform(0, 0.3)
            print(f"⚠️ Erreur réseau (essai {attempt+1}/{max_retries}), retry dans {sleep_s:.1f}s...")
            time.sleep(sleep_s)

    raise last_exc if last_exc else RuntimeError("HTTP retries exhausted")

def parse_doi_from_pubmed_xml(xml_text: str) -> str | None:
    """Extrait un DOI depuis du XML PubMed."""
    try:
        root = ET.fromstring(xml_text)
        for el in root.iter():
            if el.tag.endswith("ELocationID") and el.attrib.get("EIdType") == "doi":
                v = (el.text or "").strip()
                if v.startswith("10."):
                    return v
        for el in root.iter():
            if el.tag.endswith("ArticleId") and el.attrib.get("IdType") == "doi":
                v = (el.text or "").strip()
                if v.startswith("10."):
                    return v
    except ET.ParseError:
        pass
    return None

def get_doi_from_pmid(pmid: str) -> str | None:
    """Récupère le DOI d'un article via E-utilities NCBI."""
    efetch = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pubmed&id={quote(str(pmid))}&retmode=xml"
    try:
        r = http_get_with_retries(efetch, timeout=20)
        doi = parse_doi_from_pubmed_xml(r.text)
        return doi
    except Exception as e:
        print(f"⚠️ DOI introuvable via E-utilities pour PMID {pmid}: {e}")
        return None

def fetch_unpaywall_pdf_url(doi: str) -> str | None:
    """Interroge Unpaywall pour obtenir l'URL du PDF OA."""
    url = f"https://api.unpaywall.org/v2/{quote(doi)}?email={quote(UNPAYWALL_EMAIL)}"
    try:
        r = http_get_with_retries(url, timeout=20)
        data = r.json()
        loc = (data or {}).get("best_oa_location") or {}
        pdf = loc.get("url_for_pdf")
        return pdf
    except Exception as e:
        print(f"⚠️ Unpaywall erreur pour DOI {doi}: {e}")
        return None

def normalize_text(s: str) -> str:
    """Normalise le texte pour réduire le bruit avant indexation."""
    if not s:
        return ""

    # Supprimer soft hyphen et caractères de contrôle
    s = s.replace("\u00ad", "")
    s = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F]", "", s)

    # Normaliser espaces
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\s*\n\s*", "\n", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    s = s.strip()

    if NORMALIZE_LOWER:
        s = s.lower()

    return s

def send_project_notification(project_id: str, event_type: str, message: str, data: dict = None):
    """Envoie une notification WebSocket à un projet spécifique via Redis."""
    try:
        payload = {
            'type': event_type,
            'message': message,
            'project_id': project_id,
            'timestamp': datetime.now().isoformat(),
            'data': data or {}
            }
        # Utilise le manager Redis pour émettre l'événement
        sio_redis_manager.emit('notification', payload, room=project_id)
        # On log pour être certain que la fonction a été appelée
        print(f"📢 Notification envoyée au projet {project_id}: {event_type} - '{message[:50]}...'")
    except Exception as e:
        print(f"❌ Erreur lors de l'envoi de la notification WebSocket via Redis: {e}")

def extract_text_from_pdf(pdf_path):
    """Extrait le texte d'un fichier PDF."""
    text = ""
    try:
        with open(pdf_path, 'rb') as file:
            reader = PyPDF2.PdfReader(file)
            for page in reader.pages:
                text += page.extract_text() or ""
    except Exception as e:
        print(f"Erreur de lecture du PDF {pdf_path}: {e}")
        return None
    return text

def get_prompt_from_db(prompt_name: str) -> str:
    """Récupère un template de prompt depuis la base de données."""
    session = Session()
    try:
        result = session.execute(text("""
            SELECT template FROM prompts WHERE name = :name
        """), {'name': prompt_name}).fetchone()
        
        if result:
            return result.template
    except Exception as e:
        print(f"Erreur récupération prompt {prompt_name}: {e}")
    finally:
        session.close()

    # Fallback si la BDD est inaccessible
    if prompt_name == 'screening_prompt':
        return """En tant qu'assistant de recherche spécialisé, analysez cet article et déterminez sa pertinence pour une revue systématique.

Titre: {title}
Résumé: {abstract}
Source: {database_source}

Veuillez évaluer la pertinence de cet article sur une échelle de 1 à 10 et fournir une justification concise.

Répondez UNIQUEMENT avec un objet JSON contenant :
- "relevance_score": score numérique de 0 à 10
- "decision": "À inclure" si score >= 7, sinon "À exclure"
- "justification": phrase courte (max 30 mots) expliquant le score"""

    elif prompt_name == 'full_extraction_prompt':
        return """En tant qu'expert en revue systématique, extrayez les données importantes de cet article selon une grille d'extraction structurée.

Texte à analyser: "{text}"

Source: {database_source}

Extrayez les informations suivantes au format JSON:
{
"type_etude": "...",
"population": "...",
"intervention": "...",
"resultats_principaux": "...",
"limites": "...",
"methodologie": "..."
}"""

    return ""

def get_screening_prompt(title, abstract, database_source="unknown"):
    """Génère le prompt de screening avec les données de l'article."""
    template = get_prompt_from_db('screening_prompt')
    return template.format(title=title, abstract=abstract, database_source=database_source)

def get_full_extraction_prompt(text, database_source="unknown", custom_grid_id=None):
    """Génère le prompt d'extraction avec grille personnalisée optionnelle."""
    intro = "ROLE: Vous êtes un assistant expert en analyse de littérature scientifique, spécialisé dans l'extraction de données structurées.\n\nTÂCHE: Analysez le texte fourni et extrayez les informations demandées en respectant SCRUPULEUSEMENT le format JSON.\n\nINSTRUCTIONS IMPORTANTES:\n1. Répondez **UNIQUEMENT** avec un objet JSON valide. N'ajoutez aucun texte, commentaire ou explication avant ou après le JSON.\n2. Assurez-vous que chaque paire clé-valeur est séparée par une virgule, sauf la dernière.\n3. Échappez correctement les guillemets doubles (\") à l'intérieur des chaînes de caractères avec un antislash (\\).\n4. Si une information n'est pas présente dans le texte, utilisez une chaîne de caractères vide (\"\") comme valeur. Ne laissez pas de champ vide ou avec \"...\"."

    text_to_analyze = f'TEXTE À ANALYSER:\n---\n{text}\n---'
    source_info = f'SOURCE: {database_source}'
    instruction = "GRILLE D'EXTRACTION JSON (remplissez les valeurs):"

    json_structure = ""

    if custom_grid_id:
        session = Session()
        try:
            result = session.execute(text("""
                SELECT fields FROM extraction_grids WHERE id = :id
            """), {'id': custom_grid_id}).fetchone()
            
            if result:
                custom_fields = json.loads(result.fields)
                json_fields = ",\n".join([f' "{field}": "..."' for field in custom_fields])
                json_structure = f"{{\n{json_fields}\n}}"
        except Exception as e:
            print(f"Erreur lors du chargement de la grille personnalisée: {e}")
        finally:
            session.close()

    if not json_structure:
        default_prompt_template = get_prompt_from_db('full_extraction_prompt')
        json_start = default_prompt_template.find('{')
        if json_start != -1:
            json_structure = default_prompt_template[json_start:]

    final_prompt = f"{intro}\n\n{text_to_analyze}\n{source_info}\n\n{instruction}\n{json_structure}"
    return final_prompt

def update_project_status(project_id: str, status: str, result: dict = None, discussion: str = None,
                         graph: dict = None, prisma_path: str = None, analysis_result: dict = None,
                         analysis_plot_path: str = None):
    """Met à jour le statut et les résultats d'un projet."""
    session = Session()
    try:
        now = datetime.now()

        if result:
            session.execute(text("""
                UPDATE projects SET status = :status, synthesis_result = :synthesis_result, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'status': status,
                'synthesis_result': json.dumps(result),
                'updated_at': now,
                'id': project_id
            })
        elif discussion:
            session.execute(text("""
                UPDATE projects SET discussion_draft = :discussion_draft, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'discussion_draft': discussion,
                'updated_at': now,
                'id': project_id
            })
        elif graph:
            session.execute(text("""
                UPDATE projects SET knowledge_graph = :knowledge_graph, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'knowledge_graph': json.dumps(graph),
                'updated_at': now,
                'id': project_id
            })
        elif prisma_path:
            session.execute(text("""
                UPDATE projects SET prisma_flow_path = :prisma_flow_path, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'prisma_flow_path': prisma_path,
                'updated_at': now,
                'id': project_id
            })
        elif analysis_result is not None:
            session.execute(text("""
                UPDATE projects SET status = :status, analysis_result = :analysis_result, 
                analysis_plot_path = :analysis_plot_path, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'status': status,
                'analysis_result': json.dumps(analysis_result),
                'analysis_plot_path': analysis_plot_path,
                'updated_at': now,
                'id': project_id
            })
        else:
            session.execute(text("""
                UPDATE projects SET status = :status, updated_at = :updated_at 
                WHERE id = :id
            """), {
                'status': status,
                'updated_at': now,
                'id': project_id
            })

        session.commit()

    except Exception as e:
        session.rollback()
        print(f"❌ ERREUR DATABASE (update_project_status) pour {project_id}: {e}")
    finally:
        session.close()

def update_project_timing(session, project_id: str, duration: float):
    """Met à jour le temps de traitement total EN UTILISANT LA SESSION FOURNIE."""
    session.execute(text("""
        UPDATE projects SET total_processing_time = total_processing_time + :duration
        WHERE id = :id
    """), {'duration': duration, 'id': project_id})

def log_processing_status(session, project_id: str, article_id: str, status: str, details: str):
    """Enregistre un événement de traitement dans les logs EN UTILISANT LA SESSION FOURNIE."""
    session.execute(text("""
        INSERT INTO processing_log (project_id, pmid, status, details, timestamp)
        VALUES (:project_id, :pmid, :status, :details, :timestamp)
    """), {
        'project_id': project_id, 'pmid': article_id, 'status': status,
        'details': details, 'timestamp': datetime.now()
    })

def increment_processed_count(session, project_id: str):
    """Incrémente le compteur d'articles traités EN UTILISANT LA SESSION FOURNIE."""
    session.execute(text("""
        UPDATE projects SET processed_count = processed_count + 1
        WHERE id = :id
    """), {'id': project_id})

def call_ollama_api(prompt: str, model: str, output_format: str = "", retries: int = 3) -> any:
    """Appelle l'API Ollama avec gestion des erreurs et retry."""
    payload = {"model": model, "prompt": prompt, "stream": False}
    if output_format == "json":
        payload["format"] = "json"

    last_exception = None
    for attempt in range(retries):
        try:
            print(f"🤖 Appel Ollama avec le modèle : {model} (Essai {attempt + 1}/{retries})...")
            response = requests.post(f"{config.OLLAMA_BASE_URL}/api/generate", json=payload, timeout=900)
            response.raise_for_status()
            result = response.json()

            response_text = result.get('response', '')
            if output_format == "json":
                response_text = response_text.strip().replace("```json", "").replace("```", "")
                return json.loads(response_text)
            return response_text

        except (requests.RequestException, json.JSONDecodeError) as e:
            last_exception = e
            print(f"⚠️ Erreur Ollama (essai {attempt + 1}): {e}. Nouvel essai...")
            time.sleep(5)

    print(f"❌ Échec de l'appel API Ollama après {retries} essais. Erreur: {last_exception}")
    return {} if output_format == "json" else ""

def fetch_article_details(article_id: str, database_source: str = None) -> dict:
    """Récupère les détails d'un article selon son identifiant."""
    # Nettoyer l'identifiant
    article_id = article_id.strip()

    # Détection automatique du type d'identifiant
    if article_id.startswith("10.") and "/" in article_id:
        # C'est un DOI
        print(f"📖 Détecté comme DOI : {article_id}")
        return fetch_crossref_details(article_id)
    elif article_id.isdigit() and len(article_id) >= 7:
        # C'est probablement un PMID
        print(f"📖 Détecté comme PMID : {article_id}")
        return fetch_pubtator_abstract(article_id)
    elif "arxiv" in article_id.lower() or article_id.count('.') == 1:
        # C'est probablement un ID arXiv
        print(f"📖 Détecté comme arXiv ID : {article_id}")
        return fetch_arxiv_details(article_id)
    else:
        # Fallback : essayer en tant que PMID d'abord, puis DOI
        print(f"⚠️ Type d'identifiant incertain pour : {article_id}, essai PMID d'abord...")
        details = fetch_pubtator_abstract(article_id)
        if details.get('title') == 'Erreur de récupération':
            print(f"⚠️ Échec PMID, essai en tant que DOI...")
            details = fetch_crossref_details(article_id)
        return details

def fetch_pubtator_abstract(pmid: str) -> dict:
    """Récupère le titre et le résumé d'un article via l'API PubTator et cherche le DOI."""
    url = f"https://www.ncbi.nlm.nih.gov/research/pubtator-api/publications/export/pubtator?pmids={pmid}"
    details = {'id': pmid, 'title': 'Erreur de récupération', 'abstract': '', 'database_source': 'pubmed'}
    try:
        r = http_get_with_retries(url, timeout=20)
        content = r.text

        title_match = re.search(rf'^{re.escape(pmid)}\|t\|(.*?)$', content, re.MULTILINE)
        abstract_match = re.search(rf'^{re.escape(pmid)}\|a\|(.*?)$', content, re.MULTILINE)

        details['title'] = title_match.group(1).strip() if title_match else "Titre non trouvé"
        details['abstract'] = abstract_match.group(1).strip() if abstract_match else ""

        details['doi'] = get_doi_from_pmid(pmid)

        time.sleep(0.2)
        # CORRECTION : S'assurer de retourner le dictionnaire complet 'details'
        return details

    except Exception as e:
        print(f"❌ PubTator erreur pour PMID {pmid}: {e}")
        return {'id': pmid, 'title': 'Erreur de récupération', 'abstract': ''}
        
def fetch_arxiv_details(arxiv_id: str) -> dict:
    """Récupère les détails d'un article arXiv."""
    try:
        client = arxiv.Client()
        search = arxiv.Search(id_list=[arxiv_id])
        for paper in client.results(search):
            return {
                'id': arxiv_id,
                'title': paper.title,
                'abstract': paper.summary,
                'database_source': 'arxiv'
            }
    except Exception as e:
        print(f"❌ ArXiv erreur pour ID {arxiv_id}: {e}")
    return {'id': arxiv_id, 'title': 'Erreur de récupération', 'abstract': ''}

def fetch_crossref_details(doi: str) -> dict:
    """Récupère les détails d'un article CrossRef."""
    try:
        work = cr.get_publication_as_json(doi)
        title = ''
        if 'title' in work and work['title']:
            title = work['title'][0]
        abstract = work.get('abstract', '')
        return {
            'id': doi,
            'title': title,
            'abstract': abstract,
            'database_source': 'crossref'
        }
    except Exception as e:
        print(f"❌ CrossRef erreur pour DOI {doi}: {e}")
    return {'id': doi, 'title': 'Erreur de récupération', 'abstract': ''}

def fetch_ieee_details(article_id: str) -> dict:
    """Récupère les détails d'un article IEEE."""
    # Cette fonction nécessiterait l'API IEEE pour récupérer les détails
    # Pour l'instant, retour basique
    return {'id': article_id, 'title': 'Article IEEE', 'abstract': ''}

# --- TÂCHES PRINCIPALES ---

def multi_database_search_task(project_id: str, query: str, databases: list, max_results_per_db: int = 50):
    """Effectue une recherche dans plusieurs bases de données."""
    print(f"🔍 Recherche multi-bases pour le projet {project_id}: {query}")
    all_results = []
    total_found = 0

    try:
        for db_name in databases:
            print(f"📚 Recherche dans {db_name}...")
            try:
                if db_name == 'pubmed':
                    results = db_manager.search_pubmed(query, max_results_per_db)
                elif db_name == 'arxiv':
                    results = db_manager.search_arxiv(query, max_results_per_db)
                elif db_name == 'crossref':
                    results = db_manager.search_crossref(query, max_results_per_db)
                elif db_name == 'ieee':
                    results = db_manager.search_ieee(query, max_results_per_db)
                else:
                    print(f"⚠️ Base de données inconnue: {db_name}")
                    continue

                print(f"✅ {db_name}: {len(results)} résultats trouvés")

                # Sauvegarder les résultats dans la base de données
                session = Session()
                try:
                    for result in results:
                        search_result_id = str(uuid.uuid4())
                        session.execute(text("""
                            INSERT INTO search_results (
                                id, project_id, article_id, title, abstract, authors,
                                publication_date, journal, doi, url, database_source, created_at
                            ) VALUES (:id, :project_id, :article_id, :title, :abstract, :authors,
                                     :publication_date, :journal, :doi, :url, :database_source, :created_at)
                        """), {
                            'id': search_result_id,
                            'project_id': project_id,
                            'article_id': result['id'],
                            'title': result['title'],
                            'abstract': result['abstract'],
                            'authors': result['authors'],
                            'publication_date': result['publication_date'],
                            'journal': result['journal'],
                            'doi': result['doi'],
                            'url': result['url'],
                            'database_source': result['database_source'],
                            'created_at': datetime.now()
                        })
                    session.commit()
                except Exception as e:
                    session.rollback()
                    print(f"❌ Erreur sauvegarde résultats pour {db_name}: {e}")
                finally:
                    session.close()

                all_results.extend(results)
                total_found += len(results)

                # Notification de progression
                send_project_notification(
                    project_id,
                    'search_progress',
                    f'Recherche terminée dans {db_name}: {len(results)} résultats',
                    {'database': db_name, 'count': len(results)}
                )

                time.sleep(1)  # Politesse entre les APIs

            except Exception as e:
                print(f"❌ Erreur lors de la recherche dans {db_name}: {e}")
                continue

        # Mettre à jour le statut du projet
        session = Session()
        try:
            session.execute(text("""
                UPDATE projects SET
                status = 'search_completed',
                pmids_count = :pmids_count,
                updated_at = :updated_at
                WHERE id = :id
            """), {
                'pmids_count': total_found,
                'updated_at': datetime.now(),
                'id': project_id
            })
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"❌ Erreur mise à jour statut projet: {e}")
        finally:
            session.close()

        # Notification finale
        send_project_notification(
            project_id,
            'search_completed',
            f'Recherche terminée: {total_found} articles trouvés dans {len(databases)} base(s) de données',
            {'total_results': total_found, 'databases': databases}
        )

        print(f"✅ Recherche multi-bases terminée: {total_found} articles trouvés")
        return {'total_results': total_found, 'databases': databases}

    except Exception as e:
        print(f"❌ Erreur critique lors de la recherche multi-bases: {e}")
        
        # Mettre à jour le statut d'erreur
        session = Session()
        try:
            session.execute(text("""
                UPDATE projects SET status = 'search_failed', updated_at = :updated_at WHERE id = :id
            """), {'updated_at': datetime.now(), 'id': project_id})
            session.commit()
        except Exception as db_e:
            session.rollback()
            print(f"❌ Erreur mise à jour statut échec: {db_e}")
        finally:
            session.close()

        send_project_notification(
            project_id,
            'search_failed',
            f'Erreur lors de la recherche: {str(e)}'
        )
        return {'error': str(e)}

def pull_ollama_model_task(model_name: str):
    """Tâche de téléchargement d'un modèle Ollama."""
    print(f"📥 Lancement du téléchargement pour le modèle : {model_name}...")
    try:
        process = subprocess.run(
            ["ollama", "pull", model_name],
            capture_output=True,
            text=True,
            check=True,
            timeout=1800
        )
        print(f"✅ Modèle '{model_name}' téléchargé avec succès.")
        return f"Modèle '{model_name}' téléchargé."
    except Exception as e:
        print(f"❌ Erreur lors du téléchargement du modèle '{model_name}': {e}")
        return f"Erreur: {e}"

def process_single_article_task(project_id: str, article_id: str, profile: dict, analysis_mode: str, custom_grid_id: str = None):
    """
    Tâche complète et corrigée pour traiter un seul article.
    Gère la session de manière centralisée et logue correctement les erreurs.
    """
    session = Session()
    start_time = time.time()
    try:
        # Log du début de traitement
        log_processing_status(session, project_id, article_id, 'starting', f"Analyse '{analysis_mode}' avec le modèle {profile.get('extract_model', 'inconnu')}")

        article = session.execute(
            text("SELECT * FROM search_results WHERE project_id = :pid AND article_id = :aid"),
            {'pid': project_id, 'aid': article_id}
        ).fetchone()

        if not article:
            # Si l'article n'est pas dans la base, on le récupère et on l'ajoute
            print(f"Article {article_id} non trouvé en BDD, récupération des détails...")
            details = fetch_article_details(article_id)
            if not details or details.get('title') == 'Erreur de récupération':
                raise ValueError(f"Impossible de récupérer les détails pour l'article {article_id}.")
            
            # Insérer le nouvel article dans la table search_results
            session.execute(text("""
                INSERT INTO search_results (id, project_id, article_id, title, abstract, database_source, created_at, url, doi, authors, journal, publication_date)
                VALUES (:id, :project_id, :article_id, :title, :abstract, :database_source, :created_at, :url, :doi, :authors, :journal, :publication_date)
            """), {
                'id': str(uuid.uuid4()), 'project_id': project_id, 'article_id': article_id,
                'title': details.get('title', 'Titre non trouvé'), 'abstract': details.get('abstract', ''),
                'database_source': details.get('database_source', 'manual_fetch'), 'created_at': datetime.now(),
                'url': details.get('url'), 'doi': details.get('doi'), 'authors': details.get('authors'),
                'journal': details.get('journal'), 'publication_date': details.get('publication_date')
            })
            session.commit()
            print(f"Article {article_id} ajouté à la base de données du projet.")
            
            # On relit l'article depuis la base pour avoir un objet cohérent
            article = session.execute(
                text("SELECT * FROM search_results WHERE project_id = :pid AND article_id = :aid"),
                {'pid': project_id, 'aid': article_id}
            ).fetchone()

        if not article:
             raise ValueError(f"Article {article_id} non trouvé dans le projet même après tentative d'ajout.")
        article_dict = dict(article._mapping)
        content_to_analyze = ""
        project_dir = PROJECTS_DIR / project_id
        pdf_path = project_dir / f"{sanitize_filename(article_id)}.pdf"

        if pdf_path.exists():
            content_to_analyze = extract_text_from_pdf(str(pdf_path))
            if not content_to_analyze or len(content_to_analyze.strip()) < MIN_CHUNK_LEN:
                log_processing_status(session, project_id, article_id, 'no_content', "PDF trouvé mais texte vide ou insuffisant")
                content_to_analyze = "" # On continue avec le résumé
        else:
            log_processing_status(session, project_id, article_id, 'no_pdf', "PDF non trouvé localement, utilisation du résumé.")

        # Fallback sur le titre et le résumé si le contenu du PDF est manquant
        if not content_to_analyze:
            content_to_analyze = f"Titre: {article_dict.get('title', '')}\n\nRésumé: {article_dict.get('abstract', '')}"

        # Sélection du prompt et du modèle en fonction du mode
        if analysis_mode == 'screening':
            prompt = get_screening_prompt(article_dict.get('title'), article_dict.get('abstract'), article_dict.get('database_source'))
            model = profile['preprocess_model']
        else: # 'full_extraction'
            prompt = get_full_extraction_prompt(content_to_analyze, article_dict.get('database_source'), custom_grid_id)
            model = profile['extract_model']

        # Appel à l'API Ollama
        api_result = call_ollama_api(prompt, model, output_format="json")

        if not api_result or not isinstance(api_result, dict):
             raise Exception(f"La réponse de l'API Ollama était vide ou mal formée.")

        # Sauvegarde des résultats
        if analysis_mode == 'screening':
            new_extraction = {
                'id': str(uuid.uuid4()), 'project_id': project_id, 'pmid': article_id,
                'title': article_dict.get('title'), 'created_at': datetime.now(),
                'relevance_score': float(api_result.get('relevance_score', 0)),
                'relevance_justification': api_result.get('justification', ''),
                'extracted_data': json.dumps(api_result),
                'analysis_source': f"screening_{model}"
            }
        else: # 'full_extraction'
            new_extraction = {
                'id': str(uuid.uuid4()), 'project_id': project_id, 'pmid': article_id,
                'title': article_dict.get('title'), 'created_at': datetime.now(),
                'extracted_data': json.dumps(api_result),
                'analysis_source': f"extraction_{model}"
            }

        session.execute(text("""
            INSERT INTO extractions (id, project_id, pmid, title, created_at, relevance_score, relevance_justification, extracted_data, analysis_source)
            VALUES (:id, :project_id, :pmid, :title, :created_at, :relevance_score, :relevance_justification, :extracted_data, :analysis_source)
            ON CONFLICT (project_id, pmid) DO UPDATE SET
                title = EXCLUDED.title, extracted_data = EXCLUDED.extracted_data,
                relevance_score = EXCLUDED.relevance_score, relevance_justification = EXCLUDED.relevance_justification,
                analysis_source = EXCLUDED.analysis_source, created_at = EXCLUDED.created_at;
        """), new_extraction)

        log_processing_status(session, project_id, article_id, 'success', f"Traitement '{analysis_mode}' réussi.")
        increment_processed_count(session, project_id)
        session.commit()

        send_project_notification(project_id, 'article_processed', f"Article {article_id} traité.", {'article_id': article_id})

    except Exception as e:
        error_message = f"Erreur lors du traitement de l'article {article_id}: {str(e)}"
        print(f"❌ {error_message}")
        session.rollback() # Annuler les changements partiels en cas d'erreur
        try:
            # On utilise une nouvelle session juste pour le logging de l'erreur
            error_session = Session()
            log_processing_status(error_session, project_id, article_id, 'error', error_message)
            error_session.commit()
            error_session.close()
        except Exception as db_err:
            print(f"❌ Impossible de logger l'erreur dans la BDD: {db_err}")

    finally:
        duration = time.time() - start_time
        try:
            # Mise à jour du temps de traitement dans une transaction séparée pour garantir son enregistrement
            timing_session = Session()
            update_project_timing(timing_session, project_id, duration)
            timing_session.commit()
            timing_session.close()
        except Exception as timing_err:
            print(f"❌ Erreur lors de la mise à jour du temps de traitement : {timing_err}")
        
        session.close()

def run_synthesis_task(project_id: str, profile: dict):
    """Génère une synthèse des articles pertinents d'un projet."""
    update_project_status(project_id, "synthesizing")
    session = Session()

    try:
        project = session.execute(text("""
            SELECT description FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        project_description = project.description if project else "Non spécifié"

        # Récupérer les extractions avec jointure pour title et abstract
        extractions = session.execute(text("""
            SELECT s.title, s.abstract
            FROM extractions e
            JOIN search_results s ON e.project_id = s.project_id AND e.pmid = s.article_id
            WHERE e.project_id = :project_id AND e.relevance_score >= 7
            ORDER BY e.relevance_score DESC LIMIT 30
        """), {'project_id': project_id}).fetchall()

        if not extractions:
            update_project_status(project_id, "failed")
            send_project_notification(project_id, 'synthesis_failed', 'Aucun article pertinent trouvé pour la synthèse.')
            print(f"⏩ Échec de la synthèse pour {project_id}: Aucun article pertinent trouvé (score >= 7).")
            return "Échec : Aucun article suffisamment pertinent trouvé pour la synthèse."

        abstracts_for_prompt = [
            f"Titre: {row.title}\nRésumé: {row.abstract}"
            for row in extractions if row.abstract
        ]

        if not abstracts_for_prompt:
            update_project_status(project_id, "failed")
            send_project_notification(project_id, 'synthesis_failed', 'Les articles pertinents n\'avaient pas de résumé.')
            print(f"⏩ Échec de la synthèse pour {project_id}: Les articles pertinents n'avaient pas de résumé.")
            return "Échec : Les articles pertinents n'avaient pas de résumé."

        data_for_prompt = "\n\n---\n\n".join(abstracts_for_prompt)

        synthesis_prompt_template = get_prompt_from_db('synthesis_prompt')
        prompt = synthesis_prompt_template.format(
            project_description=project_description,
            data_for_prompt=data_for_prompt
        )

        synthesis_output = call_ollama_api(prompt, profile['synthesis_model'], output_format="json")

        if synthesis_output and isinstance(synthesis_output, dict):
            update_project_status(project_id, "completed", result=synthesis_output)
            print(f"--- ✅ SYNTHÈSE COMPLÈTE pour le projet {project_id} ---")
            send_project_notification(project_id, 'synthesis_completed', 'La synthèse est terminée avec succès.')
        else:
            update_project_status(project_id, "failed")
            send_project_notification(project_id, 'synthesis_failed', 'La synthèse a échoué car l\'IA a renvoyé une réponse invalide.')

    except Exception as e:
        print(f"❌ Erreur synthèse pour {project_id}: {e}")
        update_project_status(project_id, "failed")
        send_project_notification(project_id, 'synthesis_failed', f'Erreur lors de la synthèse: {str(e)}')
    finally:
        session.close()

def run_discussion_generation_task(project_id: str):
    """Génère une section discussion académique pour un projet."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT synthesis_result, profile_used FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        extractions = session.execute(text("""
            SELECT pmid, title FROM extractions WHERE project_id = :id
        """), {'id': project_id}).fetchall()

        if not project or not project.synthesis_result:
            return

        synthesis_data = json.loads(project.synthesis_result)
        profile_name = project.profile_used or 'standard'

        # Récupérer le profil pour obtenir le modèle de synthèse
        profile_row = session.execute(text("""
            SELECT synthesis_model FROM analysis_profiles WHERE id = :id
        """), {'id': profile_name}).fetchone()

        model_name = profile_row.synthesis_model if profile_row else 'llama3.1:8b'

        article_list = "\n".join([f"- {e.title} (ID: {e.pmid})" for e in extractions])

        prompt = f"""En tant que chercheur, rédige une section 'Discussion' académique en te basant sur le résumé de synthèse et la liste d'articles ci-dessous.

**Résumé de Synthèse :**
---
{json.dumps(synthesis_data, indent=2)}
---

**Articles Inclus :**
---
{article_list}
---

La discussion doit synthétiser les apports, analyser les perspectives, explorer les divergences et suggérer des pistes de recherche futures en citant les sources."""

        discussion_text = call_ollama_api(prompt, model_name)

        if discussion_text:
            update_project_status(project_id, status="completed", discussion=discussion_text)

    except Exception as e:
        print(f"❌ Erreur discussion pour {project_id}: {e}")
    finally:
        session.close()

def run_knowledge_graph_task(project_id: str):
    """Génère un graphe de connaissances pour un projet."""
    update_project_status(project_id, status="generating_graph")
    session = Session()

    try:
        project = session.execute(text("""
            SELECT profile_used FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        extractions = session.execute(text("""
            SELECT title, pmid FROM extractions WHERE project_id = :id
        """), {'id': project_id}).fetchall()

        if not extractions:
            return

        profile_key = project.profile_used if project else 'standard'

        # Récupérer le modèle d'extraction du profil
        profile_row = session.execute(text("""
            SELECT extract_model FROM analysis_profiles WHERE id = :id
        """), {'id': profile_key}).fetchone()

        model_to_use = profile_row.extract_model if profile_row else 'llama3.1:8b'

        titles = [f"{e.title} (ID: {e.pmid})" for e in extractions][:100]

        prompt = f"""À partir de la liste de titres suivante, génère un graphe de connaissances. Identifie les 10 concepts les plus importants et leurs relations.

Ta réponse doit être UNIQUEMENT un objet JSON avec "nodes" (id, label) et "edges" (from, to, label).

Titres : {json.dumps(titles, indent=2)}"""

        graph_data = call_ollama_api(prompt, model=model_to_use, output_format="json")

        if graph_data and "nodes" in graph_data and "edges" in graph_data:
            update_project_status(project_id, status="completed", graph=graph_data)
        else:
            update_project_status(project_id, status="completed")

    except Exception as e:
        print(f"❌ Erreur graphe pour {project_id}: {e}")
        update_project_status(project_id, status="completed")
    finally:
        session.close()

def run_prisma_flow_task(project_id: str):
    """Génère un diagramme PRISMA pour un projet."""
    update_project_status(project_id, status="generating_prisma")
    session = Session()

    try:
        # Statistiques depuis search_results et extractions
        total_found = session.execute(text("""
            SELECT COUNT(*) FROM search_results WHERE project_id = :id
        """), {'id': project_id}).scalar()

        n_included = session.execute(text("""
            SELECT COUNT(*) FROM extractions WHERE project_id = :id
        """), {'id': project_id}).scalar()

        if total_found == 0:
            return

        n_after_duplicates = total_found
        n_excluded_screening = n_after_duplicates - n_included

        # Créer le diagramme
        fig, ax = plt.subplots(figsize=(8, 10))
        box_style = dict(boxstyle='round,pad=0.5', fc='lightblue', alpha=0.7)

        ax.text(0.5, 0.9, f'Articles identifiés (n = {total_found})', ha='center', va='center', bbox=box_style)
        ax.text(0.5, 0.7, f'Articles après exclusion des doublons (n = {n_after_duplicates})', ha='center', va='center', bbox=box_style)
        ax.text(0.5, 0.5, f'Articles évalués (n = {n_after_duplicates})', ha='center', va='center', bbox=box_style)
        ax.text(0.5, 0.3, f'Études incluses (n = {n_included})', ha='center', va='center', bbox=box_style)
        ax.text(1.0, 0.5, f'Exclus après criblage (n = {n_excluded_screening})', ha='left', va='center', bbox=box_style)

        ax.axis('off')

        # Sauvegarder l'image
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(exist_ok=True)
        image_path = str(project_dir / 'prisma_flow.png')
        plt.savefig(image_path, bbox_inches='tight')
        plt.close(fig)

        update_project_status(project_id, status="completed", prisma_path=image_path)

    except Exception as e:
        print(f"❌ Erreur PRISMA pour {project_id}: {e}")
        update_project_status(project_id, status="completed")
    finally:
        session.close()

def run_meta_analysis_task(project_id):
    """Exécute une méta-analyse et génère un Forest Plot."""
    send_project_notification(project_id, 'info', 'Méta-analyse (Forest Plot) en cours...')
    session = Session()

    try:
        extractions = session.execute(text("""
            SELECT extracted_data FROM extractions 
            WHERE project_id = :id AND extracted_data IS NOT NULL
        """), {'id': project_id}).fetchall()

        studies = []
        for row in extractions:
            try:
                data = json.loads(row.extracted_data)
                if all(k in data for k in ['study_name', 'effect_size', 'lower_ci', 'upper_ci']):
                    studies.append({
                        'name': str(data['study_name']),
                        'effect': float(data['effect_size']),
                        'lower': float(data['lower_ci']),
                        'upper': float(data['upper_ci'])
                    })
            except (ValueError, TypeError, json.JSONDecodeError):
                continue

        if len(studies) < 2:
            raise ValueError("Pas assez de données (moins de 2 études) pour une méta-analyse.")

        # Création du Forest Plot
        fig, ax = plt.subplots(figsize=(10, 2 + len(studies) * 0.5))
        y_pos = np.arange(len(studies))

        for i, study in enumerate(studies):
            error = [[study['effect'] - study['lower']], [study['upper'] - study['effect']]]
            ax.errorbar(study['effect'], y_pos[i], xerr=error, fmt='o', capsize=5)

        ax.axvline(0, color='grey', linestyle='--')
        ax.set_yticks(y_pos)
        ax.set_yticklabels([s['name'] for s in studies])
        ax.invert_yaxis()
        ax.set_xlabel("Effect Size (e.g., Odds Ratio)")
        ax.set_title("Forest Plot")

        plt.tight_layout()

        project_dir = PROJECTS_DIR / project_id
        plot_path = project_dir / "forest_plot.png"
        plt.savefig(plot_path)
        plt.close(fig)

        # Mettre à jour les chemins des graphiques dans la BDD
        plot_paths = {'meta_analysis': str(plot_path)}
        update_project_status(project_id, "completed", analysis_plot_path=json.dumps(plot_paths))

        send_project_notification(project_id, 'analysis_completed', 'Forest plot généré.')

    except Exception as e:
        error_msg = f"Erreur Méta-analyse : {e}"
        print(error_msg)
        send_project_notification(project_id, 'error', error_msg)
    finally:
        session.close()

def run_descriptive_stats_task(project_id: str):
    """Génère des statistiques descriptives pour un projet."""
    update_project_status(project_id, "generating_analysis")
    session = Session()

    try:
        extractions = session.execute(text("""
            SELECT extracted_data FROM extractions 
            WHERE project_id = :id AND extracted_data IS NOT NULL
        """), {'id': project_id}).fetchall()

        if not extractions:
            return

        records = []
        for ext in extractions:
            try:
                records.append(json.loads(ext.extracted_data))
            except (json.JSONDecodeError, TypeError):
                continue

        df = pd.json_normalize(records)

        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(exist_ok=True)

        plot_paths = {}

        # Graphique simple des types d'études
        if 'methodologie.type_etude' in df.columns:
            study_types = df['methodologie.type_etude'].value_counts()
            fig, ax = plt.subplots(figsize=(10, 6))
            study_types.plot(kind='bar', ax=ax)
            ax.set_title('Répartition des Types d\'Études')
            ax.set_ylabel('Nombre d\'Articles')
            plt.xticks(rotation=45, ha='right')
            plot_path = str(project_dir / 'study_types.png')
            plt.savefig(plot_path, bbox_inches='tight')
            plt.close(fig)
            plot_paths['study_types'] = plot_path

        summary_stats = {
            "total_articles": len(df)
        }

        update_project_status(project_id, "completed", analysis_result=summary_stats, analysis_plot_path=json.dumps(plot_paths))

    except Exception as e:
        print(f"❌ Erreur stats descriptives pour {project_id}: {e}")
        update_project_status(project_id, "failed")
    finally:
        session.close()

def run_atn_score_task(project_id: str):
    """Calcule un score ATN (Alliance Thérapeutique Numérique) personnalisé."""
    update_project_status(project_id, "generating_analysis")
    session = Session()

    try:
        extractions = session.execute(text("""
            SELECT id, pmid, title, extracted_data
            FROM extractions
            WHERE project_id = :id AND extracted_data IS NOT NULL
        """), {'id': project_id}).fetchall()

        if not extractions:
            update_project_status(project_id, "failed")
            return

        scores = []
        for ext in extractions:
            try:
                data = json.loads(ext.extracted_data)
                score = 0

                # Logique de scoring ATN
                if 'alliance' in str(data).lower() or 'therapeutic' in str(data).lower():
                    score += 3
                if any(tech in str(data).lower() for tech in ['numérique', 'digital', 'app', 'plateforme', 'ia']):
                    score += 3
                if any(stakeholder in str(data).lower() for stakeholder in ['patient', 'soignant', 'développeur']):
                    score += 2
                if any(outcome in str(data).lower() for outcome in ['empathie', 'adherence', 'confiance']):
                    score += 2

                scores.append({
                    'pmid': ext.pmid,
                    'title': ext.title,
                    'atn_score': min(score, 10)
                })

            except Exception as e:
                print(f"Erreur ATN pour {ext.pmid}: {e}")
                continue

        analysis_result = {
            "atn_scores": scores,
            "mean_atn": np.mean([s['atn_score'] for s in scores]) if scores else 0,
            "total_articles_scored": len(scores)
        }

        # Créer le graphique
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(exist_ok=True)
        plot_path = str(project_dir / 'atn_scores.png')

        if scores:
            fig, ax = plt.subplots(figsize=(10, 6))
            atn_values = [s['atn_score'] for s in scores]
            ax.hist(atn_values, bins=11, range=(-0.5, 10.5), alpha=0.7, color='green', edgecolor='black')
            ax.set_xlabel('Score ATN')
            ax.set_ylabel('Nombre d\'Articles')
            ax.set_title('Distribution des Scores ATN')
            ax.set_xticks(range(0, 11))
            plt.savefig(plot_path, bbox_inches='tight')
            plt.close(fig)

        update_project_status(project_id, "completed", analysis_result=analysis_result, analysis_plot_path=plot_path)

    except Exception as e:
        print(f"❌ Erreur ATN pour {project_id}: {e}")
        update_project_status(project_id, "failed")
    finally:
        session.close()

def import_pdfs_from_zotero_task(project_id: str, pmids: list, zotero_user_id: str, zotero_api_key: str):
    """Importe des PDF depuis Zotero pour une liste d'articles avec recherche ciblée."""
    if not all([zotero_user_id, zotero_api_key]):
        send_project_notification(project_id, 'zotero_import_failed', 'Identifiants Zotero non configurés.')
        return

    print(f"🔄 Lancement de l'import Zotero pour {len(pmids)} articles dans le projet {project_id}...")
    try:
        zot = zotero.Zotero(zotero_user_id, 'user', zotero_api_key)
        zot.key_info()
        print("✅ Connexion à l'API Zotero réussie.")
    except Exception as e:
        error_message = f'Échec de la connexion à Zotero: {e}'
        print(f"❌ {error_message}")
        send_project_notification(project_id, 'zotero_import_failed', error_message)
        return

    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(exist_ok=True)
    successful_imports = []
    failed_imports = []

    for article_id in pmids:
        try:
            # Interroger directement l'API Zotero pour l'article spécifique
            items = zot.items(q=article_id, limit=5)
            if not items:
                print(f"⏩ Article {article_id} non trouvé dans Zotero.")
                failed_imports.append(article_id)
                continue

            item = items[0] # On prend le premier résultat pertinent
            attachments = zot.children(item['key'])
            pdf_found = False
            for attachment in attachments:
                if attachment.get('data', {}).get('contentType') == 'application/pdf':
                    pdf_content = zot.file(attachment['key'])
                    safe_filename = sanitize_filename(article_id) + ".pdf"
                    pdf_path = project_dir / safe_filename
                    with open(pdf_path, 'wb') as f:
                        f.write(pdf_content)
                    print(f"✅ PDF téléchargé pour {article_id}")
                    successful_imports.append(article_id)
                    pdf_found = True
                    break
            
            if not pdf_found:
                failed_imports.append(article_id)

        except Exception as e:
            print(f"❌ Erreur de téléchargement pour {article_id}: {e}")
            failed_imports.append(article_id)
        
        time.sleep(0.3) # Politesse envers l'API

    message = f"Import Zotero terminé. {len(successful_imports)} PDF importés, {len(failed_imports)} échecs."
    print(f"📊 {message}")
    send_project_notification(
        project_id,
        'zotero_import_completed',
        message,
        {'successful': successful_imports, 'failed': list(set(failed_imports))}
    )
    
def fetch_online_pdf_task(project_id, article_ids):
    """Recherche et télécharge des PDF OA via DOI→Unpaywall."""
    print(f"🌐 Recherche OA (DOI→Unpaywall) pour {len(article_ids)} articles...")
    successful_ids = []
    session = Session()

    try:
        project_dir = PROJECTS_DIR / project_id
        project_dir.mkdir(exist_ok=True)

        # Récupérer les DOI des articles depuis la base de données
        articles = session.execute(text("""
            SELECT article_id, doi FROM search_results
            WHERE project_id = :project_id AND article_id = ANY(:article_ids)
        """), {
            'project_id': project_id,
            'article_ids': article_ids
        }).fetchall()

        for article in articles:
            try:
                article_id = article.article_id
                doi = article.doi

                if not doi:
                    print(f"⏩ Pas de DOI pour article {article_id}")
                    continue

                # Étape : DOI → URL PDF via Unpaywall
                pdf_url = fetch_unpaywall_pdf_url(doi)
                if not pdf_url:
                    print(f"⏩ Pas de PDF OA pour DOI {doi} (article {article_id})")
                    continue

                # Étape : Télécharger le PDF
                resp = http_get_with_retries(pdf_url, timeout=30)
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "").lower()
                    if content_type.startswith("application/pdf"):
                        safe_filename = sanitize_filename(article_id) + ".pdf"
                        pdf_path = project_dir / safe_filename

                        with open(pdf_path, "wb") as f:
                            f.write(resp.content)

                        print(f"✅ PDF OA téléchargé pour {article_id} sous le nom {safe_filename}")
                        successful_ids.append(article_id)
                    else:
                        print(f"⚠️ Contenu non-PDF pour article {article_id} (type: {content_type})")
                else:
                    print(f"⚠️ Statut HTTP {resp.status_code} pour article {article_id}")

                time.sleep(0.4)  # politesse API

            except Exception as e:
                print(f"❌ Erreur pour article {article_id}: {e}")
                continue

        # Mémoriser le résultat dans Redis
        redis_key = f"online_fetch_result:{project_id}"
        redis_conn.set(redis_key, json.dumps(successful_ids), ex=600)

        print(f"📊 OA terminé: {len(successful_ids)}/{len(article_ids)} PDF trouvés")

        # Notification de fin
        send_project_notification(
            project_id,
            'fetch_online_completed',
            f'Recherche OA terminée: {len(successful_ids)}/{len(article_ids)} PDF trouvés',
            {'successful_count': len(successful_ids), 'total_count': len(article_ids)}
        )

    except Exception as e:
        print(f"❌ Erreur critique OA: {e}")
        redis_key = f"online_fetch_result:{project_id}"
        redis_conn.set(redis_key, json.dumps([]), ex=600)
    finally:
        session.close()

def index_project_pdfs_task(project_id: str):
    """Indexe les PDF d'un projet avec normalisation, filtrage et embeddings."""
    print(f"📚 Indexation améliorée pour le projet {project_id}...")

    try:
        project_dir = PROJECTS_DIR / project_id
        chroma_client = chromadb.PersistentClient(path=str(project_dir / "chroma_db"))
        collection_name = f"project_{project_id}"

        try:
            chroma_client.delete_collection(collection_name)
            print(f"🗑️ Ancienne collection supprimée: {collection_name}")
        except Exception:
            pass  # C'est normal si la collection n'existait pas

        collection = chroma_client.create_collection(collection_name)

        pdf_files = list(project_dir.glob("*.pdf"))
        if not pdf_files:
            print("❌ Aucun PDF trouvé pour l'indexation")
            send_project_notification(
                project_id,
                'indexing_failed',
                'Aucun PDF trouvé pour l\'indexation'
            )
            return

        text_splitter = RecursiveCharacterTextSplitter(
            chunk_size=config.CHUNK_SIZE,
            chunk_overlap=config.CHUNK_OVERLAP,
            length_function=len,
        )

        all_documents, all_metadatas, all_ids = [], [], []
        total_filtered = 0
        successful_files = 0

        for pdf_file in pdf_files:
            try:
                text = extract_text_from_pdf(str(pdf_file))
                if not text or len(text.strip()) < MIN_CHUNK_LEN:
                    print(f"⚠️ PDF {pdf_file.name} ignoré (texte insuffisant)")
                    continue

                # Normalisation et chunking
                normalized_text = normalize_text(text)
                chunks = text_splitter.split_text(normalized_text)

                # Filtrage par taille minimale
                valid_chunks = [chunk for chunk in chunks if len(chunk) >= MIN_CHUNK_LEN]
                total_filtered += len(chunks) - len(valid_chunks)

                if not valid_chunks:
                    print(f"⚠️ PDF {pdf_file.name} ignoré (aucun chunk valide)")
                    continue

                print(f"📄 {pdf_file.name}: {len(valid_chunks)} chunks valides")

                # Préparer les métadonnées et IDs
                article_id = pdf_file.stem
                for i, chunk in enumerate(valid_chunks):
                    chunk_id = f"{article_id}_chunk_{i}"
                    metadata = {
                        "source": pdf_file.name,
                        "article_id": article_id,
                        "chunk_index": i,
                        "chunk_length": len(chunk)
                    }

                    all_documents.append(chunk)
                    all_metadatas.append(metadata)
                    all_ids.append(chunk_id)

                successful_files += 1

            except Exception as e:
                print(f"❌ Erreur lors du traitement de {pdf_file}: {e}")

        if not all_documents:
            print("❌ Aucun chunk valide trouvé pour l'indexation")
            send_project_notification(
                project_id,
                'indexing_failed',
                'Aucun contenu valide pour l\'indexation'
            )
            return

        print(f"🔢 Total: {len(all_documents)} chunks de {successful_files} fichiers")

        # Ajout par batch à ChromaDB avec embeddings
        batch_size = EMBED_BATCH
        for i in range(0, len(all_documents), batch_size):
            end_idx = min(i + batch_size, len(all_documents))
            batch_docs = all_documents[i:end_idx]
            batch_metadata = all_metadatas[i:end_idx]
            batch_ids = all_ids[i:end_idx]

            # Générer les embeddings avec SentenceTransformer
            embeddings = embedding_model.encode(batch_docs).tolist()

            collection.add(
                documents=batch_docs,
                metadatas=batch_metadata,
                ids=batch_ids,
                embeddings=embeddings
            )

            print(f"✅ Batch {i//batch_size + 1}: {len(batch_docs)} chunks indexés")

        # Marquer le projet comme indexé
        session = Session()
        try:
            session.execute(text("""
                UPDATE projects SET indexed_at = :indexed_at WHERE id = :id
            """), {
                'indexed_at': datetime.now(),
                'id': project_id
            })
            session.commit()
        except Exception as e:
            session.rollback()
            print(f"❌ Erreur mise à jour date indexation: {e}")
        finally:
            session.close()

        summary = f"Indexation terminée: {len(all_documents)} chunks de {successful_files} PDF"
        print(f"🎉 {summary}")

        send_project_notification(
            project_id,
            'indexing_completed',
            summary,
            {
                'total_chunks': len(all_documents),
                'successful_files': successful_files,
                'filtered_chunks': total_filtered
            }
        )

    except Exception as e:
        error_msg = f"Erreur critique indexation: {e}"
        print(f"❌ {error_msg}")
        send_project_notification(project_id, 'indexing_failed', error_msg)

def answer_chat_question_task(project_id: str, question: str, profile: dict):
    """Répond à une question de chat en utilisant le corpus indexé."""
    try:
        project_dir = PROJECTS_DIR / project_id
        chroma_path = project_dir / "chroma_db"

        if not chroma_path.exists():
            return {
                'answer': "❌ Corpus non indexé. Veuillez lancer l'indexation d'abord.",
                'sources': []
            }

        # Recherche dans ChromaDB
        chroma_client = chromadb.PersistentClient(path=str(chroma_path))
        collection_name = f"project_{project_id}"

        try:
            collection = chroma_client.get_collection(collection_name)
        except Exception:
            return {
                'answer': "❌ Collection d'indexation introuvable. Relancez l'indexation.",
                'sources': []
            }

        # Recherche sémantique
        query_embedding = embedding_model.encode([question]).tolist()
        results = collection.query(
            query_embeddings=query_embedding,
            n_results=5,
            include=["documents", "metadatas"]
        )

        if not results['documents'] or not results['documents'][0]:
            return {
                'answer': "❌ Aucun document pertinent trouvé pour cette question.",
                'sources': []
            }

        # Construire le contexte
        context_pieces = []
        sources = []
        for doc, metadata in zip(results['documents'][0], results['metadatas'][0]):
            context_pieces.append(doc)
            sources.append({
                'source': metadata['source'],
                'article_id': metadata['article_id']
            })

        context = "\n\n".join(context_pieces)

        # Prompt pour la génération de réponse
        prompt = f"""Basé sur le contexte suivant extrait du corpus de documents, répondez à la question de l'utilisateur.

CONTEXTE:
{context}

QUESTION: {question}

Fournissez une réponse détaillée et précise basée uniquement sur les informations du contexte. Si l'information n'est pas dans le contexte, dites-le clairement."""

        answer = call_ollama_api(prompt, profile['synthesis_model'])

        # Sauvegarder dans l'historique
        session = Session()
        try:
            # Message utilisateur
            session.execute(text("""
                INSERT INTO chat_messages (id, project_id, role, content, sources, timestamp)
                VALUES (:id, :project_id, :role, :content, :sources, :timestamp)
            """), {
                'id': str(uuid.uuid4()),
                'project_id': project_id,
                'role': 'user',
                'content': question,
                'sources': None,
                'timestamp': datetime.now()
            })

            # Réponse assistant
            session.execute(text("""
                INSERT INTO chat_messages (id, project_id, role, content, sources, timestamp)
                VALUES (:id, :project_id, :role, :content, :sources, :timestamp)
            """), {
                'id': str(uuid.uuid4()),
                'project_id': project_id,
                'role': 'assistant',
                'content': answer,
                'sources': json.dumps(sources),
                'timestamp': datetime.now()
            })

            session.commit()

        except Exception as e:
            session.rollback()
            print(f"Erreur sauvegarde chat: {e}")
        finally:
            session.close()

        return {
            'answer': answer,
            'sources': sources
        }

    except Exception as e:
        print(f"❌ Erreur chat: {e}")
        return {
            'answer': f"❌ Erreur lors de la génération de la réponse: {str(e)}",
            'sources': []
        }

# Fonctions d'import supplémentaires (placeholders)
def import_from_zotero_file_task(*args, **kwargs):
    """Placeholder pour l'import depuis fichier Zotero."""
    pass

def import_pdfs_from_zotero_task(project_id: str, pmids: list, zotero_user_id: str, zotero_api_key: str):
    """Importe des PDF depuis Zotero pour une liste d'articles avec recherche ciblée."""
    if not all([zotero_user_id, zotero_api_key]):
        send_project_notification(project_id, 'zotero_import_failed', 'Identifiants Zotero non configurés.')
        return

    print(f"🔄 Lancement de l'import Zotero pour {len(pmids)} articles dans le projet {project_id}...")
    try:
        zot = zotero.Zotero(zotero_user_id, 'user', zotero_api_key)
        zot.key_info()
        print("✅ Connexion à l'API Zotero réussie.")
    except Exception as e:
        error_message = f'Échec de la connexion à Zotero: {e}'
        print(f"❌ {error_message}")
        send_project_notification(project_id, 'zotero_import_failed', error_message)
        return

    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(exist_ok=True)
    successful_imports = []
    failed_imports = []

    for article_id in pmids:
        try:
            # Interroger directement l'API Zotero pour l'article spécifique
            items = zot.items(q=article_id, limit=5)
            if not items:
                print(f"⏩ Article {article_id} non trouvé dans Zotero.")
                failed_imports.append(article_id)
                continue

            item = items[0] # On prend le premier résultat pertinent
            attachments = zot.children(item['key'])
            pdf_found = False
            for attachment in attachments:
                if attachment.get('data', {}).get('contentType') == 'application/pdf':
                    pdf_content = zot.file(attachment['key'])
                    safe_filename = sanitize_filename(article_id) + ".pdf"
                    pdf_path = project_dir / safe_filename
                    with open(pdf_path, 'wb') as f:
                        f.write(pdf_content)
                    print(f"✅ PDF téléchargé pour {article_id}")
                    successful_imports.append(article_id)
                    pdf_found = True
                    break

            if not pdf_found:
                failed_imports.append(article_id)

        except Exception as e:
            print(f"❌ Erreur de téléchargement pour {article_id}: {e}")
            failed_imports.append(article_id)

        time.sleep(0.3) # Politesse envers l'API

    message = f"Import Zotero terminé. {len(successful_imports)} PDF importés, {len(failed_imports)} échecs."
    print(f"📊 {message}")
    send_project_notification(
        project_id,
        'zotero_import_completed',
        message,
        {'successful': successful_imports, 'failed': list(set(failed_imports))}
    )

def generate_prisma_diagram_task(*args, **kwargs):
    """Placeholder pour la génération de diagramme PRISMA."""
    pass