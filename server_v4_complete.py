# AnalyLit V4.0 - Serveur Flask COMPLET avec support PostgreSQL via SQLAlchemy
from gevent import monkey
monkey.patch_all()
import os
import uuid
import json
import logging
import io
import zipfile
import pandas as pd
from pathlib import Path
from datetime import datetime

from flask import Flask, jsonify, request, Blueprint, send_from_directory, Response, make_response
from flask_cors import CORS
from rq import Queue
from rq.job import Job
import redis
from flask_socketio import SocketIO, join_room, leave_room, emit
from sqlalchemy import create_engine, text, MetaData, Table, Column, String, Integer, Float, DateTime, Text, Boolean, ForeignKey
from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.exc import IntegrityError

from config_v4 import get_config
from tasks_v4_complete import (
    multi_database_search_task,
    process_single_article_task,
    run_synthesis_task,
    run_discussion_generation_task,
    run_knowledge_graph_task,
    run_prisma_flow_task,
    run_meta_analysis_task,
    run_descriptive_stats_task,
    pull_ollama_model_task,
    run_atn_score_task,
    import_pdfs_from_zotero_task,
    index_project_pdfs_task,
    answer_chat_question_task,
    fetch_online_pdf_task,
    db_manager,
    fetch_article_details,
    sanitize_filename,
    import_from_zotero_file_task,
)

# Configuration
config = get_config()
logging.basicConfig(level=getattr(logging, config.LOG_LEVEL))
logger = logging.getLogger(__name__)

# SQLAlchemy Setup
engine = create_engine(config.DATABASE_URL, pool_pre_ping=True, pool_recycle=300)
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)

# Flask app
app = Flask(__name__, static_folder='web', static_url_path='/')
api_bp = Blueprint('api', __name__, url_prefix='/api')
CORS(app, resources={r"/api/*": {"origins": "*"}})

# WebSocket
socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    async_mode='gevent',
    path='/socket.io/',
    message_queue=config.REDIS_URL,
    ping_interval=config.WEBSOCKET_PING_INTERVAL,
    ping_timeout=config.WEBSOCKET_PING_TIMEOUT
)

# Redis et files
redis_conn = redis.from_url(config.REDIS_URL)
processing_queue = Queue('analylit_processing_v4', connection=redis_conn)
synthesis_queue = Queue('analylit_synthesis_v4', connection=redis_conn)
analysis_queue = Queue('analylit_analysis_v4', connection=redis_conn)
background_queue = Queue('analylit_background_v4', connection=redis_conn)

PROJECTS_DIR = config.PROJECTS_DIR

