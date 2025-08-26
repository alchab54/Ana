# **AnalyLit V4.1 \- Guide Technique Exhaustif**

Ce document fournit une description technique détaillée de l'architecture, des composants, des flux de données et des fonctions clés de l'application AnalyLit V4.1. Il est destiné aux développeurs souhaitant comprendre, maintenir ou étendre le système.

## **1\. Architecture et Philosophie**

AnalyLit est une application web conteneurisée avec Docker, conçue pour l'analyse de littérature scientifique assistée par IA. Son architecture repose sur plusieurs principes clés :

* **Découplage des Services** : Chaque composant majeur (serveur web, workers, IA, base de données) est un service indépendant, ce qui facilite la maintenance, le scaling et le remplacement de parties spécifiques.  
* **Traitement Asynchrone** : Les tâches longues sont déléguées à des workers en arrière-plan via une file d'attente, garantissant une interface utilisateur toujours réactive.  
* **Persistance des Données** : Les données critiques (projets, PDF, bases de données) sont stockées dans des volumes Docker, les séparant du cycle de vie des conteneurs.  
* **IA Locale d'Abord** : L'intégration avec Ollama permet d'utiliser des modèles de langage puissants en local, assurant la confidentialité des données et l'indépendance vis-à-vis des API cloud.

### **1.1. Composants Détaillés**

* **nginx (Reverse Proxy)** : Point d'entrée unique (localhost:8080).  
  * **Rôle** : Sert les fichiers statiques de l'interface (/web) et agit comme un répartiteur de charge et un point de terminaison sécurisé.  
  * **Configuration (nginx\_complete.conf)** :  
    * location / : Sert le index.html et les autres fichiers statiques. La directive try\_files est essentielle pour une application monopage (SPA), car elle redirige toutes les routes inconnues vers index.html.  
    * location /api/ : Transfère toutes les requêtes API au service web sur son port interne (web:5001).  
    * location /socket.io/ : Gère la connexion WebSocket, en s'assurant que les en-têtes Upgrade et Connection sont correctement transmis pour maintenir la connexion ouverte.  
* **web (Serveur Backend Flask)** : Le cerveau de l'application.  
  * **Rôle** : Gérer la logique métier, les sessions utilisateur (implicites), la communication avec la base de données et l'orchestration des tâches de fond.  
  * **Frameworks** : Utilise **Flask** pour l'API REST, **Flask-SocketIO** pour la communication temps réel, et **Gunicorn** avec des workers gevent pour un serveur de production performant et non bloquant.  
* **worker (Tâches de Fond RQ)** : Les "chevaux de trait" de l'application.  
  * **Rôle** : Exécuter toutes les opérations qui prendraient plus de quelques secondes.  
  * **Framework** : Utilise **Redis Queue (RQ)**, une bibliothèque Python simple et robuste pour la mise en file d'attente de tâches. Les workers écoutent en permanence les nouvelles tâches sur les files Redis.  
* **redis (Broker de Messages & Cache)** : Le système nerveux central.  
  * **Rôle** : Stocker les listes de tâches à effectuer pour les workers et servir de bus de communication pour les notifications WebSocket entre les services.  
