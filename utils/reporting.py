# Fichier : utils/reporting.py (CORRIGÉ)

import json
from sqlalchemy import create_engine, text
from config_v4 import get_config

config = get_config()

engine = create_engine(config.DATABASE_URL)

class AdvancedPRISMAFlowExtractor:
    """
    Extraire les données nécessaires pour un diagramme de flux PRISMA avancé en utilisant PostgreSQL.
    """

    def __init__(self, project_id: str):
        self.project_id = project_id
        self.stats = {
            "identification": 0,
            "screening": 0,
            "eligibility": 0,
            "included": 0,
            "duplicates": 0,
            "excluded_screening": 0,
            "excluded_eligibility": 0,
            "reasons_for_exclusion": {}
        }

    def run(self):
        self._calculate_initial_counts()
        self._calculate_exclusion_reasons()
        return self.stats

    def _calculate_initial_counts(self):
        with engine.connect() as conn:
            # Nombre total d'articles identifiés
            total_found_result = conn.execute(
                text("SELECT COUNT(*) FROM search_results WHERE project_id = :pid"),
                {"pid": self.project_id}
            ).scalar_one_or_none() or 0
            self.stats["identification"] = total_found_result
            self.stats["screening"] = total_found_result

            # Nombre d'articles inclus
            included_count_result = conn.execute(
                text("SELECT COUNT(*) FROM extractions WHERE project_id = :pid AND relevance_score &gt;= 7"),
                {"pid": self.project_id}
            ).scalar_one_or_none() or 0
            self.stats["included"] = included_count_result
            self.stats["eligibility"] = included_count_result
            self.stats["excluded_screening"] = total_found_result - included_count_result

    def _calculate_exclusion_reasons(self):
        with engine.connect() as conn:
            excluded_rows = conn.execute(text("""
                SELECT relevance_justification FROM extractions
                WHERE project_id = :pid AND relevance_score &lt; 7
            """), {"pid": self.project_id}).mappings().all()

            reasons = {}
            for row in excluded_rows:
                justification = row['relevance_justification'] or "Raison non spécifiée"
                reasons[justification] = reasons.get(justification, 0) + 1
            
            self.stats["reasons_for_exclusion"] = reasons