def init_db():
    """Initialise la base de données PostgreSQL avec toutes les tables nécessaires."""
    logger.info("Initialisation de la base de données PostgreSQL...")
    
    try:
        with engine.connect() as conn:
            # Créer les tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'pending',
                    profile_used TEXT,
                    job_id TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP,
                    synthesis_result TEXT,
                    discussion_draft TEXT,
                    knowledge_graph TEXT,
                    prisma_flow_path TEXT,
                    analysis_mode TEXT DEFAULT 'screening',
                    analysis_result TEXT,
                    analysis_plot_path TEXT,
                    pmids_count INTEGER DEFAULT 0,
                    processed_count INTEGER DEFAULT 0,
                    total_processing_time REAL DEFAULT 0,
                    indexed_at TIMESTAMP,
                    search_query TEXT,
                    databases_used TEXT,
                    inter_rater_reliability TEXT
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS search_results (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    article_id TEXT NOT NULL,
                    zotero_key TEXT,
                    title TEXT,
                    abstract TEXT,
                    authors TEXT,
                    publication_date TEXT,
                    journal TEXT,
                    doi TEXT,
                    url TEXT,
                    database_source TEXT NOT NULL,
                    created_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS extractions (
                    id TEXT PRIMARY KEY,
                    project_id TEXT,
                    pmid TEXT,
                    title TEXT,
                    validation_score REAL,
                    created_at TIMESTAMP,
                    extracted_data TEXT,
                    relevance_score REAL DEFAULT 0,
                    relevance_justification TEXT,
                    validations TEXT,
                    analysis_source TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects(id),
                    UNIQUE (project_id, pmid) -- AJOUTEZ CETTE LIGNE
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS processing_log (
                    id SERIAL PRIMARY KEY,
                    project_id TEXT,
                    pmid TEXT,
                    status TEXT,
                    details TEXT,
                    timestamp TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS analysis_profiles (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    is_custom BOOLEAN DEFAULT TRUE,
                    preprocess_model TEXT NOT NULL,
                    extract_model TEXT NOT NULL,
                    synthesis_model TEXT NOT NULL
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS prompts (
                    id SERIAL PRIMARY KEY,
                    name TEXT NOT NULL UNIQUE,
                    description TEXT,
                    template TEXT NOT NULL
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS extraction_grids (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    fields TEXT NOT NULL,
                    created_at TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT,
                    timestamp TIMESTAMP,
                    FOREIGN KEY (project_id) REFERENCES projects(id)
                )
            """))

            # Insérer les profils par défaut
            profiles_count = conn.execute(text("SELECT COUNT(*) FROM analysis_profiles")).scalar()
            if profiles_count == 0:
                default_profiles = [
                    ('fast', 'Rapide', False, 'gemma:2b', 'phi3:mini', 'llama3.1:8b'),
                    ('standard', 'Standard', False, 'phi3:mini', 'llama3.1:8b', 'llama3.1:8b'),
                    ('deep', 'Approfondi', False, 'llama3.1:8b', 'mixtral:8x7b', 'llama3.1:70b')
                ]
                
                for profile in default_profiles:
                    conn.execute(text("""
                        INSERT INTO analysis_profiles (id, name, is_custom, preprocess_model, extract_model, synthesis_model)
                        VALUES (:id, :name, :is_custom, :preprocess_model, :extract_model, :synthesis_model)
                    """), {
                        'id': profile[0],
                        'name': profile[1],
                        'is_custom': profile[2],
                        'preprocess_model': profile[3],
                        'extract_model': profile[4],
                        'synthesis_model': profile[5]
                    })
                logger.info("✅ Profils par défaut insérés.")

            # Insérer les prompts par défaut
            prompts_count = conn.execute(text("SELECT COUNT(*) FROM prompts")).scalar()
            if prompts_count == 0:
                default_prompts = [
                    ('screening_prompt', 'Prompt pour la pré-sélection des articles.',
                     """En tant qu'assistant de recherche spécialisé, analysez cet article et déterminez sa pertinence pour une revue systématique.

Titre: {title}
Résumé: {abstract}
Source: {database_source}

Veuillez évaluer la pertinence de cet article sur une échelle de 1 à 10 et fournir une justification concise.

Répondez UNIQUEMENT avec un objet JSON contenant :
- "relevance_score": score numérique de 0 à 10
- "decision": "À inclure" si score >= 7, sinon "À exclure"
- "justification": phrase courte (max 30 mots) expliquant le score"""),

                    ('full_extraction_prompt', "Prompt pour l'extraction détaillée (grille).",
                     """ROLE: Vous êtes un assistant expert en analyse de littérature scientifique, spécialisé dans l'extraction de données structurées.

TÂCHE: Analysez le texte fourni et extrayez les informations demandées en respectant SCRUPULEUSEMENT le format JSON qui vous sera fourni.

INSTRUCTIONS IMPORTANTES:
1. Répondez **UNIQUEMENT** avec un objet JSON valide. N'ajoutez aucun texte, commentaire ou explication avant ou après le JSON.
2. Assurez-vous que chaque paire clé-valeur est séparée par une virgule, sauf la dernière.
3. Échappez correctement les guillemets doubles (") à l'intérieur des chaînes de caractères avec un antislash (\\).
4. Si une information n'est pas présente dans le texte, utilisez une chaîne de caractères vide ("") comme valeur. Ne laissez pas de champ vide ou avec "...".

TEXTE À ANALYSER:
---
{text}
---

SOURCE: {database_source}"""),

                    ('synthesis_prompt', 'Prompt pour la synthèse des résultats.',
                     """En tant que chercheur expert, analyse les résumés d'articles suivants fournis pour une revue de littérature. Ton objectif est de produire une synthèse structurée et critique au format JSON.

**CONTEXTE DE LA REVUE :** {project_description}

**RÉSUMÉS À ANALYSER :**
---
{data_for_prompt}
---

**INSTRUCTIONS :**
Réponds **UNIQUEMENT** avec un objet JSON valide contenant les clés suivantes :
- "relevance_evaluation": (String) Évalue si le corpus d'articles dans son ensemble semble pertinent pour répondre à la question de recherche initiale. Justifie brièvement.
- "main_themes": (Array de Strings) Identifie les 3 à 5 thèmes principaux ou axes de recherche qui émergent du corpus.
- "key_findings": (Array de Strings) Liste les résultats et conclusions les plus importants et récurrents.
- "methodologies_used": (Array de Strings) Résume les types de méthodologies d'étude les plus courantes (ex: 'Essais contrôlés randomisés', 'Études de cohorte', 'Revues systématiques').
- "synthesis_summary": (String) Rédige un paragraphe de synthèse global qui résume l'état de l'art basé sur ces articles, en incluant les convergences et les divergences notables.
- "research_gaps": (Array de Strings) Identifie les lacunes dans la recherche ou les questions qui restent sans réponse.""")
                ]

                for prompt in default_prompts:
                    conn.execute(text("""
                        INSERT INTO prompts (name, description, template) VALUES (:name, :description, :template)
                    """), {
                        'name': prompt[0],
                        'description': prompt[1],
                        'template': prompt[2]
                    })
                logger.info("✅ Prompts par défaut insérés.")

            conn.commit()
            logger.info("✅ Base de données PostgreSQL initialisée avec succès.")

    except Exception as e:
        logger.error(f"❌ Erreur lors de l'initialisation de la base de données: {e}")
        raise

@app.teardown_appcontext
def shutdown_session(exception=None):
    Session.remove()

def get_project_by_id(project_id: str):
    """Récupère un projet par son ID."""
    session = Session()
    try:
        result = session.execute(text("SELECT * FROM projects WHERE id = :id"), {'id': project_id}).fetchone()
        return dict(result._mapping) if result else None
    finally:
        Session.remove()

def update_project_status(project_id: str, status: str):
    """Met à jour le statut d'un projet."""
    session = Session()
    try:
        session.execute(text("""
            UPDATE projects SET status = :status, updated_at = :updated_at WHERE id = :id
        """), {
            'status': status,
            'updated_at': datetime.now(),
            'id': project_id
        })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Erreur mise à jour statut projet {project_id}: {e}")
    finally:
        Session.remove()

# --- API ENDPOINTS ---

@api_bp.route('/health', methods=['GET'])
def health_check():
    """Vérifie l'état de santé du serveur."""
    try:
        redis_status = "connected" if redis_conn.ping() else "disconnected"
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        logger.error(f"Erreur health check: {e}")
        db_status = "error"
        redis_status = "error"

    return jsonify({
        "status": "ok",
        "version": config.ANALYLIT_VERSION,
        "timestamp": datetime.now().isoformat(),
        "services": {
            "database": db_status,
            "redis": redis_status,
            "ollama": "unknown"
        }
    })

@api_bp.route('/databases', methods=['GET'])
def get_available_databases():
    """Récupère la liste des bases de données disponibles."""
    return jsonify(db_manager.get_available_databases())

@api_bp.route('/search', methods=['POST'])
def search_multiple_databases():
    """Lance une recherche dans plusieurs bases de données."""
    data = request.get_json()
    project_id = data.get('project_id')
    query = data.get('query')
    databases = data.get('databases', ['pubmed'])
    max_results_per_db = data.get('max_results_per_db', 50)

    if not project_id or not query:
        return jsonify({'error': 'project_id et query requis'}), 400

    # Sauvegarder les paramètres de recherche
    session = Session()
    try:
        session.execute(text("""
            UPDATE projects SET
            search_query = :query,
            databases_used = :databases,
            status = 'searching',
            updated_at = :updated_at
            WHERE id = :id
        """), {
            'query': query,
            'databases': json.dumps(databases),
            'updated_at': datetime.now(),
            'id': project_id
        })
        session.commit()
    except Exception as e:
        session.rollback()
        logger.error(f"Erreur sauvegarde paramètres recherche: {e}")
    finally:
        Session.remove()

    # Lancer la tâche de recherche
    job = background_queue.enqueue(
        multi_database_search_task,
        project_id=project_id,
        query=query,
        databases=databases,
        max_results_per_db=max_results_per_db,
        job_timeout='30m'
    )

    return jsonify({
        'message': f'Recherche lancée dans {len(databases)} base(s) de données',
        'job_id': job.id,
        'databases': databases
    }), 202

@api_bp.route('/projects/<project_id>/search-results', methods=['GET'])
def get_project_search_results(project_id):
    """Récupère les résultats de recherche d'un projet."""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    database_filter = request.args.get('database')
    offset = (page - 1) * per_page

    session = Session()
    try:
        # Construire la requête avec filtre optionnel
        base_query = "SELECT * FROM search_results WHERE project_id = :project_id"
        params = {'project_id': project_id}

        if database_filter:
            base_query += " AND database_source = :database_source"
            params['database_source'] = database_filter

        # Compter le total
        count_query = f"SELECT COUNT(*) FROM ({base_query}) as subq"
        total = session.execute(text(count_query), params).scalar()

        # Récupérer les résultats paginés
        results_query = f"{base_query} ORDER BY created_at DESC LIMIT :limit OFFSET :offset"
        params.update({'limit': per_page, 'offset': offset})
        results = session.execute(text(results_query), params).fetchall()

        return jsonify({
            'results': [dict(row._mapping) for row in results],
            'total': total,
            'page': page,
            'per_page': per_page,
            'has_next': offset + per_page < total,
            'has_prev': page > 1
        })
    except Exception as e:
        logger.error(f"Erreur récupération résultats recherche: {e}")
        return jsonify({"error": "Erreur interne du serveur"}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/search-stats', methods=['GET'])
def get_project_search_stats(project_id):
    """Récupère les statistiques de recherche d'un projet."""
    session = Session()
    try:
        # Statistiques par base de données
        stats = session.execute(text("""
            SELECT database_source, COUNT(*) as count
            FROM search_results
            WHERE project_id = :project_id
            GROUP BY database_source
        """), {'project_id': project_id}).fetchall()

        # Total
        total = session.execute(text("""
            SELECT COUNT(*) FROM search_results WHERE project_id = :project_id
        """), {'project_id': project_id}).scalar()

        return jsonify({
            'total_results': total,
            'results_by_database': {row.database_source: row.count for row in stats}
        })
    except Exception as e:
        logger.error(f"Erreur récupération stats recherche: {e}")
        return jsonify({"error": "Erreur interne du serveur"}), 500
    finally:
        Session.remove()

@api_bp.route('/queue-status', methods=['GET'])
def get_queue_status():
    """Récupère l'état des files d'attente."""
    queues = {
        'Traitement': processing_queue,
        'Synthèse': synthesis_queue,
        'Analyse': analysis_queue,
        'Tâches de fond': background_queue
    }
    status = {name: {'count': q.count} for name, q in queues.items()}
    return jsonify(status)

@api_bp.route('/queues/clear', methods=['POST'])
def clear_queues():
    """Vide une file d'attente spécifiée."""
    data = request.get_json()
    queue_name = data.get('queue_name')

    queues_map = {
        'Traitement': processing_queue,
        'Synthèse': synthesis_queue,
        'Analyse': analysis_queue,
        'Tâches de fond': background_queue
    }

    if queue_name in queues_map:
        q = queues_map[queue_name]
        q.empty()
        
        # Nettoyer le registre des échecs
        failed_registry = q.failed_job_registry
        for job_id in failed_registry.get_job_ids():
            failed_registry.remove(job_id, delete_job=True)

        return jsonify({'message': f'La file "{queue_name}" a été vidée.'}), 200

    return jsonify({'error': 'Nom de file invalide'}), 400

# Paramètres Zotero
@api_bp.route('/settings/zotero', methods=['POST'])
def save_zotero_settings():
    """Sauvegarde les paramètres Zotero."""
    data = request.get_json()
    zotero_config = {
        'user_id': data.get('userId'),
        'api_key': data.get('apiKey')
    }

    config_path = PROJECTS_DIR / 'zotero_config.json'
    with open(config_path, 'w') as f:
        json.dump(zotero_config, f)

    return jsonify({'message': 'Paramètres Zotero sauvegardés.'})

@api_bp.route('/settings/zotero', methods=['GET'])
def get_zotero_settings():
    """Récupère les paramètres Zotero."""
    config_path = PROJECTS_DIR / 'zotero_config.json'
    if config_path.exists():
        with open(config_path, 'r') as f:
            zotero_config = json.load(f)
        return jsonify({
            'userId': zotero_config.get('user_id', ''),
            'hasApiKey': bool(zotero_config.get('api_key'))
        })
    return jsonify({'userId': '', 'hasApiKey': False})

# Import depuis Zotero
@api_bp.route('/projects/<project_id>/import-zotero', methods=['POST'])
def import_from_zotero(project_id):
    """Lance l'import depuis Zotero pour une liste d'articles fournie."""
    data = request.get_json()
    manual_ids = data.get('articles', [])

    try:
        with open(PROJECTS_DIR / 'zotero_config.json', 'r') as f:
            zotero_config = json.load(f)
    except FileNotFoundError:
        return jsonify({'error': 'Veuillez configurer vos identifiants Zotero dans les paramètres.'}), 400

    # Ajoute les nouveaux articles à la base de données
    article_ids_to_process = add_manual_articles_to_project(project_id, manual_ids)

    if not article_ids_to_process:
        return jsonify({'error': 'Aucun article valide à importer pour ce projet.'}), 400

    job = background_queue.enqueue(
        import_pdfs_from_zotero_task,
        project_id=project_id,
        pmids=article_ids_to_process,
        zotero_user_id=zotero_config.get('user_id'),
        zotero_api_key=zotero_config.get('api_key'),
        job_timeout='1h'
    )

    return jsonify({'message': f'Import depuis Zotero lancé pour {len(article_ids_to_process)} articles.'}), 202

@api_bp.route('/projects/<project_id>/zotero-import-status', methods=['GET'])
def get_zotero_import_status(project_id):
    """Récupère le statut de l'import Zotero."""
    redis_key = f"zotero_import_result:{project_id}"
    result = redis_conn.get(redis_key)

    if result:
        redis_conn.delete(redis_key)
        successful_pmids = json.loads(result)
        return jsonify({
            'status': 'completed',
            'successful_pmids': successful_pmids
        })
    else:
        return jsonify({'status': 'pending'})

@api_bp.route('/projects/<project_id>/import-zotero-file', methods=['POST'])
def import_zotero_file(project_id):
    """Importe des références depuis un fichier Zotero JSON."""
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier fourni."}), 400

    file = request.files['file']
    if not file or not file.filename.endswith('.json'):
        return jsonify({"error": "Veuillez fournir un fichier .json."}), 400
    
    try:
        # Lire le contenu du fichier en mémoire
        file_content = file.stream.read().decode("utf-8")
        
        # Lancer la tâche de fond avec le contenu du fichier
        job = background_queue.enqueue(
            import_from_zotero_file_task,
            project_id=project_id,
            json_content=file_content,
            job_timeout='1h'
        )
        
        return jsonify({
            'message': 'L\'import depuis le fichier Zotero a été lancé.',
            'job_id': job.id
        }), 202
        
    except Exception as e:
        logger.error(f"Erreur lors de l'import du fichier Zotero: {e}")
        return jsonify({"error": "Erreur interne du serveur lors de l'import."}), 500
        
# Upload PDF en lot
def add_manual_articles_to_project(project_id, article_ids):
    """Ajoute une liste d'articles (PMID/DOI) à la base de données d'un projet."""
    processed_ids = []
    session = Session()
    
    try:
        for article_id in article_ids:
            if not article_id or not isinstance(article_id, str):
                continue

            exists = session.execute(text("""
                SELECT 1 FROM search_results WHERE project_id = :project_id AND article_id = :article_id
            """), {'project_id': project_id, 'article_id': article_id}).fetchone()

            if exists:
                processed_ids.append(article_id)
                continue

            details = fetch_article_details(article_id)
            if details and details.get('title') != 'Erreur de récupération':
                session.execute(text("""
                    INSERT INTO search_results (id, project_id, article_id, title, abstract, database_source, created_at, url, doi, authors, journal, publication_date)
                    VALUES (:id, :project_id, :article_id, :title, :abstract, :database_source, :created_at, :url, :doi, :authors, :journal, :publication_date)
                """), {
                    'id': str(uuid.uuid4()),
                    'project_id': project_id,
                    'article_id': article_id,
                    'title': details.get('title', 'Titre non trouvé'),
                    'abstract': details.get('abstract', ''),
                    'database_source': details.get('database_source', 'manual'),
                    'created_at': datetime.now(),
                    'url': details.get('url'),
                    'doi': details.get('doi'),
                    'authors': details.get('authors'),
                    'journal': details.get('journal'),
                    'publication_date': details.get('publication_date')
                })
                processed_ids.append(article_id)

        session.commit()

        # Mettre à jour le compteur total
        total_articles = session.execute(text("""
            SELECT COUNT(*) FROM search_results WHERE project_id = :project_id
        """), {'project_id': project_id}).scalar()

        session.execute(text("""
            UPDATE projects SET pmids_count = :count WHERE id = :project_id
        """), {'count': total_articles, 'project_id': project_id})

        session.commit()
        return processed_ids

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur ajout articles manuels: {e}")
        return []
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/upload-pdfs-bulk', methods=['POST'])
def upload_pdfs_bulk(project_id):
    if 'files' not in request.files:
        return jsonify({'error': 'Aucun fichier fourni'}), 400

    files = request.files.getlist('files')
    project_dir = Path(config.PROJECTS_DIR) / project_id
    project_dir.mkdir(exist_ok=True)

    successful = []
    failed = []

    for file in files:
        if file and file.filename:
            filename_base = Path(file.filename).stem
            safe_filename = sanitize_filename(filename_base) + ".pdf"
            pdf_path = project_dir / safe_filename

            try:
                if file.content_length > config.MAX_PDF_SIZE:
                    failed.append(f"{file.filename}: Fichier trop volumineux (max {config.MAX_PDF_SIZE / 1024 / 1024} Mo)")
                    continue

                file.save(str(pdf_path))
                successful.append(safe_filename)
            except Exception as e:
                failed.append(f"{safe_filename}: {str(e)}")

    return jsonify({'successful': successful, 'failed': failed}), 200

# Recherche PDF en ligne
@api_bp.route('/projects/<project_id>/fetch-online-pdfs', methods=['POST'])
def fetch_online_pdfs(project_id):
    """Lance la recherche de PDF en ligne pour une liste d'articles fournie."""
    data = request.get_json()
    manual_ids = data.get('articles', [])

    article_ids_to_process = add_manual_articles_to_project(project_id, manual_ids)

    if not article_ids_to_process:
        return jsonify({'error': 'Aucun article valide à traiter pour ce projet.'}), 400

    job = background_queue.enqueue(
        fetch_online_pdf_task,
        project_id=project_id,
        article_ids=article_ids_to_process,
        job_timeout='1h'
    )

    return jsonify({'message': f'La recherche de PDF en ligne a été lancée pour {len(article_ids_to_process)} articles.'}), 202

@api_bp.route('/projects/<project_id>/fetch-online-status', methods=['GET'])
def get_fetch_online_status(project_id):
    """Récupère le statut de la recherche PDF en ligne."""
    redis_key = f"online_fetch_result:{project_id}"
    result = redis_conn.get(redis_key)

    if result:
        redis_conn.delete(redis_key)
        successful_ids = json.loads(result)
        return jsonify({
            'status': 'completed',
            'successful_pmids': successful_ids
        })
    else:
        return jsonify({'status': 'pending'})

# Indexation
@api_bp.route('/projects/<project_id>/index', methods=['POST'])
def run_indexing(project_id):
    """Lance l'indexation des PDF d'un projet."""
    job = background_queue.enqueue(
        index_project_pdfs_task,
        project_id=project_id,
        job_timeout='1h'
    )

    update_project_status(project_id, 'indexing')

    return jsonify({
        'message': 'L\'indexation du corpus a été lancée.',
        'job_id': job.id
    }), 202

# Chat
@api_bp.route('/projects/<project_id>/chat', methods=['POST'])
def handle_chat_message(project_id):
    """Traite un message de chat."""
    data = request.get_json()
    question = data.get('question')
    profile_id = data.get('profile', 'standard')

    session = Session()
    try:
        profile_row = session.execute(text("""
            SELECT * FROM analysis_profiles WHERE id = :id
        """), {'id': profile_id}).fetchone()

        if not profile_row:
            return jsonify({'error': 'Profil invalide'}), 400

        profile = dict(profile_row._mapping)

        try:
            result = answer_chat_question_task(project_id, question, profile)
            return jsonify(result)
        except Exception as e:
            logger.error(f"Erreur lors du chat pour le projet {project_id}: {e}")
            return jsonify({'error': 'Erreur lors de la génération de la réponse.'}), 500

    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/chat-history', methods=['GET'])
def get_chat_history(project_id):
    """Récupère l'historique de chat."""
    session = Session()
    try:
        messages = session.execute(text("""
            SELECT role, content, sources, timestamp FROM chat_messages
            WHERE project_id = :project_id ORDER BY timestamp ASC
        """), {'project_id': project_id}).fetchall()

        return jsonify([dict(row._mapping) for row in messages])
    finally:
        Session.remove()

# Ollama
@api_bp.route('/ollama/models', methods=['GET'])
def get_ollama_local_models():
    """Récupère la liste des modèles Ollama installés."""
    try:
        import requests
        response = requests.get(f"{config.OLLAMA_BASE_URL}/api/tags")
        response.raise_for_status()
        return jsonify(response.json().get('models', []))
    except requests.RequestException as e:
        logger.error(f"Erreur de communication avec Ollama: {e}")
        return jsonify({'error': 'Impossible de contacter le service Ollama.'}), 503

@api_bp.route('/ollama/pull', methods=['POST'])
def pull_ollama_model():
    """Lance le téléchargement d'un modèle Ollama."""
    data = request.get_json()
    model_name = data.get('model_name')

    if not model_name:
        return jsonify({'error': 'Le nom du modèle est requis.'}), 400

    job = background_queue.enqueue(
        pull_ollama_model_task,
        model_name,
        job_timeout='1h'
    )

    return jsonify({
        'message': f'Le téléchargement du modèle "{model_name}" a été lancé.',
        'job_id': job.id
    }), 202

# Prompts
@api_bp.route('/prompts', methods=['GET'])
def get_prompts():
    """Récupère la liste des prompts."""
    session = Session()
    try:
        prompts = session.execute(text("""
            SELECT id, name, description, template FROM prompts
        """)).fetchall()

        return jsonify([dict(row._mapping) for row in prompts])
    finally:
        Session.remove()

@api_bp.route('/prompts/<int:prompt_id>', methods=['PUT'])
def update_prompt(prompt_id):
    """Met à jour un prompt."""
    data = request.get_json()
    template = data.get('template')

    session = Session()
    try:
        session.execute(text("""
            UPDATE prompts SET template = :template WHERE id = :id
        """), {'template': template, 'id': prompt_id})
        session.commit()

        return jsonify({'message': 'Prompt mis à jour.'})
    except Exception as e:
        session.rollback()
        logger.error(f"Erreur mise à jour prompt: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

# Profils d'analyse
@api_bp.route('/analysis-profiles', methods=['GET'])
def get_analysis_profiles():
    """Récupère la liste des profils d'analyse."""
    session = Session()
    try:
        profiles = session.execute(text("""
            SELECT * FROM analysis_profiles ORDER BY is_custom, name
        """)).fetchall()

        return jsonify([dict(row._mapping) for row in profiles])
    finally:
        Session.remove()

@api_bp.route('/analysis-profiles', methods=['POST'])
def create_analysis_profile():
    """Crée un nouveau profil d'analyse personnalisé."""
    data = request.get_json()
    required_fields = ['name', 'preprocess_model', 'extract_model', 'synthesis_model']

    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Tous les champs sont requis'}), 400

    profile_id = str(uuid.uuid4())
    session = Session()

    try:
        session.execute(text("""
            INSERT INTO analysis_profiles
            (id, name, is_custom, preprocess_model, extract_model, synthesis_model)
            VALUES (:id, :name, :is_custom, :preprocess_model, :extract_model, :synthesis_model)
        """), {
            'id': profile_id,
            'name': data['name'],
            'is_custom': True,
            'preprocess_model': data['preprocess_model'],
            'extract_model': data['extract_model'],
            'synthesis_model': data['synthesis_model']
        })
        session.commit()

        logger.info(f"✅ Nouveau profil créé: {data['name']} (ID: {profile_id})")
        return jsonify({'message': 'Profil créé avec succès', 'id': profile_id}), 201

    except IntegrityError:
        session.rollback()
        return jsonify({'error': 'Un profil avec ce nom existe déjà'}), 409
    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la création du profil: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/analysis-profiles/<profile_id>', methods=['PUT'])
def update_analysis_profile(profile_id):
    """Met à jour un profil d'analyse personnalisé."""
    data = request.get_json()
    required_fields = ['name', 'preprocess_model', 'extract_model', 'synthesis_model']

    if not all(field in data for field in required_fields):
        return jsonify({'error': 'Tous les champs sont requis'}), 400

    session = Session()
    try:
        result = session.execute(text("""
            UPDATE analysis_profiles SET
            name = :name, preprocess_model = :preprocess_model, 
            extract_model = :extract_model, synthesis_model = :synthesis_model
            WHERE id = :id AND is_custom = TRUE
        """), {
            'name': data['name'],
            'preprocess_model': data['preprocess_model'],
            'extract_model': data['extract_model'],
            'synthesis_model': data['synthesis_model'],
            'id': profile_id
        })

        if result.rowcount == 0:
            return jsonify({'error': 'Profil non trouvé ou non modifiable'}), 404

        session.commit()
        return jsonify({'message': 'Profil mis à jour avec succès'})

    except IntegrityError:
        session.rollback()
        return jsonify({'error': 'Un profil avec ce nom existe déjà'}), 409
    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la mise à jour du profil: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/analysis-profiles/<profile_id>', methods=['DELETE'])
def delete_analysis_profile(profile_id):
    """Supprime un profil d'analyse personnalisé."""
    session = Session()
    try:
        result = session.execute(text("""
            DELETE FROM analysis_profiles WHERE id = :id AND is_custom = TRUE
        """), {'id': profile_id})

        if result.rowcount == 0:
            return jsonify({'error': 'Profil non trouvé ou non modifiable'}), 404

        session.commit()
        return jsonify({'message': 'Profil supprimé avec succès'})

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la suppression du profil: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

# Projets
@api_bp.route('/projects', methods=['GET'])
def get_projects():
    """Récupère la liste des projets."""
    session = Session()
    try:
        projects = session.execute(text("""
            SELECT * FROM projects ORDER BY updated_at DESC
        """)).fetchall()

        return jsonify([dict(row._mapping) for row in projects])
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>', methods=['GET'])
def get_project_details(project_id):
    """Récupère les détails d'un projet."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT * FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        if project is None:
            return jsonify({'error': 'Projet non trouvé'}), 404

        return jsonify(dict(project._mapping))
    finally:
        Session.remove()

@api_bp.route('/projects', methods=['POST'])
def create_project():
    """Crée un nouveau projet."""
    data = request.get_json()
    analysis_mode = data.get('mode', 'screening')
    project_id = str(uuid.uuid4())
    now = datetime.now()

    session = Session()
    try:
        session.execute(text("""
            INSERT INTO projects (id, name, description, created_at, updated_at, analysis_mode)
            VALUES (:id, :name, :description, :created_at, :updated_at, :analysis_mode)
        """), {
            'id': project_id,
            'name': data['name'],
            'description': data.get('description', ''),
            'created_at': now,
            'updated_at': now,
            'analysis_mode': analysis_mode
        })
        session.commit()

        return jsonify({'id': project_id, 'name': data['name']}), 201

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur création projet: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>', methods=['DELETE'])
def delete_project(project_id):
    """Supprime un projet."""
    session = Session()
    try:
        # Supprimer dans l'ordre à cause des clés étrangères
        session.execute(text("DELETE FROM search_results WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM extractions WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM processing_log WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM extraction_grids WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM chat_messages WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM projects WHERE id = :id"), {'id': project_id})
        session.commit()

        return jsonify({'message': 'Projet supprimé'}), 200

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur suppression projet: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

# Grilles d'extraction
@api_bp.route('/projects/<project_id>/grids', methods=['POST'])
def create_extraction_grid(project_id):
    """Crée une nouvelle grille d'extraction."""
    data = request.get_json()
    name = data.get('name')
    fields = data.get('fields')

    if not name or not isinstance(fields, list) or not fields:
        return jsonify({'error': 'Le nom et une liste de champs sont requis.'}), 400

    grid_id = str(uuid.uuid4())
    now = datetime.now()
    fields_json = json.dumps(fields)

    session = Session()
    try:
        session.execute(text("""
            INSERT INTO extraction_grids (id, project_id, name, fields, created_at)
            VALUES (:id, :project_id, :name, :fields, :created_at)
        """), {
            'id': grid_id,
            'project_id': project_id,
            'name': name,
            'fields': fields_json,
            'created_at': now
        })
        session.commit()

        new_grid = {
            'id': grid_id,
            'project_id': project_id,
            'name': name,
            'fields': fields,
            'created_at': now.isoformat()
        }

        return jsonify(new_grid), 201

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la création de la grille pour le projet {project_id}: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/grids', methods=['GET'])
def get_extraction_grids(project_id):
    """Récupère toutes les grilles d'extraction pour un projet."""
    session = Session()
    try:
        grids_rows = session.execute(text("""
            SELECT id, name, fields, created_at FROM extraction_grids
            WHERE project_id = :project_id ORDER BY created_at DESC
        """), {'project_id': project_id}).fetchall()

        grids = []
        for row in grids_rows:
            grid = dict(row._mapping)
            grid['fields'] = json.loads(grid['fields'])
            grids.append(grid)

        return jsonify(grids)

    except Exception as e:
        logger.error(f"Erreur lors de la récupération des grilles pour le projet {project_id}: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/grids/<grid_id>', methods=['PUT'])
def update_extraction_grid(project_id, grid_id):
    """Met à jour une grille d'extraction."""
    data = request.get_json()
    name = data.get('name')
    fields = data.get('fields')

    if not name or not isinstance(fields, list) or not fields:
        return jsonify({'error': 'Le nom et une liste de champs sont requis.'}), 400

    fields_json = json.dumps(fields)

    session = Session()
    try:
        result = session.execute(text("""
            UPDATE extraction_grids SET name = :name, fields = :fields
            WHERE id = :grid_id AND project_id = :project_id
        """), {
            'name': name,
            'fields': fields_json,
            'grid_id': grid_id,
            'project_id': project_id
        })

        if result.rowcount == 0:
            return jsonify({'error': 'Grille non trouvée ou n\'appartient pas à ce projet.'}), 404

        session.commit()
        return jsonify({'message': 'Grille mise à jour avec succès.'})

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la mise à jour de la grille {grid_id}: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/grids/<grid_id>', methods=['DELETE'])
def delete_extraction_grid(project_id, grid_id):
    """Supprime une grille d'extraction."""
    session = Session()
    try:
        result = session.execute(text("""
            DELETE FROM extraction_grids
            WHERE id = :grid_id AND project_id = :project_id
        """), {'grid_id': grid_id, 'project_id': project_id})

        if result.rowcount == 0:
            return jsonify({'error': 'Grille non trouvée ou n\'appartient pas à ce projet.'}), 404

        session.commit()
        return jsonify({'message': 'Grille supprimée avec succès.'})

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lors de la suppression de la grille {grid_id}: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/grids/import', methods=['POST'])
def import_grid_from_file(project_id):
    """Importe une grille d'extraction depuis un fichier JSON."""
    if 'file' not in request.files:
        return jsonify({"error": "Aucun fichier n'a été envoyé"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "Aucun fichier sélectionné"}), 400

    if file and file.filename.endswith('.json'):
        try:
            grid_data = json.load(file.stream)
            grid_name = grid_data.get('name')
            grid_fields = grid_data.get('fields')

            if not grid_name or not isinstance(grid_fields, list):
                return jsonify({"error": "Le fichier JSON doit contenir une clé 'name' et une clé 'fields' (liste)"}), 400

            session = Session()
            try:
                session.execute(text("""
                    INSERT INTO extraction_grids (id, project_id, name, fields, created_at)
                    VALUES (:id, :project_id, :name, :fields, :created_at)
                """), {
                    'id': str(uuid.uuid4()),
                    'project_id': project_id,
                    'name': grid_name,
                    'fields': json.dumps(grid_fields),
                    'created_at': datetime.now()
                })
                session.commit()

                return jsonify({"message": "Grille importée avec succès"}), 201

            except Exception as e:
                session.rollback()
                raise e
            finally:
                Session.remove()

        except json.JSONDecodeError:
            return jsonify({"error": "Fichier JSON invalide"}), 400
        except Exception as e:
            logger.error(f"Erreur lors de l'importation de la grille: {e}")
            return jsonify({"error": "Erreur interne du serveur"}), 500

    return jsonify({"error": "Type de fichier non supporté. Veuillez utiliser un fichier .json"}), 400

# Pipeline de traitement
@api_bp.route('/projects/<project_id>/run', methods=['POST'])
def run_project_pipeline(project_id):
    """Lance le pipeline d'analyse pour un projet sur une liste d'articles fournie."""
    data = request.get_json()
    selected_articles = data.get('articles', [])
    profile_id = data.get('profile', 'standard')
    custom_grid_id = data.get('custom_grid_id')
    analysis_mode = data.get('analysis_mode', 'screening')

    if not selected_articles:
        return jsonify({'error': 'La liste d\'articles est requise.'}), 400

    session = Session()
    try:
        profile_row = session.execute(text("""
            SELECT * FROM analysis_profiles WHERE id = :id
        """), {'id': profile_id}).fetchone()

        if not profile_row:
            return jsonify({'error': f"Profil invalide: '{profile_id}'"}), 400

        profile = dict(profile_row._mapping)

        project = session.execute(text("""
            SELECT analysis_mode FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        analysis_mode = project.analysis_mode if project else 'screening'

        # Nettoyage et mise à jour du projet
        session.execute(text("DELETE FROM extractions WHERE project_id = :id"), {'id': project_id})
        session.execute(text("DELETE FROM processing_log WHERE project_id = :id"), {'id': project_id})

        session.execute(text("""
            UPDATE projects SET
            status = 'processing', profile_used = :profile_used, updated_at = :updated_at, 
            pmids_count = :pmids_count, processed_count = 0, total_processing_time = 0
            WHERE id = :id
        """), {
            'profile_used': profile_id,
            'updated_at': datetime.now(),
            'pmids_count': len(selected_articles),
            'id': project_id
        })

        session.execute(text("""
            UPDATE projects SET analysis_mode = :analysis_mode WHERE id = :id
        """), {'analysis_mode': analysis_mode, 'id': project_id})

        session.commit()

        # Lancer les tâches
        for article_id in selected_articles:
            processing_queue.enqueue(
                process_single_article_task,
                project_id=project_id,
                article_id=article_id,
                profile=profile,
                analysis_mode=analysis_mode,
                custom_grid_id=custom_grid_id,
                job_timeout=1800
            )

        return jsonify({"status": "processing"}), 202

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lancement pipeline: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/run-synthesis', methods=['POST'])
def run_synthesis_endpoint(project_id):
    """Lance la synthèse des résultats."""
    data = request.get_json()
    profile_id = data.get('profile')

    session = Session()
    try:
        profile_row = session.execute(text("""
            SELECT * FROM analysis_profiles WHERE id = :id
        """), {'id': profile_id}).fetchone()

        if not profile_row:
            return jsonify({'error': f"Profil invalide: '{profile_id}'"}), 400

        profile_to_use = dict(profile_row._mapping)

        job = synthesis_queue.enqueue(
            run_synthesis_task,
            project_id=project_id,
            profile=profile_to_use,
            job_timeout=3600
        )

        session.execute(text("""
            UPDATE projects SET status = 'synthesizing', job_id = :job_id WHERE id = :id
        """), {'job_id': job.id, 'id': project_id})
        session.commit()

        return jsonify({
            "status": "synthesizing",
            "message": "La synthèse des résultats a été lancée."
        }), 202

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur lancement synthèse: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

# Extractions
@api_bp.route('/projects/<project_id>/extractions', methods=['GET'])
def get_project_extractions(project_id):
    """Récupère les extractions d'un projet, y compris l'abstract et l'URL."""
    session = Session()
    try:
        extractions = session.execute(text("""
            SELECT
                e.id, e.pmid, e.title, e.relevance_score, e.relevance_justification,
                e.validations, e.extracted_data, e.analysis_source,
                s.abstract, s.url
            FROM extractions e
            LEFT JOIN search_results s ON e.project_id = s.project_id AND e.pmid = s.article_id
            WHERE e.project_id = :project_id
            ORDER BY e.relevance_score DESC
        """), {'project_id': project_id}).fetchall()

        return jsonify([dict(row._mapping) for row in extractions])

    finally:
        Session.remove()

# Logs et résultats
@api_bp.route('/projects/<project_id>/processing-log', methods=['GET'])
def get_project_processing_log(project_id):
    """Récupère les logs de traitement d'un projet."""
    session = Session()
    try:
        logs = session.execute(text("""
            SELECT pmid, status, details, timestamp FROM processing_log
            WHERE project_id = :project_id ORDER BY id DESC LIMIT 100
        """), {'project_id': project_id}).fetchall()

        return jsonify([dict(row._mapping) for row in logs])
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/result', methods=['GET'])
def get_project_result(project_id):
    """Récupère le résultat de synthèse d'un projet."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT synthesis_result FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        if project and project.synthesis_result:
            return jsonify(json.loads(project.synthesis_result))

        return jsonify({})
    finally:
        Session.remove()

# Export
@api_bp.route('/projects/<project_id>/export', methods=['GET'])
def export_results_csv(project_id):
    """Exporte les résultats au format CSV."""
    session = Session()
    try:
        extractions = session.execute(text("""
            SELECT * FROM extractions WHERE project_id = :project_id
        """), {'project_id': project_id}).fetchall()

        if not extractions:
            return jsonify({"error": "Aucune donnée à exporter."}), 404

        records = []
        for ext in extractions:
            ext_dict = dict(ext._mapping)
            base_record = {
                "pmid": ext_dict["pmid"],
                "title": ext_dict["title"],
                "relevance_score": ext_dict["relevance_score"],
                "relevance_justification": ext_dict["relevance_justification"],
                "validations": ext_dict["validations"],
                "validation_score": ext_dict["validation_score"],
                "created_at": ext_dict["created_at"]
            }

            # Ajouter les données extraites si disponibles
            try:
                if ext_dict['extracted_data']:
                    data = json.loads(ext_dict['extracted_data'])
                    if isinstance(data, dict):
                        for category, details in data.items():
                            if isinstance(details, dict):
                                for key, value in details.items():
                                    base_record[f"{category}_{key}"] = value
                            else:
                                base_record[category] = details
            except (json.JSONDecodeError, TypeError):
                pass

            records.append(base_record)

        df = pd.DataFrame(records)
        csv_data = df.to_csv(index=False)

        return Response(
            csv_data,
            mimetype="text/csv",
            headers={"Content-disposition": f"attachment; filename=export_{project_id}.csv"}
        )

    except Exception as e:
        logger.error(f"Erreur d'export CSV pour {project_id}: {e}")
        return jsonify({"error": "Erreur interne du serveur lors de l'export."}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/export-all', methods=['GET'])
def export_all_data_zip(project_id):
    """Exporte toutes les données d'un projet dans une archive ZIP."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT * FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        extractions = session.execute(text("""
            SELECT * FROM extractions WHERE project_id = :id
        """), {'id': project_id}).fetchall()

        search_results = session.execute(text("""
            SELECT * FROM search_results WHERE project_id = :id
        """), {'id': project_id}).fetchall()

        if not project:
            return jsonify({"error": "Projet non trouvé."}), 404

        project_dict = dict(project._mapping)

        memory_file = io.BytesIO()
        with zipfile.ZipFile(memory_file, 'w', zipfile.ZIP_DEFLATED) as zf:
            summary = f"""Rapport d'Exportation pour le Projet AnalyLit V4
-------------------------------------------------
ID du Projet: {project_dict.get('id', 'N/A')}
Nom: {project_dict.get('name', 'N/A')}
Description: {project_dict.get('description', 'N/A')}
Date de création: {project_dict.get('created_at', 'N/A')}
Dernière mise à jour: {project_dict.get('updated_at', 'N/A')}
Statut: {project_dict.get('status', 'N/A')}
Profil utilisé: {project_dict.get('profile_used', 'N/A')}
Mode d'analyse: {project_dict.get('analysis_mode', 'N/A')}
Nombre d'articles: {project_dict.get('pmids_count', 0)}
Requête de recherche: {project_dict.get('search_query', 'N/A')}
Bases de données utilisées: {project_dict.get('databases_used', 'N/A')}
"""
            zf.writestr('summary.txt', summary)

            if search_results:
                df_search = pd.DataFrame([dict(row._mapping) for row in search_results])
                zf.writestr('search_results.csv', df_search.to_csv(index=False))

            if extractions:
                df_extractions = pd.DataFrame([dict(row._mapping) for row in extractions])
                zf.writestr('extractions.csv', df_extractions.to_csv(index=False))

            if project_dict.get('synthesis_result'):
                zf.writestr('synthesis_result.json', project_dict['synthesis_result'])

            if project_dict.get('discussion_draft'):
                zf.writestr('discussion_draft.txt', project_dict['discussion_draft'])

            if project_dict.get('knowledge_graph'):
                zf.writestr('knowledge_graph.json', project_dict['knowledge_graph'])

            if project_dict.get('analysis_result'):
                zf.writestr('analysis_result_raw.json', project_dict['analysis_result'])

                try:
                    analysis_data = json.loads(project_dict['analysis_result'])
                    if 'mean_score' in analysis_data:
                        report = f"Rapport de Méta-Analyse\n-----------------------------\nArticles analysés: {analysis_data.get('n_articles', 'N/A')}\nScore moyen: {analysis_data.get('mean_score', 0):.2f}"
                        zf.writestr('meta_analysis_report.txt', report)
                    elif 'atn_scores' in analysis_data:
                        df_atn = pd.DataFrame(analysis_data['atn_scores'])
                        zf.writestr('atn_scores.csv', df_atn.to_csv(index=False))
                except Exception as e:
                    logger.error(f"Erreur formatage export analyse: {e}")

        memory_file.seek(0)
        return Response(
            memory_file.read(),
            mimetype="application/zip",
            headers={"Content-disposition": f"attachment; filename=analylit_export_{project_id}.zip"}
        )

    except Exception as e:
        logger.error(f"Erreur d'export ZIP pour {project_id}: {e}")
        return jsonify({"error": "Erreur interne du serveur lors de l'export."}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/extractions/<extraction_id>', methods=['PATCH'])
def update_extraction(project_id, extraction_id):
    data = request.get_json()
    
    fields = []
    params = {'extraction_id': extraction_id, 'project_id': project_id}
    
    if 'extracted_data' in data:
        fields.append("extracted_data = :extracted_data")
        params['extracted_data'] = json.dumps(data['extracted_data'])
    
    if 'validations' in data:
        fields.append("validations = :validations")
        params['validations'] = json.dumps(data['validations'])
    
    if not fields:
        return jsonify({'error': 'Rien à mettre à jour'}), 400

    session = Session()
    try:
        session.execute(text(f"""
            UPDATE extractions SET {', '.join(fields)} 
            WHERE id = :extraction_id AND project_id = :project_id
        """), params)
        session.commit()

        return jsonify({'message': 'Extraction mise à jour'}), 200

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur mise à jour extraction: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/export-extractions', methods=['GET'])
def export_extractions_csv(project_id):
    session = Session()
    try:
        extractions = session.execute(text("""
            SELECT pmid, title, extracted_data FROM extractions
            WHERE project_id = :project_id AND extracted_data IS NOT NULL
        """), {'project_id': project_id}).fetchall()

        if not extractions:
            return jsonify({"error": "Aucune donnée à exporter."}), 404

        records = []
        for ext in extractions:
            ext_dict = dict(ext._mapping)
            base_record = {
                'pmid': ext_dict['pmid'],
                'title': ext_dict['title']
            }
            
            try:
                if ext_dict['extracted_data']:
                    data = json.loads(ext_dict['extracted_data'])
                    if isinstance(data, dict):
                        base_record.update(data)
            except (json.JSONDecodeError, TypeError):
                pass
            
            records.append(base_record)

        df = pd.DataFrame(records)
        csv = df.to_csv(index=False)

        return Response(csv, mimetype="text/csv",
                       headers={"Content-Disposition": f"attachment; filename=extractions_{project_id}.csv"})

    finally:
        Session.remove()

# Analyse avancée
@api_bp.route('/projects/<project_id>/generate-discussion', methods=['POST'])
def generate_discussion_endpoint(project_id):
    """Lance la génération de la discussion."""
    analysis_queue.enqueue(run_discussion_generation_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Génération de la discussion lancée."}), 202

@api_bp.route('/projects/<project_id>/generate-knowledge-graph', methods=['POST'])
def generate_knowledge_graph_endpoint(project_id):
    """Lance la génération du graphe de connaissances."""
    analysis_queue.enqueue(run_knowledge_graph_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Génération du graphe de connaissances lancée."}), 202

@api_bp.route('/projects/<project_id>/generate-prisma-flow', methods=['POST'])
def generate_prisma_flow_endpoint(project_id):
    """Lance la génération du diagramme PRISMA."""
    analysis_queue.enqueue(run_prisma_flow_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Génération du diagramme PRISMA lancée."}), 202

@api_bp.route('/projects/<project_id>/run-meta-analysis', methods=['POST'])
def run_meta_analysis_endpoint(project_id):
    """Lance la méta-analyse."""
    analysis_queue.enqueue(run_meta_analysis_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Lancement de la méta-analyse."}), 202

@api_bp.route('/projects/<project_id>/run-descriptive-stats', methods=['POST'])
def run_descriptive_stats_endpoint(project_id):
    """Lance l'analyse descriptive."""
    analysis_queue.enqueue(run_descriptive_stats_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Lancement de l'analyse descriptive."}), 202

@api_bp.route('/projects/<project_id>/run-atn-score', methods=['POST'])
def run_atn_score_endpoint(project_id):
    """Lance le calcul du score ATN."""
    analysis_queue.enqueue(run_atn_score_task, project_id=project_id, job_timeout=1800)
    return jsonify({"message": "Lancement du calcul du score ATN."}), 202

# Images et fichiers
@api_bp.route('/projects/<project_id>/analysis-plot', methods=['GET'])
def get_analysis_plot_image(project_id):
    """Récupère l'image d'analyse principale pour un projet."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT analysis_plot_path FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        if not project or not project.analysis_plot_path:
            return jsonify({"error": "Aucun chemin de graphique trouvé pour ce projet."}), 404

        plot_path_data = project.analysis_plot_path
        final_plot_path = None

        try:
            # Cas 1: Le chemin est un JSON contenant plusieurs types de graphiques
            plot_paths = json.loads(plot_path_data)
            if isinstance(plot_paths, dict):
                final_plot_path = next(iter(plot_paths.values()), None)
        except (json.JSONDecodeError, TypeError):
            # Cas 2: Le chemin est une simple chaîne de caractères
            final_plot_path = plot_path_data

        if final_plot_path and os.path.exists(final_plot_path):
            return send_from_directory(os.path.dirname(final_plot_path), os.path.basename(final_plot_path))

        return jsonify({"error": "Fichier image d'analyse introuvable sur le serveur."}), 404

    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/prisma-flow', methods=['GET'])
def get_prisma_flow_image(project_id):
    """Récupère l'image du diagramme PRISMA."""
    session = Session()
    try:
        project = session.execute(text("""
            SELECT prisma_flow_path FROM projects WHERE id = :id
        """), {'id': project_id}).fetchone()

        if project and project.prisma_flow_path and os.path.exists(project.prisma_flow_path):
            return send_from_directory(os.path.dirname(project.prisma_flow_path), os.path.basename(project.prisma_flow_path))

        return jsonify({"error": "Image PRISMA non trouvée."}), 404

    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/files', methods=['GET'])
def list_project_files(project_id):
    """Liste les fichiers PDF trouvés dans le répertoire d'un projet."""
    project_dir = Path(config.PROJECTS_DIR) / project_id
    if not project_dir.is_dir():
        # Retourne une liste vide si le répertoire n'existe pas encore,
        # ce qui est plus propre pour le frontend qu'une erreur 404.
        return jsonify([])
    
    try:
        # Le frontend (app.js) s'attend à une liste d'objets avec une clé "filename".
        files_list = [{'filename': f.name} for f in project_dir.glob('*.pdf')]
        return jsonify(files_list)
    except Exception as e:
        logger.error(f"Erreur lors du listage des fichiers pour le projet {project_id}: {e}")
        return jsonify({"error": "Erreur interne du serveur lors du listage des fichiers."}), 500
        
# Upload de PDF individuel
@api_bp.route('/projects/<project_id>/<article_id>/upload-pdf', methods=['POST'])
def upload_pdf(project_id, article_id):
    """Upload d'un PDF pour un article spécifique."""
    if 'file' not in request.files:
        return jsonify({'error': 'Aucun fichier fourni'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Nom de fichier vide'}), 400

    project_dir = PROJECTS_DIR / project_id
    project_dir.mkdir(exist_ok=True)

    pdf_path = project_dir / f"{article_id}.pdf"
    file.save(str(pdf_path))

    return jsonify({'message': f'PDF pour {article_id} importé avec succès.'}), 200

@api_bp.route('/extractions/<extraction_id>/validate', methods=['POST'])
def validate_extraction(extraction_id):
    """Valide une extraction par l'utilisateur."""
    data = request.get_json()
    user_decision = data.get('decision')  # 'include' or 'exclude'

    if user_decision not in ['include', 'exclude']:
        return jsonify({'error': 'Décision invalide'}), 400

    session = Session()
    try:
        session.execute(text("""
            UPDATE extractions SET validations = :validations WHERE id = :id
        """), {'validations': json.dumps({'evaluator_1': user_decision}), 'id': extraction_id})
        session.commit()

        return jsonify({'message': f'Extraction marquée comme {user_decision}.'}), 200

    except Exception as e:
        session.rollback()
        logger.error(f"Erreur validation extraction: {e}")
        return jsonify({'error': 'Erreur interne du serveur'}), 500
    finally:
        Session.remove()

@api_bp.route('/projects/<project_id>/validation-stats', methods=['GET'])
def get_validation_stats(project_id):
    """Calcule les statistiques de validation pour un projet."""
    session = Session()
    try:
        extractions = session.execute(text("""
            SELECT relevance_score, validations
            FROM extractions
            WHERE project_id = :project_id AND validations IS NOT NULL
        """), {'project_id': project_id}).fetchall()

        if not extractions:
            return jsonify({
                "total_validated": 0,
                "message": "Aucune validation manuelle n'a encore été effectuée pour ce projet."
            }), 200

        validated_rows = []
        for e in extractions:
            try:
                validations_dict = json.loads(e.validations)
                if 'evaluator_1' in validations_dict:
                    validated_rows.append({
                        'relevance_score': e.relevance_score,
                        'user_validation_status': validations_dict['evaluator_1']
                    })
            except (json.JSONDecodeError, TypeError):
                continue

        if not validated_rows:
            return jsonify({
                "total_validated": 0,
                "message": "Aucune validation par l'évaluateur 1 trouvée."
            }), 200

        # Calculer les statistiques (à implémenter selon vos besoins)
        total_validated = len(validated_rows)
        agreed_count = sum(1 for row in validated_rows 
                          if (row['relevance_score'] >= 7 and row['user_validation_status'] == 'include') or 
                             (row['relevance_score'] < 7 and row['user_validation_status'] == 'exclude'))

        agreement_rate = agreed_count / total_validated if total_validated > 0 else 0

        return jsonify({
            "total_validated": total_validated,
            "agreement_rate": agreement_rate,
            "agreed_count": agreed_count
        })

    finally:
        Session.remove()

# WebSocket handlers
@socketio.on('connect')
def handle_connect():
    """Gère la connexion d'un client WebSocket."""
    logger.info(f"Client WebSocket connecté: {request.sid}")

@socketio.on('disconnect')
def handle_disconnect():
    """Gère la déconnexion d'un client WebSocket."""
    logger.info(f"Client WebSocket déconnecté: {request.sid}")

@socketio.on('join_room')
def handle_join_room(data):
    """Gère la demande d'un client de rejoindre une room de projet."""
    # Le frontend doit envoyer un dictionnaire {'room': project_id}
    project_id = data.get('room') if isinstance(data, dict) else data

    if project_id:
        logger.info(f"Client {request.sid} rejoint la room du projet {project_id}")
        join_room(project_id) # C'est LA fonction correcte à appeler
        emit('room_joined', {'project_id': project_id})
    else:
        logger.warning(f"Tentative de rejoindre une room sans project_id par {request.sid}")

@socketio.on('leave_room')
def handle_leave_room(data):
    """Gère la demande d'un client de quitter une room de projet."""
    project_id = data.get('room') if isinstance(data, dict) else data

    if project_id:
        logger.info(f"Client {request.sid} quitte la room du projet {project_id}")
        leave_room(project_id) # C'est LA fonction correcte à appeler

# Enregistrer le blueprint
app.register_blueprint(api_bp)

if __name__ == '__main__':
    # Ne PAS utiliser en production. Gunicorn est utilisé.
    socketio.run(app, debug=True, host='0.0.0.0', port=5001)