* **ollama (Serveur d'IA)** : Le moteur d'intelligence artificielle.  
  * **Rôle** : Charger les modèles de langage (LLM) en mémoire (GPU si disponible) et exposer une API simple pour l'inférence (génération de texte).  
* **projects/ (Volume de Données)** : La mémoire persistante de l'application.  
  * database.db : Base de données **SQLite** unique contenant toutes les métadonnées. Le mode journal\_mode=WAL est activé pour permettre une meilleure concurrence entre les lectures et les écritures.  
  * \<project\_id\>/ : Chaque projet a son propre sous-dossier contenant :  
    * Les fichiers PDF importés.  
    * Les images générées (PRISMA, graphes).  
    * Un dossier chroma\_db/ pour la base de données vectorielle spécifique à ce projet.

## **2\. Schéma de la Base de Données (SQLite)**

La base de données est conçue pour être simple et relationnelle, centrée autour du concept de projet.

* **projects** : Table principale. Chaque ligne représente un projet d'analyse.  
  * id, name, description : Informations de base.  
  * status : État actuel du projet (processing, completed, failed).  
  * analysis\_mode : screening ou full\_extraction.  
  * synthesis\_result, discussion\_draft, etc. : Champs TEXT (JSON) pour stocker les résultats des analyses.  
* **search\_results** : Stocke les métadonnées de tous les articles trouvés ou ajoutés à un projet.  
  * project\_id, article\_id (PMID/DOI), title, abstract, etc.  
* **extractions** : Table la plus importante, stocke les résultats de l'analyse IA pour chaque article.  
  * relevance\_score, relevance\_justification : Pour le mode screening.  
  * extracted\_data : Un champ TEXT contenant le JSON des données extraites en mode full\_extraction.  
  * user\_validation\_status : include ou exclude, défini par l'utilisateur.  
  * **analysis\_source** : Champ crucial qui trace si l'analyse a été faite sur le 'pdf' ou l''abstract'.  
* **extraction\_grids**, **analysis\_profiles**, **prompts** : Tables de configuration pour la personnalisation.  
* **chat\_messages** : Stocke l'historique des conversations pour la fonction de Chat RAG.

## **3\. Dépendances Clés et Leurs Rôles (requirements.txt)**

La stabilité de l'application dépend de versions spécifiques de bibliothèques Python.

* **Serveur Web & Asynchrone** :  
  * Flask, Flask-CORS, Flask-SocketIO : Forment la base du serveur web et de la communication temps réel.  
  * gunicorn, gevent, gevent-websocket : Permettent de faire tourner le serveur Flask de manière performante en production, en gérant de multiples connexions simultanées sans blocage.  
* **Tâches de Fond** :  
  * redis, rq : Le duo qui forme le système de file d'attente. redis est le serveur de messages, rq est la librairie Python qui permet de créer et de gérer les tâches.  
* **IA & NLP** :  
  * sentence-transformers : Utilisée pour créer les embeddings (vecteurs numériques) à partir du texte des PDF. Le modèle all-MiniLM-L6-v2 est choisi pour son excellent rapport performance/taille.  
  * chromadb : La base de données vectorielle qui stocke les embeddings et permet la recherche de similarité sémantique pour le Chat RAG.  
  * langchain : Utilisée spécifiquement pour son RecursiveCharacterTextSplitter, un outil efficace pour découper le texte en chunks sémantiquement cohérents.  
* **API Externes & Traitement de Données** :  
  * requests : Pour tous les appels HTTP externes.  
  * pyzotero : Client Python pour interagir avec l'API Zotero.  
  * PyPDF2 : Librairie pour extraire le texte brut des fichiers PDF.  
  * pandas, numpy, matplotlib : Utilisés pour les analyses statistiques et la génération de graphiques.

## **4\. Description Détaillée des Fonctions Clés**

### **tasks\_v4\_complete.py (Logique Métier)**

Ce fichier est le plus critique car il contient la logique de toutes les tâches asynchrones.

* #### **process\_single\_article\_task(...)**   **C'est la fonction la plus complexe, au cœur du pipeline d'analyse.**

  * **Objectif** : Analyser un seul article en utilisant la meilleure source de texte disponible.  
  * **Flux d'Exécution** :  
    1. Récupère les métadonnées de l'article depuis la table search\_results.  
    2. **Cherche un fichier PDF** correspondant à l'ID de l'article dans le dossier du projet.  
    3. **Si un PDF est trouvé**, son texte est extrait. Si le texte est de longueur suffisante, la variable analysis\_source est définie sur 'pdf'.  
    4. **Sinon (pas de PDF ou PDF illisible)**, la fonction se rabat sur le résumé (abstract) et analysis\_source est défini sur 'abstract'.  
    5. Selon l'analysis\_mode du projet :  
       * **screening** : Construit un prompt demandant un score de pertinence.  
       * **full\_extraction** : Construit un prompt plus complexe incluant la structure JSON de la grille d'extraction (personnalisée ou par défaut).  
    6. Appelle call\_ollama\_api pour obtenir une réponse de l'IA.  
    7. **Sauvegarde le résultat** dans la table extractions, en incluant le score, la justification, les données extraites, et surtout, la valeur de analysis\_source.

* #### **import\_from\_zotero\_file\_task(...)**

  * **Objectif** : Importer des articles et leurs PDF de manière fiable à partir d'un export Zotero.  
  * **Flux d'Exécution** :  
    1. Prend en entrée le contenu d'un fichier CSL JSON.  
    2. **Analyse l'URL id du premier article** pour détecter automatiquement si la collection provient d'une bibliothèque personnelle (/users/...) ou de groupe (/groups/...).  
    3. Initialise la connexion à l'API Zotero avec le bon type et ID de bibliothèque.  
    4. Parcourt chaque article du fichier JSON :  
       * Ajoute les métadonnées de l'article à la table search\_results s'il n'y est pas déjà.  
       * **Extrait la clé d'item Zotero** (ex: M7YXBXKR) de la fin de l'URL id.  
       * Utilise cette clé pour appeler zot.children(key), une méthode API très précise pour lister les fichiers attachés.  
       * Si un PDF est trouvé, il est téléchargé.

* #### **index\_project\_pdfs\_task(...) et answer\_chat\_question\_task(...)**   **Ces deux fonctions forment le système de Retrieval-Augmented Generation (RAG).**

  * **index\_project\_pdfs\_task (L'Indexation)** :  
    1. Utilise PyPDF2 pour extraire le texte brut de tous les PDF du projet.  
    2. Utilise RecursiveCharacterTextSplitter (de LangChain) pour découper intelligemment le texte en morceaux qui se chevauchent (chunks).  
    3. Pour chaque chunk, le modèle SentenceTransformer (all-MiniLM-L6-v2) le transforme en un **vecteur numérique** (embedding) qui représente son sens sémantique.  
    4. Ces vecteurs, ainsi que le texte original et les métadonnées (de quel article vient le chunk), sont stockés dans une base de données vectorielle **ChromaDB**.  
  * **answer\_chat\_question\_task (La Réponse)** :  
    1. La question de l'utilisateur est transformée en vecteur avec le même modèle.  
    2. ChromaDB est interrogé pour trouver les N chunks de texte dont les vecteurs sont les plus "proches" de celui de la question (recherche de similarité cosinus).  
    3. Un **prompt contextuel** est construit, contenant la question de l'utilisateur et les chunks de texte pertinents trouvés.  
    4. Ce prompt est envoyé à un LLM puissant (comme Llama3.1) avec l'instruction de répondre **uniquement** sur la base du contexte fourni.  
    5. La réponse et les sources sont sauvegardées et renvoyées à l'utilisateur.

### **app.js (Logique Frontend)**

* #### **appState**

  * **Rôle** : Agit comme une "source unique de vérité" pour l'état de l'interface. Toute donnée dynamique (projets, résultats, etc.) est stockée ici. Les fonctions de rendu lisent cet état pour dessiner l'interface.

* #### **initializeApplication() et setupEventListeners()**

  * **Rôle** : Mettre en place l'application. initializeApplication est le point d'entrée qui appelle les autres fonctions de chargement. setupEventListeners est crucial car il attache toutes les fonctions de gestion d'événements aux éléments du DOM, en utilisant un système centralisé basé sur l'attribut data-action.

* #### **Fonctions render...()**

  * **Rôle** : Générer le HTML dynamique. Par exemple, renderProjectArticlesList boucle sur la liste des articles dans appState et crée un \<li\> pour chacun, en y ajoutant la logique pour afficher le bouton 📄 ou ➕ selon la présence du PDF.

* #### **Fonctions handle...()**

  * **Rôle** : Contenir la logique métier côté client. Par exemple, handleDeleteSelectedArticles :  
    1. Récupère toutes les cases à cocher sélectionnées.  
    2. Extrait les data-article-id de ces cases.  
    3. Affiche une boîte de dialogue de confirmation.  
    4. Utilise fetchAPI pour envoyer la liste des IDs à supprimer à l'endpoint backend /api/projects/.../delete-articles.  
    5. Après confirmation du backend, appelle selectProject(..., true) pour rafraîchir les données et l'affichage.

## **5\. Liens entre les Fichiers et Logique Applicative**

Pour comprendre comment les différents fichiers collaborent, suivons le parcours d'une action utilisateur typique : **lancer une analyse sur une liste d'articles**.

**Objectif :** L'utilisateur a une liste de PMIDs, il veut que l'IA les analyse en mode "Screening" et voir les résultats.

**Étape 1 : Interaction Utilisateur (Frontend)**

* **Fichiers impliqués :** index.html, app.js  
* **Logique :**  
  1. L'utilisateur navigue vers l'onglet "Import PDF". La fonction renderImportSection() dans app.js génère le HTML nécessaire.  
  2. Il colle sa liste de PMIDs dans le \<textarea id="manualPmidTextarea"\>.  
  3. Il clique sur le bouton "Importer via Zotero (Liste)". Ce bouton a un attribut data-action="import-zotero-list".  
  4. La fonction setupEventListeners() dans app.js intercepte ce clic. Elle trouve l'action import-zotero-list dans son objet actions et exécute la fonction associée : handleImportZotero(projectId).

**Étape 2 : Requête API (Frontend → Nginx → Backend)**

* **Fichiers impliqués :** app.js, nginx\_complete.conf, server\_v4\_complete.py  
* **Logique :**  
  1. handleImportZotero() dans app.js récupère la liste des PMIDs depuis le textarea.  
  2. Elle appelle fetchAPI('/projects/.../import-zotero', { method: 'POST', ... }).  
  3. Le navigateur envoie une requête POST à http://localhost:8080/api/projects/.../import-zotero.  
  4. **Nginx** (nginx\_complete.conf) reçoit la requête. Comme elle correspond à location /api/, il la transfère au service backend défini comme upstream analylit\_backend, c'est-à-dire web:5001.  
  5. Le serveur **Flask** (server\_v4\_complete.py) reçoit la requête sur la route @api\_bp.route('/projects/\<project\_id\>/import-zotero', methods=\['POST'\]).

**Étape 3 : Mise en File de la Tâche (Backend → Redis)**

* **Fichiers impliqués :** server\_v4\_complete.py, tasks\_v4\_complete.py, redis  
* **Logique :**  
  1. La fonction import\_from\_zotero() dans server\_v4\_complete.py récupère les données JSON de la requête.  
  2. Elle appelle la fonction add\_manual\_articles\_to\_project() pour ajouter les métadonnées des nouveaux articles à la base de données.  
  3. Ensuite, elle met en file une tâche pour le worker : background\_queue.enqueue(import\_pdfs\_from\_zotero\_task, ...).  
  4. La librairie RQ sérialise la fonction et ses arguments et les place dans une file d'attente sur le serveur **Redis**.  
  5. Le serveur web renvoie immédiatement une réponse 202 Accepted au frontend, indiquant que la tâche a été acceptée pour traitement.

**Étape 4 : Exécution de la Tâche (Worker)**

* **Fichiers impliqués :** worker (conteneur), tasks\_v4\_complete.py, config\_v4.py, ollama  
* **Logique :**  
  1. Un conteneur worker est en attente de nouvelles tâches sur les files Redis.  
  2. Il récupère la tâche import\_pdfs\_from\_zotero\_task et ses arguments.  
  3. La fonction s'exécute. Elle utilise les variables d'environnement (comme ZOTERO\_API\_KEY) et les paramètres de config\_v4.py.  
  4. Elle se connecte à l'API Zotero, cherche chaque article, et télécharge les PDF trouvés dans le volume projects/.  
  5. Pendant son exécution, la tâche peut appeler send\_project\_notification(...).

**Étape 5 : Notification en Temps Réel (Worker → Redis → Backend → Frontend)**

* **Fichiers impliqués :** tasks\_v4\_complete.py, redis, server\_v4\_complete.py, app.js  
* **Logique :**  
  1. La fonction send\_project\_notification() dans tasks\_v4\_complete.py se connecte à Redis et publie un message sur un canal pub/sub.  
  2. Le serveur web (server\_v4\_complete.py), via Flask-SocketIO, est abonné à ce canal Redis. Il reçoit le message.  
  3. Le serveur web relaie ce message via la connexion WebSocket au client concerné (grâce au système de "room").  
  4. Dans app.js, la fonction initializeWebSocket() a défini un écouteur socket.on('notification', ...) qui reçoit le message.  
  5. La fonction handleWebSocketNotification() est appelée. Elle affiche un "toast" et peut déclencher un rafraîchissement des données en appelant selectProject(..., true).

**Étape 6 : Finalisation et Mise à Jour de l'UI**

* **Fichiers impliqués :** tasks\_v4\_complete.py, app.js, index.html  
* **Logique :**  
  1. À la fin de son exécution, la tâche import\_pdfs\_from\_zotero\_task envoie une notification finale 'zotero\_import\_completed'.  
  2. Le frontend reçoit cette notification et rafraîchit les données du projet.  
  3. selectProject(..., true) est appelé, ce qui refait un fetchAPI pour obtenir les dernières informations du projet.  
  4. Enfin, renderImportSection() et renderProjectArticlesList() sont appelées à nouveau. Elles lisent le appState mis à jour et redessinent l'interface, affichant maintenant l'icône 📄 à côté des articles dont le PDF a été importé avec succès.

Ce cycle complet, du clic à la mise à jour de l'interface, illustre comment les différents composants et fichiers de l'application sont interconnectés pour fournir une expérience utilisateur fluide et asynchrone.

## **6\. Déploiement et Maintenance**

* **Déploiement** : Le déploiement est entièrement géré par docker-compose. La commande docker-compose up \-d \--build suffit à construire les images et lancer tous les services dans le bon ordre.  
* **Mise à jour** : Pour mettre à jour l'application, il suffit de récupérer la dernière version du code (git pull), puis de relancer la commande de déploiement. Docker reconstruira uniquement les images dont les fichiers ont changé.  
* **Sauvegardes** : La partie la plus critique à sauvegarder est le volume projects/. Une simple compression de ce dossier (tar \-czf backup.tar.gz projects/) suffit pour sauvegarder toutes les données des utilisateurs. Les modèles Ollama peuvent être retéléchargés.  
* **Monitoring** : La commande docker-compose logs \-f est l'outil principal pour suivre l'activité de l'application en temps réel. Pour les performances, docker stats donne un aperçu de l'utilisation CPU et RAM de chaque conteneur.

## **7\. Pistes d'Amélioration et Extensibilité**

L'architecture modulaire de l'application permet de nombreuses extensions futures :

* **Ajout de nouvelles bases de données** : Il suffit d'ajouter une nouvelle méthode search\_... dans la classe DatabaseManager de tasks\_v4\_complete.py et de l'appeler dans la tâche multi\_database\_search\_task.  
* **Support de nouveaux types d'analyses** : Une nouvelle carte peut être ajoutée dans renderAnalysisSection() (app.js), liée à un nouvel endpoint dans server\_v4\_complete.py, qui lui-même mettra en file une nouvelle tâche d'analyse dans tasks\_v4\_complete.py.  
* **Authentification multi-utilisateurs** : Le schéma de la base de données peut être étendu avec une table users, et les requêtes peuvent être modifiées pour filtrer les projets par user\_id.  
* **Modèles d'IA Cloud** : La fonction call\_ollama\_api pourrait être étendue pour appeler, en alternative, des API comme GPT-4 ou Claude, en se basant sur la configuration du profil d'analyse.