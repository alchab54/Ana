# Fichier : utils/analysis.py

import json
import pandas as pd
from typing import List, Dict, Any, Callable

def generate_discussion_draft(df: pd.DataFrame, call_ollama_func: Callable, model: str) -> str:
    """
    Génère un brouillon de la section 'Discussion' pour une revue systématique.
    """
    required_cols = ['extracted_data'] # On se base sur le JSON brut
    if not all(col in df.columns for col in required_cols):
        return "Erreur: La colonne 'extracted_data' est requise."

    excerpts = []
    for _, row in df.head(15).iterrows():
        try:
            data = json.loads(row.get('extracted_data', '{}'))
            conclusion = data.get('conclusions', {}).get('main_conclusions', 'Non spécifiée')
            limitations = data.get('limitations', {}).get('study_limitations', 'Non spécifiées')
            excerpts.append(f"Étude (PMID: {row.get('pmid', 'N/A')}):\n- Conclusion: {conclusion}\n- Limitations: {limitations}")
        except (json.JSONDecodeError, AttributeError):
            continue

    if not excerpts:
        return "Aucune donnée de conclusion ou de limitation exploitable trouvée dans les extractions."

    prompt = f"""
    En tant qu'assistant de recherche expert, rédigez une synthèse narrative concise (environ 150-200 mots) destinée à la section "Discussion" d'une revue systématique. Votre analyse doit se baser sur les extraits d'études suivants.
    Votre synthèse doit impérativement :
    1. Identifier les points de convergence majeurs (les résultats qui se répètent ou se complètent).
    2. Souligner les divergences ou les contradictions notables entre les études.
    3. Suggérer brièvement une ou deux directions pertinentes pour la recherche future, en se basant sur les limitations identifiées.
    Extraits des études à analyser :
    ---
    {''.join(excerpts)}
    ---
    Brouillon de la section Discussion :
    """
    return call_ollama_func(prompt, model)

def generate_knowledge_graph_data(df: pd.DataFrame, call_ollama_func: Callable, model: str) -> Dict[str, List[Dict]]:
    """
    Génère les données (nœuds et arêtes) pour un graphe de connaissances.
    """
    nodes = [{"id": str(row.get('pmid')), "title": row.get('title')} for i, row in df.iterrows()]
    
    study_summaries = "\n".join([f"ID: {node['id']}, Titre: {node['title']}" for node in nodes])

    prompt = f"""
    Analysez la liste d'articles suivante et identifiez jusqu'à 5 relations significatives entre eux. Les types de relations peuvent être, par exemple, "Méthodologie Similaire", "Population Similaire", "Thème Commun", "Auteur Commun", "Résultats Contradictoires".
    Retournez UNIQUEMENT un objet JSON valide contenant une seule clé "relations". La valeur de cette clé doit être une liste d'objets. Chaque objet doit avoir trois clés : "source" (ID de l'article source), "target" (ID de l'article cible), et "type" (une courte description de la relation).
    Articles à analyser :
    ---
    {study_summaries}
    ---
    JSON des relations :
    """
    
    response_json = call_ollama_func(prompt, model, output_format="json")
    
    try:
        # response_json est déjà un dict grâce à `output_format="json"`
        edges = response_json.get("relations", [])
        node_ids = {node['id'] for node in nodes}
        edges = [edge for edge in edges if edge.get('source') in node_ids and edge.get('target') in node_ids]
    except (AttributeError, TypeError): # Si response_json n'est pas un dict
        print("Avertissement: La réponse du LLM pour le graphe n'était pas un JSON valide.")
        edges = []

    return {"nodes": nodes, "edges": edges}

def analyze_themes(abstracts: List[str], call_ollama_func: Callable, model: str) -> List[str]:
    """
    Identifie les thèmes récurrents à partir d'une liste d'abstracts.
    """
    if not abstracts:
        return []
    
    combined_abstracts = "\n\n".join(abstracts)
    prompt = f"""
    Analysez le corpus de résumés scientifiques suivant et identifiez les 5 à 7 thèmes de recherche les plus récurrents et significatifs. Ne fournissez aucune explication, juste une liste numérotée des thèmes.
    Corpus :
    {combined_abstracts}
    Thèmes récurrents :
    """
    
    response = call_ollama_func(prompt, model)
    themes = [line.split('.', 1)[1].strip() for line in response.split('\n') if '.' in line]
    return themes

    
