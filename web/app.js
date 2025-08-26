// ================================================================
// AnalyLit V4.1 - Application Frontend CORRIGÉE
// ================================================================

const appState = {
    currentProject: null,
    projects: [],
    searchResults: [],
    analysisProfiles: [],
    ollamaModels: [],
    prompts: [],
    currentProjectGrids: [],
    currentProjectExtractions: [],
    socketConnected: false,
    currentSection: 'projects',
    socket: null,
    availableDatabases: [],
    notifications: [],
    unreadNotifications: 0,
    selectedSearchResults: new Set()
};

let elements = {};

document.addEventListener('DOMContentLoaded', () => {
    console.log('🚀 Démarrage de AnalyLit V4.1 Frontend CORRIGÉ...');
    elements = {
        sections: document.querySelectorAll('.section'),
        navButtons: document.querySelectorAll('.app-nav__button'),
        connectionStatus: document.querySelector('[data-connection-status]'),
        projectsList: document.getElementById('projectsList'),
        createProjectBtn: document.getElementById('createProjectBtn'),
        projectDetail: document.getElementById('projectDetail'),
        projectDetailContent: document.getElementById('projectDetailContent'),
        projectPlaceholder: document.getElementById('projectPlaceholder'),
        searchResults: document.getElementById('searchResults'),
        resultsContainer: document.getElementById('resultsContainer'),
        validationContainer: document.getElementById('validationContainer'),
        analysisContainer: document.getElementById('analysisContainer'),
        importContainer: document.getElementById('importContainer'),
        chatContainer: document.getElementById('chatContainer'),
        settingsContainer: document.getElementById('settingsContainer'),
        newProjectForm: document.getElementById('newProjectForm'),
        multiSearchForm: document.getElementById('multiSearchForm'),
        runPipelineForm: document.getElementById('runPipelineForm'),
        gridForm: document.getElementById('gridForm'),
        promptForm: document.getElementById('promptForm'),
        profileForm: document.getElementById('profileForm'),
        loadingOverlay: document.getElementById('loadingOverlay'),
        toastContainer: document.getElementById('toastContainer'),
        zoteroImportForm: document.getElementById('zoteroImportForm'),

    };

    setupEventListeners();
    initializeApplication();
});

async function initializeApplication() {
    showLoadingOverlay(true, 'Initialisation...');
    try {
        initializeWebSocket();
        await loadInitialData();
        showSection('projects');
        console.log('✅ Application initialisée avec succès');
    } catch (error) {
        console.error('❌ Erreur initialisation application:', error);
        showToast("Erreur lors de l'initialisation", 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

function setupEventListeners() {
    // Navigation
    elements.navButtons.forEach(button => button.addEventListener('click', (e) => {
        e.preventDefault();
        showSection(e.currentTarget.getAttribute('data-section'));
    }));

    // Formulaires
    elements.createProjectBtn?.addEventListener('click', () => openModal('newProjectModal'));
    elements.newProjectForm?.addEventListener('submit', handleCreateProject);
    elements.zoteroImportForm?.addEventListener('submit', handleZoteroFileUpload);
    elements.multiSearchForm?.addEventListener('submit', handleMultiSearch);
    elements.runPipelineForm?.addEventListener('submit', handleRunPipeline);
    elements.gridForm?.addEventListener('submit', handleSaveGrid);
    elements.promptForm?.addEventListener('submit', handleSavePrompt);
    elements.profileForm?.addEventListener('submit', handleSaveProfile);

    const gridFileInput = document.getElementById('gridFileInput');
    if (gridFileInput) {
        gridFileInput.addEventListener('change', handleGridImport);
    }
	
	const zoteroFileInput = document.getElementById('zoteroFileInput');
    if (zoteroFileInput) {
        zoteroFileInput.addEventListener('change', handleZoteroFileUpload);
    }

    document.getElementById('addGridFieldBtn')?.addEventListener('click', () => addGridFieldInput());
    document.getElementById('pipelineSourceSelect')?.addEventListener('change', handlePipelineSourceChange);

    document.body.addEventListener('click', e => {
        const target = e.target.closest('[data-action]');
        if (!target) return;

        const action = target.dataset.action;
        const { projectId, articleId, gridId, promptId, profileId, queueName, plotType, extractionId, decision } = target.dataset;

        if (action === 'view-article-online') {
            e.preventDefault();
            const url = target.href;
            if (url && url !== '#' && !url.endsWith('null')) {
                window.open(url, '_blank');
            } else {
                showToast("URL de l'article non disponible.", 'warning');
            }
            return;
        }

        const actions = {
			selectProject: () => selectProject(projectId),
			deleteProject: () => handleDeleteProject(projectId),
			runPipeline: () => openRunPipelineModal(),
			runSynthesis: () => handleRunSynthesis(),
			exportProject: () => handleExportProject(projectId),
			selectSearchResult: () => selectSearchResult(articleId),
			selectAllSearchResults: () => selectAllSearchResults(),
			// MODIFIÉ: Passe l'ID de l'évaluateur (ici, 'evaluator_1' pour l'utilisateur principal)
			validateExtraction: () => handleValidateExtraction(extractionId, decision, 'evaluator_1'),
			toggleAbstract: () => {
				const row = target.closest('tr');
				const next = row?.nextElementSibling;
				if (next && next.classList.contains('abstract-row')) {
					next.classList.toggle('hidden');
				}
			},
			viewExtractionDetails: () => openExtractionDetailModal(extractionId),
			'generate-discussion': () => runAdvancedAnalysis('generate-discussion', projectId),
			'generate-knowledge-graph': () => runAdvancedAnalysis('generate-knowledge-graph', projectId),
			'generate-prisma-flow': () => runAdvancedAnalysis('generate-prisma-flow', projectId),
			'run-meta-analysis': () => runAdvancedAnalysis('run-meta-analysis', projectId),
			'run-descriptive-stats': () => runAdvancedAnalysis('run-descriptive-stats', projectId),
			'run-atn-score': () => runAdvancedAnalysis('run-atn-score', projectId),
			viewAnalysisPlot: () => viewAnalysisPlot(projectId, plotType),
			'import-zotero-file': () => document.getElementById('zoteroFileInput')?.click(),
			'import-zotero-list': () => handleImportZotero(projectId),
			'fetch-online-pdfs': () => handleFetchOnlinePdfs(projectId),
			'run-indexing': () => handleRunIndexing(projectId),
			sendChatMessage: () => sendChatMessage(),
			clearChatHistory: () => clearChatHistory(),
			'create-grid': () => openGridModal(),
			'edit-grid': () => openGridModal(gridId),
			'delete-grid': () => handleDeleteGrid(gridId),
			'import-grid': () => document.getElementById('gridFileInput')?.click(),
			removeGridField: () => target.closest('.form-group-dynamic')?.remove(),
			'edit-prompt': () => openPromptModal(promptId),
			'create-profile': () => openProfileModal(),
			'edit-profile': () => openProfileModal(profileId),
			'delete-profile': () => handleDeleteProfile(profileId),
			pullModel: () => handlePullModel(),
			'refresh-queues': () => renderQueueStatus(),
			clearQueue: () => handleClearQueue(queueName),
			saveZoteroSettings: () => handleSaveZoteroSettings(),
			'delete-selected-articles': () => handleDeleteSelectedArticles(),
			
			// AJOUT: Nouvelles actions
			'import-validations': () => document.getElementById('validationFileInput')?.click(),
			'export-validations': () => handleExportValidations(projectId),
			'calculate-kappa': () => handleCalculateKappa(projectId),
			'generate-gdpr-report': () => handleGenerateReport(projectId, 'gdpr'),
			'generate-ai-act-report': () => handleGenerateReport(projectId, 'ai-act'),
			'run-publication-bias': () => runAdvancedAnalysis('run-publication-bias', projectId),

			'upload-single-pdf': () => {
				const fileInput = document.createElement('input');
				fileInput.type = 'file';
				fileInput.accept = '.pdf';
				fileInput.style.display = 'none';
				fileInput.addEventListener('change', (e) => {
					handleManualPDFUpload(target.dataset.articleId, e.target.files[0]);
				});
				document.body.appendChild(fileInput);
				fileInput.click();
				fileInput.remove();
			},
		};

        if (actions[action]) {
            e.preventDefault();
            actions[action]();
        }
    });

    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const activeModal = document.querySelector('.modal--show');
            if (activeModal) closeModal(activeModal.id);
        }
    });

    document.querySelectorAll('.modal').forEach(modal => {
        modal.addEventListener('click', (e) => {
            if (e.target === modal) closeModal(modal.id);
        });
        modal.querySelector('.modal__close')?.addEventListener('click', () => closeModal(modal.id));
    });
} 

async function loadInitialData() {
    await Promise.all([
        loadProjects(),
        loadAnalysisProfiles(),
        loadOllamaModels(),
        loadPrompts(),
        loadAvailableDatabases()
    ]);
}

// ================================================================
// ===== 2. FONCTIONS UTILITAIRES & WEBSOCKET
// ================================================================

async function fetchAPI(endpoint, options = {}) {
    const url = `/api${endpoint}`;
    const headers = options.body instanceof FormData ? {} : { 'Content-Type': 'application/json', ...options.headers };
    const config = { ...options, headers,  cache: 'no-cache' };

    if (options.body && !(options.body instanceof FormData)) {
        config.body = JSON.stringify(options.body);
    }

    try {
        const response = await fetch(url, config);
        if (!response.ok) {
            const data = await response.json().catch(() => ({ error: `Erreur HTTP ${response.status}` }));
            throw new Error(data.error || `Erreur ${response.status}`);
        }
        if (response.status === 204 || response.headers.get('Content-Length') === '0') return null;
        const contentType = response.headers.get("content-type");
        if (contentType && contentType.indexOf("application/json") !== -1) {
            return await response.json();
        } else {
            return await response.text();
        }
    } catch (error) {
        console.error(`Erreur API pour ${endpoint}:`, error);
        showToast(error.message, 'error');
        throw error;
    }
}

function initializeWebSocket() {
    try {
        appState.socket = io({ path: '/socket.io/' });

        appState.socket.on('connect', () => {
            console.log('✅ WebSocket connecté');
            appState.socketConnected = true;
            elements.connectionStatus.textContent = '✅';
            if (appState.currentProject) {
                appState.socket.emit('join_room', { room: appState.currentProject.id });
            }
        });

        appState.socket.on('disconnect', () => {
            console.warn('🔌 WebSocket déconnecté.');
            appState.socketConnected = false;
            elements.connectionStatus.textContent = '❌';
        });

        appState.socket.on('connect_error', (err) => {
            console.error('❌ Erreur de connexion WebSocket:', err.message);
            appState.socketConnected = false;
            elements.connectionStatus.textContent = '❌';
        });

        appState.socket.on('notification', (data) => {
            console.log('📢 Notification reçue:', data);
            handleWebSocketNotification(data);
        });

        appState.socket.on('room_joined', (data) => {
            console.log(`🏠 Rejoint la room du projet ${data.project_id}`);
        });

    } catch (e) {
        console.error("Socket.IO non disponible.", e);
        elements.connectionStatus.textContent = '❌';
    }
}

function handleWebSocketNotification(data) {
    showToast(data.message, data.type || 'info');
    appState.unreadNotifications++;
    updateNotificationIndicator();

    const { type, project_id } = data;

    // Logique de rafraîchissement unifiée et fiable
    switch (type) {
        case 'search_completed':
        case 'article_processed': // C'est le cas qui nous intéresse
        case 'synthesis_completed':
        case 'analysis_completed':
        case 'pdf_upload_completed':
        case 'indexing_completed':
            // Si la notification concerne le projet actuellement ouvert, on le rafraîchit entièrement.
            if (project_id === appState.currentProject?.id) {
                selectProject(project_id, true); // Le 'true' indique un rafraîchissement
            } else {
                // Sinon, on met simplement à jour la liste des projets sur le côté.
                loadProjects();
            }
            break;
    }
}

async function handleExportValidations(projectId) {
    showLoadingOverlay(true, 'Exportation...');
    try {
        const response = await fetchAPI(`/projects/${projectId}/export-validations`);
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.style.display = 'none';
        a.href = url;
        a.download = `validations_${projectId}.csv`;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        showToast('Exportation réussie.', 'success');
    } catch (error) {
        showToast('Erreur lors de l\'exportation.', 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleImportValidations(file) {
    if (!appState.currentProject || !file) return;
    showLoadingOverlay(true, 'Importation...');
    const formData = new FormData();
    formData.append('file', file);
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/import-validations`, {
            method: 'POST',
            body: formData,
        });
        showToast('Importation réussie. Rafraîchissement des données...', 'success');
        selectProject(appState.currentProject.id, true);
    } catch (error) {
        showToast('Erreur lors de l\'importation.', 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleCalculateKappa(projectId) {
    showLoadingOverlay(true, 'Calcul en cours...');
    try {
        await fetchAPI(`/projects/${projectId}/inter-rater-reliability`, { method: 'POST' });
        showToast('Le calcul du score Kappa a été lancé.', 'info');
    } catch (error) {
         showToast('Erreur lors du lancement du calcul.', 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleGenerateReport(projectId, reportType) {
    showLoadingOverlay(true, `Génération du rapport ${reportType.toUpperCase()}...`);
    try {
        await fetchAPI(`/projects/${projectId}/report/${reportType}`, { method: 'POST' });
        showToast(`La génération du rapport ${reportType.toUpperCase()} a été lancée.`, 'info');
    } catch (error) {
        showToast('Erreur lors de la génération du rapport.', 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

function updateNotificationIndicator() {
    const indicator = document.getElementById('notificationIndicator');
    if (!indicator) return;
    if (appState.unreadNotifications > 0) {
        indicator.style.display = 'flex';
        indicator.querySelector('.notification-indicator__count').textContent = appState.unreadNotifications;
    } else {
        indicator.style.display = 'none';
    }
}

function escapeHtml(text) {
    if (text === null || typeof text === 'undefined') return '';
    const map = { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' };
    return String(text).replace(/[&<>"']/g, (m) => map[m]);
}

function showToast(message, type = 'info') {
    if (!elements.toastContainer) return;
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };
    
    toast.innerHTML = `
        <div class="toast__icon">${icons[type] || 'ℹ️'}</div>
        <div class="toast__message">${escapeHtml(message)}</div>
        <button class="toast__close" onclick="this.parentElement.remove()">×</button>
    `;
    
    elements.toastContainer.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

function showLoadingOverlay(show, message = 'Chargement...') {
    if (!elements.loadingOverlay) return;
    const messageElement = document.getElementById('loadingMessage');
    if (messageElement) messageElement.textContent = message;
    elements.loadingOverlay.classList.toggle('loading-overlay--show', show);
}

function openModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.add('modal--show');
}

function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) modal.classList.remove('modal--show');
}

// ================================================================
// ===== 3. NAVIGATION ET AFFICHAGE DES SECTIONS
// ================================================================

function showSection(sectionName) {
    appState.currentSection = sectionName;
    appState.unreadNotifications = 0;
    updateNotificationIndicator();
    
    elements.sections.forEach(section => {
        section.classList.toggle('section--active', section.id === `${sectionName}Section`);
    });

    elements.navButtons.forEach(button => {
        button.classList.toggle('app-nav__button--active', button.dataset.section === sectionName);
    });

    refreshCurrentSection();
}

function refreshCurrentSection() {
    const renderMap = {
        projects: () => { renderProjectsList(); renderProjectDetail(); },
        search: renderSearchInterface,
        results: renderResultsSection,
        validation: renderValidationSection,
        analysis: renderAnalysisSection,
        import: renderImportSection,
        chat: renderChatSection,
        settings: renderSettingsSection,
    };
    if (renderMap[appState.currentSection]) {
        renderMap[appState.currentSection]();
    }
}

// ================================================================
// ===== 4. GESTION DES PROJETS
// ================================================================

async function loadProjects() {
    try {
        appState.projects = await fetchAPI('/projects');
    } catch (error) {
        appState.projects = [];
    }
    renderProjectsList();
}

function renderProjectsList() {
    const container = elements.projectsList;
    if (!container) return;

    if (!appState.projects || appState.projects.length === 0) {
        container.innerHTML = `<div class="projects-empty"><p>Créez votre premier projet.</p></div>`;
        return;
    }

    container.innerHTML = appState.projects.map(project => {
        const isActive = appState.currentProject?.id === project.id;
        return `
            <li class="project-list__item ${isActive ? 'project-list__item--active' : ''}" data-action="selectProject" data-project-id="${project.id}">
                <div class="project-list__item-info">
                    <span class="project-list__item-name">${escapeHtml(project.name)}</span>
                    <div class="project-meta">
                        <span class="status ${getStatusClass(project.status)}">${escapeHtml(project.status || 'pending')}</span>
                        <span class="project-list__item-date">${new Date(project.updated_at).toLocaleDateString()}</span>
                    </div>
                </div>
                <button class="btn btn--danger btn--sm" data-action="deleteProject" data-project-id="${project.id}" title="Supprimer" onclick="event.stopPropagation()">&times;</button>
            </li>`;
    }).join('');
}

async function selectProject(projectId, isRefresh = false) {
    if (!isRefresh && appState.currentProject?.id === projectId) return;
    if (!isRefresh) showLoadingOverlay(true, 'Chargement du projet...');

    try {
        appState.currentProject = await fetchAPI(`/projects/${projectId}`);
        
        if (appState.socket?.connected) {
            appState.socket.emit('join_room', { room: projectId });
        }
        
        await Promise.all([
            loadProjectExtractions(projectId),
            loadProjectGrids(projectId),
            loadSearchResults(projectId)
        ]);
        
        refreshCurrentSection();
    } catch (error) {
        console.error(`Erreur sélection projet ${projectId}:`, error);
        appState.currentProject = null;
        refreshCurrentSection();
    } finally {
        if (!isRefresh) showLoadingOverlay(false);
    }
}

function renderProjectDetail() {
    const project = appState.currentProject;
    if (!project) {
        elements.projectPlaceholder.style.display = 'flex';
        elements.projectDetailContent.style.display = 'none';
        return;
    }
	
    if (project.prisma_flow_path) {
        const prismaButtonHtml = `
            <div class="mt-16">
                <a href="${escapeHtml(project.prisma_flow_path)}" target="_blank" class="btn btn--secondary">
                    🖼️ Voir le diagramme PRISMA
                </a>
            </div>
        `;
        // Ajouter ce HTML au conteneur de détail du projet
        projectDetailContent.querySelector('.analysis-section').innerHTML += prismaButtonHtml;
    }

    elements.projectPlaceholder.style.display = 'none';
    elements.projectDetailContent.style.display = 'block';

    const progress = project.pmids_count > 0 ? (project.processed_count / project.pmids_count) * 100 : 0;
    
    let resultsHtml = '';
    if (project.synthesis_result) {
        resultsHtml += renderSynthesisPreview(JSON.parse(project.synthesis_result));
    }
    if (project.discussion_draft) {
        resultsHtml += `
            <div class="result-preview" style="margin-top:20px;">
                <h4>📝 Discussion Générée</h4>
                <p class="result-text">${escapeHtml(project.discussion_draft).replace(/\n/g, '<br>')}</p>
            </div>`;
    }

    if (project.analysis_result) {
        try {
            const analysisData = JSON.parse(project.analysis_result);
            
            // Si c'est une méta-analyse
            if (analysisData.mean_score !== undefined && analysisData.confidence_interval) {
                resultsHtml += `
                    <div class="result-preview" style="margin-top:20px;">
                        <h4>📈 Méta-Analyse</h4>
                        <p>Articles analysés: <strong>${analysisData.n_articles}</strong></p>
                        <p>Score moyen de pertinence: <strong>${analysisData.mean_score.toFixed(2)}</strong> (IC 95%: [${analysisData.confidence_interval[0].toFixed(2)}, ${analysisData.confidence_interval[1].toFixed(2)}])</p>
                    </div>`;
            }
            // Si c'est un calcul de score ATN
            else if (analysisData.atn_scores !== undefined) {
                 resultsHtml += `
                    <div class="result-preview" style="margin-top:20px;">
                        <h4>💯 Score ATN</h4>
                        <p>Articles évalués: <strong>${analysisData.total_articles_scored}</strong></p>
                        <p>Score ATN moyen: <strong>${analysisData.mean_atn.toFixed(2)}</strong></p>
                    </div>`;
            }
            // Si ce sont des statistiques descriptives
            else if (analysisData.total_articles !== undefined) {
                 resultsHtml += `
                    <div class="result-preview" style="margin-top:20px;">
                        <h4>📋 Statistiques Descriptives</h4>
                        <p>Total d'articles avec données extraites: <strong>${analysisData.total_articles}</strong></p>
                    </div>`;
            }

        } catch(e) { console.error("Erreur parsing analysis_result", e); }
    }

    elements.projectDetailContent.innerHTML = `
        <div class="project-detail-header">
            <h3>${escapeHtml(project.name)}</h3>
            <div class="project-badges">
                <span class="status status--info">${escapeHtml(project.analysis_mode)}</span>
                <span class="status ${getStatusClass(project.status)}">${escapeHtml(project.status || 'pending')}</span>
            </div>
        </div>
        <p class="project-detail-description">${escapeHtml(project.description) || 'Aucune description.'}</p>
        <div class="project-detail-stats">
            <div class="stat"><div class="stat__value">${project.pmids_count || 0}</div><div class="stat__label">Articles Total</div></div>
            <div class="stat"><div class="stat__value">${project.processed_count || 0}</div><div class="stat__label">Traités</div></div>
            <div class="stat"><div class="stat__value">${(project.total_processing_time || 0).toFixed(1)}s</div><div class="stat__label">Temps Total</div></div>
        </div>
        <div class="progress-bar">
            <div class="progress-bar__inner" style="width: ${progress}%"></div>
            <span class="progress-bar__label">${escapeHtml(project.status || 'pending')} (${progress.toFixed(0)}%)</span>
        </div>
        <div class="project-detail-actions">
            <button class="btn btn--primary" data-action="runPipeline">🚀 Lancer Analyse</button>
            ${(project.status === 'completed' || project.processed_count > 0) ? `<button class="btn btn--secondary" data-action="runSynthesis">🔄 Générer Synthèse</button>` : ''}
            <button class="btn btn--secondary" data-action="exportProject" data-project-id="${project.id}">📤 Exporter</button>
            <button class="btn btn--danger btn--outline" data-action="deleteProject" data-project-id="${project.id}">🗑️ Supprimer</button>
        </div>
        <div class="project-results-container" style="margin-top:20px;">
            ${resultsHtml || ''}
        </div>`;
}

function getStatusClass(status) {
    const statusMapping = {
        pending: 'status--info', processing: 'status--warning',
        completed: 'status--success', failed: 'status--error'
    };
    return statusMapping[status] || 'status--info';
}

function renderSynthesisPreview(synthesis) {
    const renderList = (items) => {
        if (!Array.isArray(items) || items.length === 0) return '<li>Aucun élément identifié.</li>';
        return items.map(point => `<li>${escapeHtml(point)}</li>`).join('');
    };

    return `
        <div class="result-preview">
            <h4>📋 Synthèse Générée</h4>
            <div class="synthesis-content">
                <div class="synthesis-section">
                    <strong>Évaluation de la pertinence du corpus :</strong>
                    <p>${escapeHtml(synthesis.relevance_evaluation || 'Non évaluée.')}</p>
                </div>
                <div class="synthesis-section">
                    <strong>Thèmes principaux :</strong>
                    <ul>${renderList(synthesis.main_themes)}</ul>
                </div>
                <div class="synthesis-section">
                    <strong>Synthèse globale :</strong>
                    <p>${escapeHtml(synthesis.synthesis_summary || synthesis.synthese_globale || 'Non disponible.')}</p>
                </div>
            </div>
        </div>`;
}

async function handleCreateProject(e) {
    e.preventDefault();
    const formData = new FormData(e.target);
    const projectData = { name: formData.get('projectName'), description: formData.get('description'), mode: formData.get('analysisMode') };
    if (!projectData.name) { showToast("Le nom du projet est requis.", 'error'); return; }
    showLoadingOverlay(true, 'Création du projet...');
    try {
        const newProject = await fetchAPI('/projects', { method: 'POST', body: projectData });
        closeModal('newProjectModal');
        e.target.reset();
        await loadProjects();
        await selectProject(newProject.id);
        showToast('Projet créé avec succès!', 'success');
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleDeleteProject(projectId) {
    const project = appState.projects.find(p => p.id === projectId);
    if (!project || !confirm(`Supprimer le projet "${project.name}" ?`)) return;

    showLoadingOverlay(true, 'Suppression...');
    try {
        await fetchAPI(`/projects/${projectId}`, { method: 'DELETE' });
        showToast('Projet supprimé.', 'success');
        if (appState.currentProject?.id === projectId) appState.currentProject = null;
        await loadProjects();
        refreshCurrentSection();
    } finally {
        showLoadingOverlay(false);
    }
}

// ================================================================
// ===== 5. GESTION DE LA RECHERCHE MULTI-BASES
// ================================================================

async function loadAvailableDatabases() {
    try {
        appState.availableDatabases = await fetchAPI('/databases');
        renderDatabaseSelection();
    } catch (error) {
        appState.availableDatabases = [
            { id: 'pubmed', name: 'PubMed', enabled: true },
            { id: 'arxiv', name: 'arXiv', enabled: true },
            { id: 'crossref', name: 'CrossRef', enabled: true }
        ];
        renderDatabaseSelection();
    }
}

function renderDatabaseSelection() {
    const container = document.getElementById('databaseSelection');
    if (!container) return;
    
    container.innerHTML = appState.availableDatabases.map(db => `
        <label class="checkbox-item">
            <input type="checkbox" name="databases" value="${db.id}" ${db.enabled ? 'checked' : ''}>
            <span>${escapeHtml(db.name)}</span>
        </label>
    `).join('');
}

function renderSearchInterface() {
    // L'interface est déjà dans le HTML, on met juste à jour les éléments dynamiques
    renderDatabaseSelection();
    renderSearchResults();
}

async function handleMultiSearch(e) {
  e.preventDefault();
  if (!appState.currentProject) return;
  const form = elements.multiSearchForm;
  const query = form.querySelector('input[name="query"]').value;
  const databases = Array.from(form.querySelectorAll('input[name="databases"]:checked')).map(cb => cb.value);

  showLoadingOverlay(true, 'Recherche en cours...');
  try {
    // Lancer la recherche
    await fetchAPI('/search', {
      method: 'POST',
      body: { project_id: appState.currentProject.id, query, databases }
    });

    // Polling ou attendre notification WebSocket, mais on fait un fetch immédiat
    const resultsResponse = await fetchAPI(
      `/projects/${appState.currentProject.id}/search-results`
    );
    appState.searchResults = resultsResponse.results;
    renderResultsSection();
  } catch (err) {
    console.error('Erreur lors de la recherche :', err);
    showToast(err.message, 'error');
  } finally {
    showLoadingOverlay(false);
  }
}

async function loadSearchResults(projectId) {
    try {
        const data = await fetchAPI(`/projects/${projectId}/search-results`);
        appState.searchResults = data.results;
        renderSearchResults();
    } catch (error) {
        appState.searchResults = [];
        renderSearchResults();
    }
}

function renderSearchResults() {
    const container = elements.searchResults;
    if (!container) return;
    if (!appState.searchResults || appState.searchResults.length === 0) {
        container.innerHTML = `<div class="results-placeholder"><h4>Aucun résultat</h4><p>Lancez une recherche pour voir les résultats ici.</p></div>`;
        return;
    }
    const groupedResults = appState.searchResults.reduce((acc, result) => {
        (acc[result.database_source] = acc[result.database_source] || []).push(result);
        return acc;
    }, {});
    container.innerHTML = `
        <div class="search-results-header">
            <h3>Résultats (${appState.searchResults.length} articles)</h3>
            <div class="search-actions">
                <button class="btn btn--secondary btn--sm" data-action="selectAllSearchResults">Tout sélectionner / désélectionner</button>
            </div>
        </div>
        ${Object.entries(groupedResults).map(([database, results]) => `
            <div class="database-results-section">
                <h4>${escapeHtml(database)} (${results.length})</h4>
                <div class="search-results-grid">${results.map(renderSearchResultCard).join('')}</div>
            </div>
        `).join('')}`;
}

function renderSearchResultCard(result) {
    const isSelected = appState.selectedSearchResults?.has(result.article_id);
    
    return `
        <div class="search-result-card ${isSelected ? 'search-result-card--selected' : ''}" 
             data-action="selectSearchResult" 
             data-article-id="${result.article_id}"
             data-database="${result.database_source}">
            <div class="search-result-card__header">
                <h5 class="search-result-card__title">${escapeHtml(result.title)}</h5>
                <div class="search-result-card__meta">
                    <span class="database-badge">${escapeHtml(result.database_source)}</span>
                    ${result.publication_date ? `<span class="date-badge">${result.publication_date}</span>` : ''}
                </div>
            </div>
            <div class="search-result-card__content">
                ${result.authors ? `<p class="authors">${escapeHtml(result.authors)}</p>` : ''}
                ${result.journal ? `<p class="journal"><em>${escapeHtml(result.journal)}</em></p>` : ''}
                ${result.abstract ? `<p class="abstract">${escapeHtml(result.abstract.slice(0, 200))}${result.abstract.length > 200 ? '...' : ''}</p>` : ''}
            </div>
            <div class="search-result-card__actions">
                ${result.url ? `<a href="${result.url}" target="_blank" class="btn btn--outline btn--sm">Voir l'article</a>` : ''}
                <div class="selection-indicator">
                    ${isSelected ? '✅ Sélectionné' : 'Cliquer pour sélectionner'}
                </div>
            </div>
        </div>
    `;
}

function selectSearchResult(articleId, database) {
    if (!appState.selectedSearchResults) {
        appState.selectedSearchResults = new Set();
    }
    
    const key = `${articleId}-${database}`;
    if (appState.selectedSearchResults.has(key)) {
        appState.selectedSearchResults.delete(key);
    } else {
        appState.selectedSearchResults.add(key);
    }
    
    renderSearchResults();
}

function selectAllSearchResults() {
    if (!appState.selectedSearchResults) {
        appState.selectedSearchResults = new Set();
    }
    
    const allSelected = appState.searchResults.every(result => 
        appState.selectedSearchResults.has(`${result.article_id}-${result.database_source}`)
    );
    
    if (allSelected) {
        // Tout désélectionner
        appState.selectedSearchResults.clear();
    } else {
        // Tout sélectionner
        appState.searchResults.forEach(result => {
            appState.selectedSearchResults.add(`${result.article_id}-${result.database_source}`);
        });
    }
    
    renderSearchResults();
}

async function addSelectedToProject() {
    if (!appState.selectedSearchResults || appState.selectedSearchResults.size === 0) {
        showToast('Aucun article sélectionné.', 'warning');
        return;
    }
    
    if (!appState.currentProject) {
        showToast('Aucun projet sélectionné.', 'error');
        return;
    }
    
    const selectedIds = Array.from(appState.selectedSearchResults).map(key => key.split('-')[0]);
    
    showLoadingOverlay(true, 'Ajout des articles au projet...');
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/add-articles`, {
            method: 'POST',
            body: { article_ids: selectedIds }
        });
        
        showToast(`${selectedIds.length} articles ajoutés au projet.`, 'success');
        appState.selectedSearchResults.clear();
        await selectProject(appState.currentProject.id, true);
        
    } catch (error) {
        console.error('Erreur ajout articles:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function updateSearchProgress(data) {
    // Mettre à jour la progression en temps réel si nécessaire
    const { database, count } = data;
    console.log(`Progression recherche ${database}: ${count} résultats`);
}

// ================================================================
// ===== 6. GESTION DU PIPELINE ET DES ANALYSES
// ================================================================

function openRunPipelineModal() {
    if (!appState.currentProject) {
        showToast("Sélectionnez d'abord un projet.", 'error');
        return;
    }
    
    // Ouvre la modale vide en premier
    openModal('runPipelineModal');
    // Ensuite, remplit son contenu
    renderRunPipelineModal();
}

// Fonction qui remplit la modale "Lancer une analyse"
function renderRunPipelineModal() {
    const project = appState.currentProject;
    if (!project) return;

    // --- CORRECTION DE L'ERREUR ---
    // Sélection des éléments qui existent déjà dans index.html
    const profileSelect = document.getElementById('pipelineProfileSelect');
    const gridContainer = document.getElementById('pipelineGridContainer');
    const gridSelect = document.getElementById('pipelineGridSelect');
    const sourceSelect = document.getElementById('pipelineSourceSelect');
    
    // Vérification que les éléments existent avant de les manipuler
    if (!profileSelect || !gridContainer || !gridSelect || !sourceSelect) {
        console.error("Éléments de la modale d'analyse non trouvés !");
        return;
    }
    
    // Remplissage du sélecteur de profils
    profileSelect.innerHTML = appState.analysisProfiles.map(profile => 
        `<option value="${profile.id}">${escapeHtml(profile.name)}</option>`
    ).join('');
    profileSelect.value = project.profile_used || 'standard';

    // Affichage du sélecteur de grille uniquement en mode "extraction détaillée"
    if (project.analysis_mode === 'full_extraction') {
        gridContainer.style.display = 'block';
        gridSelect.innerHTML = '<option value="">Grille par défaut</option>' + 
            appState.currentProjectGrids.map(grid => 
                `<option value="${grid.id}">${escapeHtml(grid.name)}</option>`
            ).join('');
    } else {
        gridContainer.style.display = 'none';
    }
    
    // Assurer que le champ de saisie manuelle est correctement affiché ou masqué
    handlePipelineSourceChange();
}

function handlePipelineSourceChange() {
    const sourceSelect = document.getElementById('pipelineSourceSelect');
    const manualGroup = document.getElementById('manualIdsGroup');
    
    if (sourceSelect && manualGroup) {
        manualGroup.style.display = sourceSelect.value === 'manual' ? 'block' : 'none';
    }
}

async function handleRunPipeline(e) {
    e.preventDefault();
    
    if (!appState.currentProject) {
        showToast('Aucun projet sélectionné.', 'error');
        return;
    }

    const formData = new FormData(e.target);
    const source = formData.get('pipelineSourceSelect');
    const profileId = formData.get('pipelineProfileSelect');
    const customGridId = formData.get('pipelineGridSelect');
    
    let articleIds = [];
    
    if (source === 'manual') {
        const manualIds = formData.get('pmidsTextarea');
        if (!manualIds) {
            showToast('Veuillez fournir des IDs d\'articles.', 'error');
            return;
        }
        articleIds = manualIds.split('\n').map(id => id.trim()).filter(Boolean);
    } else {
        // En mode "résultats de recherche", on récupère les IDs sélectionnés
        articleIds = Array.from(appState.selectedSearchResults);
    }
    
    if (articleIds.length === 0) {
        showToast('Aucun article à traiter. Veuillez en sélectionner ou en saisir manuellement.', 'error');
        return;
    }

    closeModal('runPipelineModal');
    showLoadingOverlay(true, 'Lancement du pipeline...');
    
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/run`, {
            method: 'POST',
            body: {
                articles: articleIds,
                profile: profileId,
                custom_grid_id: customGridId || null
            }
        });
        
        showToast(`Analyse lancée pour ${articleIds.length} article(s).`, 'info');
        await selectProject(appState.currentProject.id, true);
        
    } catch (error) {
        console.error('Erreur lancement pipeline:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function handleAnalysisModeChange() {
    const project = appState.currentProject;
    const gridContainer = document.getElementById('pipelineGridContainer');
    const gridSelect = document.querySelector('.grid-select');

    if (project && gridContainer && gridSelect) {
        if (project.analysis_mode === 'full_extraction') {
            gridContainer.style.display = 'block';
            gridSelect.innerHTML = '<option value="">Grille par défaut</option>' + 
                appState.currentProjectGrids.map(grid => 
                    `<option value="${grid.id}">${escapeHtml(grid.name)}</option>`
                ).join('');
        } else {
            gridContainer.style.display = 'none';
        }
    }
}

async function handleRunSynthesis() {
    if (!appState.currentProject) return;
    
    const profile = appState.currentProject.profile_used || 'standard';
    
    showLoadingOverlay(true, 'Lancement de la synthèse...');
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/run-synthesis`, {
            method: 'POST',
            body: { profile }
        });
        
        showToast("La synthèse a été lancée.", "info");
        await selectProject(appState.currentProject.id, true);
        
    } catch (error) {
        console.error('Erreur synthèse:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleExportProject(projectId) {
  showToast("Préparation de l'export complet...", "info");
  try {
    const response = await fetch(`/api/projects/${projectId}/export-all`, {
      method: "GET"
    });

    if (!response.ok) {
      const errorData = await response.json();
      throw new Error(errorData.error || `Erreur HTTP ${response.status}`);
    }

    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    
    const disposition = response.headers.get("Content-Disposition") || "";
    const filenameMatch = disposition.match(/filename="?(.+)"?/);
    a.download = filenameMatch ? filenameMatch[1] : `project_export_${projectId}.zip`;
    
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
    showToast("Export ZIP terminé.", "success");

  } catch (error) {
    console.error("Erreur export :", error);
    showToast(`Erreur lors de l'export du ZIP: ${error.message}`, "error");
  }
}

// ================================================================
// ===== 7. AUTRES SECTIONS (RÉSULTATS, VALIDATION, ANALYSES...)
// ================================================================

async function loadProjectExtractions(projectId) {
    try {
        appState.currentProjectExtractions = await fetchAPI(`/projects/${projectId}/extractions`);
    } catch (e) {
        appState.currentProjectExtractions = [];
    }
}

async function loadProjectGrids(projectId) {
    try {
        appState.currentProjectGrids = await fetchAPI(`/projects/${projectId}/grids`);
    } catch (e) {
        appState.currentProjectGrids = [];
    }
}

function renderResultsSection() {
    const container = elements.resultsContainer;
    const project = appState.currentProject;

    if (!project) {
        container.innerHTML = `
            <div class="results-placeholder">
                <span class="results-placeholder__icon">📊</span>
                <h4>Sélectionnez un projet</h4>
                <p>Les résultats des analyses s'afficheront ici.</p>
            </div>`;
        return;
    }

    const extractions = appState.currentProjectExtractions;
    if (!extractions || extractions.length === 0) {
        container.innerHTML = `
            <div class="results-placeholder">
                <span class="results-placeholder__icon">📋</span>
                <h4>Aucun résultat d'analyse</h4>
                <p>Lancez une analyse pour générer des résultats à afficher ici.</p>
            </div>`;
        return;
    }

    const isScreening = project.analysis_mode === 'screening';
    
    // CORRECTION : Affichage des extractions au lieu des résultats de recherche
    container.innerHTML = `
        <div class="results-header">
            <h2>Résultats d'analyse pour : ${escapeHtml(project.name)}</h2>
            <div class="results-stats">
                <span class="status status--info">📊 ${extractions.length} articles traités</span>
                <span class="status status--success">✅ ${extractions.filter(e => e.relevance_score >= 7).length} articles pertinents</span>
            </div>
        </div>
        
        <div class="table-container">
            <table class="table">
                <thead>
                    <tr>
                        ${isScreening ? 
                            `<th>Score</th><th>ID</th><th>Titre</th><th>Justification</th><th>Actions</th>` :
                            `<th>ID</th><th>Titre</th><th>Données Extraites</th><th>Actions</th>`
                        }
                    </tr>
                </thead>
                <tbody>
                    ${extractions.map(ext => renderExtractionRow(ext, isScreening)).join('')}
                </tbody>
            </table>
        </div>
    `;
}
	
// Affiche une ligne dans le tableau des résultats (corrigé pour l'extraction détaillée)
function renderExtractionRow(extraction, isScreening) {
    const validationStatus = extraction.user_validation_status;
    let rowClass = '';
    if (validationStatus === 'include') rowClass = 'extraction-row--included';
    if (validationStatus === 'exclude') rowClass = 'extraction-row--excluded';

    // DÉCLARATION CORRIGÉE : 'sourceBadge' est maintenant défini au début.
    const sourceBadge = `<span class="status-badge source--${extraction.analysis_source}">${escapeHtml(extraction.analysis_source)}</span>`;

    const articleUrl = extraction.url || `https://pubmed.ncbi.nlm.nih.gov/${extraction.pmid}/`;
    const titleHtml = `
    <td class="title-cell">
        <a href="${articleUrl}" data-action="view-article-online" target="_blank" title="Voir source">🔗</a>
        <span class="title-text" data-action="toggleAbstract">${escapeHtml(extraction.title || '')}</span>
        ${sourceBadge}
    </td>`;
    
    let dataCellHtml = '';
    if (isScreening) {
        dataCellHtml = `<td class="justification-cell">${escapeHtml(extraction.relevance_justification || 'N/A')}</td>`;
    } else {
        dataCellHtml = `<td>${renderExtractedDataPreview(extraction.extracted_data)}</td>`;
    }

    const mainRowHtml = `
        <tr class="extraction-row ${rowClass}" data-pmid="${extraction.pmid}">
            ${isScreening ? `<td><span class="score-badge">${extraction.relevance_score ?? 'N/A'}</span></td>` : ''}
            <td>${escapeHtml(extraction.pmid)}</td>
            ${titleHtml} 
            ${dataCellHtml}
            <td class="actions-cell">
                <button class="btn btn--secondary btn--sm" data-action="viewExtractionDetails" data-extraction-id="${extraction.id}">Détails</button>
                <button class="btn btn--success btn--sm" data-action="validateExtraction" data-extraction-id="${extraction.id}" data-decision="include">Inclure</button>
                <button class="btn btn--danger btn--sm" data-action="validateExtraction" data-extraction-id="${extraction.id}" data-decision="exclude">Exclure</button>
            </td>
        </tr>`;

    const colspan = isScreening ? 5 : 4;
    const abstractRowHtml = (extraction.abstract) ? `
        <tr class="abstract-row hidden">
            <td colspan="${colspan}">
                <div class="abstract-content">
                    <strong>Abstract:</strong>
                    <p>${escapeHtml(extraction.abstract)}</p>
                </div>
            </td>
        </tr>
    ` : '';

    return mainRowHtml + abstractRowHtml;
}


function renderExtractedDataPreview(extractedData) {
    if (!extractedData) return '<span class="text-muted">Aucune donnée</span>';
    
    try {
        const data = typeof extractedData === 'string' ? JSON.parse(extractedData) : extractedData;

        // Fonction pour "aplatir" les objets imbriqués (ex: { "a": { "b": 1 } } devient { "a.b": 1 })
        const flattenObject = (obj, parentKey = '') => 
            Object.keys(obj).reduce((acc, key) => {
                const newKey = parentKey ? `${parentKey} / ${key}` : key;
                if (typeof obj[key] === 'object' && obj[key] !== null && !Array.isArray(obj[key])) {
                    Object.assign(acc, flattenObject(obj[key], newKey));
                } else {
                    acc[newKey] = obj[key];
                }
                return acc;
            }, {});
        
        const flatData = flattenObject(data);

        const preview = Object.entries(flatData)
            .filter(([, value]) => value && value.toString().trim())
            .slice(0, 4) // Affiche jusqu'à 4 champs
            .map(([key, value]) => {
                const displayValue = value.toString();
                return `<strong>${escapeHtml(key.replace(/_/g, ' '))}:</strong> ${escapeHtml(displayValue.slice(0, 70))}${displayValue.length > 70 ? '...' : ''}`;
            })
            .join('<br>');

        return `<div class="extraction-preview-list">${preview || '<span class="text-muted">Données vides</span>'}</div>`;
    } catch (error) {
        return '<span class="text-muted">Données invalides</span>';
    }
}


async function openExtractionDetailModal(extractionId) {
    const modal = document.getElementById('extractionDetailModal');
    const container = document.getElementById('extractionModalBody');
    if (!modal || !container) {
        console.error("La modale d'extraction ou son conteneur n'a pas été trouvé.");
        return;
    }

    const ext = appState.currentProjectExtractions.find(e => e.id === extractionId);
    if (!ext) {
        container.innerHTML = '<p>Détails non trouvés.</p>';
        openModal('extractionDetailModal');
        return;
    }

    container.innerHTML = formatExtractionDetailsForModal(ext);
    openModal('extractionDetailModal');
}

// Nouvelle fonction pour formater joliment les détails dans la modale
function formatExtractionDetailsForModal(extraction) {
    let html = `
        <div class="extraction-details">
            <h4>${escapeHtml(extraction.title || 'Titre non disponible')}</h4>
            <div class="extraction-meta">
                <p><strong>ID Article:</strong> ${escapeHtml(extraction.pmid || 'N/A')}</p>
                ${extraction.relevance_score ? `<p><strong>Score Pertinence:</strong> ${extraction.relevance_score}/10</p>` : ''}
                ${extraction.relevance_justification ? `<p><strong>Justification:</strong> ${escapeHtml(extraction.relevance_justification)}</p>` : ''}
            </div>
    `;

    if (extraction.extracted_data) {
        try {
            const data = typeof extraction.extracted_data === 'string' ? 
                JSON.parse(extraction.extracted_data) : extraction.extracted_data;
            
            html += '<div class="extraction-data"><h5>Données extraites :</h5><ul class="extraction-details-list">';
            
            // Fonction récursive pour afficher joliment les objets imbriqués
            const createList = (obj) => {
                let listHtml = '<ul>';
                for (const [key, value] of Object.entries(obj)) {
                    const cleanKey = escapeHtml(key.replace(/_/g, ' '));
                    if (value && typeof value === 'object') {
                        listHtml += `<li><strong>${cleanKey}:</strong>${createList(value)}</li>`;
                    } else if (value) {
                        listHtml += `<li><strong>${cleanKey}:</strong><p>${escapeHtml(value)}</p></li>`;
                    }
                }
                listHtml += '</ul>';
                return listHtml;
            };

            html += createList(data) + '</ul></div>';
        } catch (error) {
            html += '<p>Erreur lors de l\'affichage des données extraites.</p>';
        }
    }

    html += '</div>';
    return html;
}

async function handleGridImport(event) {
    const file = event.target.files[0];
    if (!file) return;

    if (!file.name.endsWith('.json')) {
        showToast('Veuillez sélectionner un fichier JSON', 'error');
        return;
    }

    if (!appState.currentProject) {
        showToast('Veuillez sélectionner un projet avant d\'importer une grille', 'error');
        return;
    }

    showLoadingOverlay(true, 'Import de la grille en cours...');

    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`/api/projects/${appState.currentProject.id}/grids/import`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'Erreur lors de l\'import');
        }

        const result = await response.json();
        showToast('Grille importée avec succès !', 'success');
        
        // Recharger les grilles du projet
        await loadProjectGrids(appState.currentProject.id);
        renderSettingsSection();
        
        // Réinitialiser le champ de fichier
        event.target.value = '';
        
    } catch (error) {
        console.error('Erreur lors de l\'import de grille:', error);
        showToast(`Erreur d'import : ${error.message}`, 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

async function renderValidationSection() {
    const container = elements.validationContainer;
    const project = appState.currentProject;
    if (!container || !project) return;

    // Charger les stats et le score kappa
    const [stats, projectDetails] = await Promise.all([
        fetchAPI(`/projects/${project.id}/validation-stats`).catch(() => null),
        fetchAPI(`/projects/${project.id}`).catch(() => null)
    ]);
    
    const kappaScore = projectDetails?.inter_rater_reliability || "Non calculé";

    let statsHtml = `<h4>Statistiques de Validation (IA vs Évaluateur 1)</h4>`;
    if (stats && stats.total_validated > 0) {
        statsHtml += `
            <div class="metrics-grid">
                <div class="metric-card">
                    <h5>Validés</h5>
                    <div class="metric-value">${stats.total_validated}</div>
                </div>
                <div class="metric-card">
                    <h5>Précision IA</h5>
                    <div class="metric-value">${stats.metrics.precision}</div>
                </div>
                <div class="metric-card">
                    <h5>Rappel IA</h5>
                    <div class="metric-value">${stats.metrics.recall}</div>
                </div>
                <div class="metric-card">
                    <h5>Score F1 IA</h5>
                    <div class="metric-value">${stats.metrics.f1_score}</div>
                </div>
            </div>
             <div class="metric-card">
                <h5>Kappa de Cohen</h5>
                <div class="metric-value">${kappaScore}</div>
            </div>
        `;
    } else {
        statsHtml += '<p>Pas assez de données pour les statistiques.</p>';
    }

    const actionsHtml = `
        <div class="project-actions-header">
            <h4>Actions de Double Codage</h4>
            <div class="actions">
                <input type="file" id="validationFileInput" style="display:none;" accept=".csv,.json">
                <button class="btn btn--secondary" data-action="import-validations">Importer (Éval. 2)</button>
                <button class="btn btn--secondary" data-action="export-validations" data-project-id="${project.id}">Exporter (Éval. 1)</button>
                <button class="btn btn--primary" data-action="calculate-kappa" data-project-id="${project.id}">Calculer Kappa</button>
            </div>
        </div>
    `;

    if (!appState.currentProjectExtractions || appState.currentProjectExtractions.length === 0) {
        container.innerHTML = `
            ${statsHtml}
            ${actionsHtml}
            <p>Aucune extraction disponible pour ce projet.</p>
        `;
        return;
    }
    
    const tableHeader = `
        <div class="table-container">
            <table class="results-table">
                <thead>
                    <tr>
                        <th>Titre</th>
                        <th>Score IA</th>
                        <th>Décision IA</th>
                        <th>Éval. 1</th>
                        <th>Éval. 2</th>
                        <th>Actions (Éval. 1)</th>
                    </tr>
                </thead>
                <tbody>
    `;

    const tableRows = appState.currentProjectExtractions.map(ext => {
        const included = ext.relevance_score >= 7;
        const validations = ext.validations ? JSON.parse(ext.validations) : {};
        const decision1 = validations.evaluator_1 || 'N/A';
        const decision2 = validations.evaluator_2 || 'N/A';
        const isDisagreement = decision1 !== 'N/A' && decision2 !== 'N/A' && decision1 !== decision2;

        return `
            <tr class="${isDisagreement ? 'extraction-row--excluded' : ''}">
                <td>${escapeHtml(ext.title)}</td>
                <td>${ext.relevance_score.toFixed(2)}</td>
                <td>${included ? 'Inclure' : 'Exclure'}</td>
                <td>${decision1}</td>
                <td>${decision2}</td>
                <td class="actions-cell">
                    <button class="btn btn--success btn--small" data-action="validateExtraction" data-extraction-id="${ext.id}" data-decision="include">Inclure</button>
                    <button class="btn btn--danger btn--small" data-action="validateExtraction" data-extraction-id="${ext.id}" data-decision="exclude">Exclure</button>
                </td>
            </tr>
        `;
    }).join('');

    const tableFooter = `</tbody></table></div>`;
    container.innerHTML = statsHtml + actionsHtml + tableHeader + tableRows + tableFooter;
    
    // Attacher l'événement au champ de fichier
    document.getElementById('validationFileInput')?.addEventListener('change', (e) => {
        if (e.target.files.length > 0) {
            handleImportValidations(e.target.files[0]);
        }
    });
}

async function handleUpdateDecision(extractionId, decision) {
  await fetchAPI(`/projects/${appState.currentProject.id}/extractions/${extractionId}`, {
    method: 'PATCH',
    body: { user_validation_status: decision }
  });
  renderValidationSection();
}

function calculateAndRenderMetrics(exts) {
  const tp = exts.filter(e => e.relevance_score>=7 && e.user_validation_status==='include').length;
  const fp = exts.filter(e => e.relevance_score>=7 && e.user_validation_status==='exclude').length;
  const fn = exts.filter(e => e.relevance_score<7 && e.user_validation_status==='include').length;
  const tn = exts.filter(e => e.relevance_score<7 && e.user_validation_status==='exclude').length;
  const precision = tp/(tp+fp) || 0;
  const recall = tp/(tp+fn) || 0;
  const f1 = 2*precision*recall/(precision+recall) || 0;
  document.getElementById('metrics').innerHTML = `
    <div>Precision: ${precision.toFixed(2)}</div>
    <div>Recall: ${recall.toFixed(2)}</div>
    <div>F1: ${f1.toFixed(2)}</div>`;
}

document.body.addEventListener('click', e => {
  const t = e.target.closest('[data-action="updateDecision"]');
  if (t) {
    handleUpdateDecision(t.dataset.extractionId, t.dataset.decision);
  }
});

async function renderAnalysisSection() {
    const container = elements.analysisContainer;
    const project = appState.currentProject;

    if (!container || !project) {
        container.innerHTML = `<p>Veuillez sélectionner un projet.</p>`;
        return;
    }

    const analyses = [
        { id: 'descriptive-stats', name: 'Statistiques Descriptives', description: 'Statistiques sur les scores et sources.', action: 'run-descriptive-stats' },
        { id: 'meta-analysis', name: 'Méta-Analyse (Forest Plot)', description: 'Génère un Forest Plot des effets.', action: 'run-meta-analysis' },
        { id: 'publication-bias', name: 'Biais de Publication (Funnel Plot)', description: 'Génère un Funnel Plot pour détecter les biais.', action: 'run-publication-bias' },
        { id: 'atn-score', name: 'Score ATN', description: 'Calcule le score ATN moyen du corpus.', action: 'run-atn-score' },
        { id: 'prisma-flow', name: 'Diagramme PRISMA', description: 'Génère le diagramme de flux PRISMA.', action: 'generate-prisma-flow' },
        { id: 'knowledge-graph', name: 'Graphe de Connaissances', description: 'Visualise les relations entre concepts.', action: 'generate-knowledge-graph' },
        { id: 'discussion', name: 'Discussion Synthétique', description: 'Génère une ébauche de discussion.', action: 'generate-discussion' },
        { id: 'compliance', name: 'Rapports de Conformité', description: 'Génère des rapports RGPD et AI Act.', multiAction: true }
    ];

    // Récupérer les chemins des graphiques
    let plotPaths = {};
    if (project.analysis_plot_path) {
        try {
            plotPaths = JSON.parse(project.analysis_plot_path);
        } catch (e) {
            // Ancien format (chaîne simple)
            plotPaths = { 'descriptive-stats': project.analysis_plot_path };
        }
    }
    
    const analysisCardsHtml = analyses.map(analysis => {
        let resultHtml = '';
        let plotPath = plotPaths[analysis.id];

        if (analysis.id === 'prisma-flow') plotPath = project.prisma_flow_path;

        if (plotPath) {
            resultHtml = `<img src="${plotPath}?t=${new Date().getTime()}" alt="${analysis.name}" class="analysis-plot">`;
        }

        const actionButton = analysis.multiAction
            ? `
                <div class="import-actions">
                  <button class="btn btn--secondary" data-action="generate-gdpr-report" data-project-id="${project.id}">Rapport RGPD</button>
                  <button class="btn btn--secondary" data-action="generate-ai-act-report" data-project-id="${project.id}">Rapport AI Act</button>
                </div>`
            : `<button class="btn btn--primary" data-action="${analysis.action}" data-project-id="${project.id}">Lancer</button>`;

        return `
            <div class="import-card">
                <h4>${analysis.name}</h4>
                <p>${analysis.description}</p>
                ${resultHtml || ''}
                <div class="import-actions">
                  ${!resultHtml ? actionButton : ''}
                </div>
            </div>
        `;
    }).join('');

    container.innerHTML = `
        <h3>Analyses Avancées pour "${escapeHtml(project.name)}"</h3>
        <div class="import-sections">
            ${analysisCardsHtml}
        </div>
    `;
}

async function runAdvancedAnalysis(analysisType, projectId) {
    showLoadingOverlay(true, "Lancement de l'analyse...");
    try {
        await fetchAPI(`/projects/${projectId}/${analysisType}`, { method: 'POST' });
        showToast("Analyse avancée lancée.", 'info');
        await selectProject(projectId, true);
    } catch (error) {
        console.error('Erreur analyse avancée:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function formatExtractionDetailsForAlert(extraction) {
    let text = `Titre: ${extraction.title || 'N/A'}\n`;
    text += `PMID: ${extraction.pmid || 'N/A'}\n`;
    text += `Score: ${extraction.relevance_score || 'N/A'}/10\n`;
    text += `Justification: ${extraction.relevance_justification || 'N/A'}\n`;
    
    if (extraction.extracted_data) {
        try {
            const data = typeof extraction.extracted_data === 'string' ? 
                JSON.parse(extraction.extracted_data) : extraction.extracted_data;
            text += '\nDonnées extraites:\n';
            for (const [key, value] of Object.entries(data)) {
                if (value && value.toString().trim()) {
                    text += `${key}: ${value}\n`;
                }
            }
        } catch (error) {
            text += '\nErreur lors de l\'affichage des données extraites';
        }
    }
    
    return text;
}

// ================================================================
// ===== 8. GESTION DES PARAMÈTRES
// ================================================================

async function loadAnalysisProfiles() {
    try {
        appState.analysisProfiles = await fetchAPI('/analysis-profiles');
    } catch (e) {
        appState.analysisProfiles = [];
    }
}

async function loadOllamaModels() {
    try {
        appState.ollamaModels = await fetchAPI('/ollama/models');
    } catch (e) {
        appState.ollamaModels = [];
    }
}

async function loadPrompts() {
    try {
        appState.prompts = await fetchAPI('/prompts');
    } catch (e) {
        appState.prompts = [];
    }
}

function renderSettingsSection() {
    const container = elements.settingsContainer;
    
    const cards = [
        renderZoteroCard(),
        renderPromptsCard(),
        renderProfilesCard(),
        renderModelsCard(),
        renderQueuesCard()
    ];
    
    // Ajouter la carte des grilles si un projet est sélectionné
    if (appState.currentProject) {
        cards.push(renderGridsCard());
    }
    
    container.innerHTML = cards.join('');
    
	const gridFileInput = document.getElementById('gridFileInput');
    if (gridFileInput) {
        // On s'assure qu'il n'y a qu'un seul écouteur actif à la fois.
        gridFileInput.removeEventListener('change', handleGridImport);
        gridFileInput.addEventListener('change', handleGridImport);
    }
	
    // Charger le statut des files après le rendu
    loadQueueStatus().then(renderQueueStatus);
}

function renderZoteroCard() {
    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>📚 Configuration Zotero</h4>
            </div>
            <div class="settings-card__content">
                <p>Connectez votre compte Zotero pour importer automatiquement les PDF.</p>
                <form id="zoteroForm">
                    <div class="form-group">
                        <label for="zoteroUserId" class="form-label">ID Utilisateur Zotero</label>
                        <input type="text" id="zoteroUserId" class="form-control" required>
                    </div>
                    <div class="form-group">
                        <label for="zoteroApiKey" class="form-label">Clé API Zotero</label>
                        <input type="password" id="zoteroApiKey" class="form-control" required>
                    </div>
                    <button type="submit" class="btn btn--primary btn--full-width" data-action="saveZoteroSettings">
                        Sauvegarder
                    </button>
                </form>
            </div>
        </div>
    `;
}

function renderPromptsCard() {
    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>📝 Gestion des Prompts</h4>
            </div>
            <div class="settings-card__content">
                <p>Modifiez les templates de prompts utilisés par l'IA.</p>
                <div class="prompts-list">
                    ${appState.prompts.map(prompt => `
                        <div class="prompt-item">
                            <div class="prompt-item__info">
                                <h5>${escapeHtml(prompt.name)}</h5>
                                <p>${escapeHtml(prompt.description)}</p>
                            </div>
                            <button class="btn btn--secondary btn--sm" 
                                    data-action="edit-prompt" 
                                    data-prompt-id="${prompt.id}">
                                Modifier
                            </button>
                        </div>
                    `).join('') || '<p>Aucun prompt trouvé.</p>'}
                </div>
            </div>
        </div>
    `;
}

function renderProfilesCard() {
    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>🎯 Profils d'Analyse</h4>
                <button class="btn btn--primary btn--sm" data-action="create-profile">
                    Créer un profil
                </button>
            </div>
            <div class="settings-card__content">
                <p>Gérez les ensembles de modèles IA pour chaque type d'analyse.</p>
                <div class="profiles-grid">
                    ${appState.analysisProfiles.map(profile => `
                        <div class="profile-card">
                            <div class="profile-card__header">
                                <h5>${escapeHtml(profile.name)}</h5>
                                ${!profile.is_custom ? '<span class="badge">Défaut</span>' : ''}
                            </div>
                            <div class="profile-models">
                                <div class="model-assignment">
                                    <span class="model-label">Pré-sélection:</span>
                                    <span class="model-value">${escapeHtml(profile.preprocess_model)}</span>
                                </div>
                                <div class="model-assignment">
                                    <span class="model-label">Extraction:</span>
                                    <span class="model-value">${escapeHtml(profile.extract_model)}</span>
                                </div>
                                <div class="model-assignment">
                                    <span class="model-label">Synthèse:</span>
                                    <span class="model-value">${escapeHtml(profile.synthesis_model)}</span>
                                </div>
                            </div>
                            <div class="profile-actions">
                                <button class="btn btn--secondary btn--sm" 
                                        data-action="edit-profile" 
                                        data-profile-id="${profile.id}">
                                    Modifier
                                </button>
                                ${profile.is_custom ? `
                                    <button class="btn btn--danger btn--sm" 
                                            data-action="delete-profile" 
                                            data-profile-id="${profile.id}">
                                        Supprimer
                                    </button>
                                ` : ''}
                            </div>
                        </div>
                    `).join('') || '<p>Aucun profil trouvé.</p>'}
                </div>
            </div>
        </div>
    `;
}

function renderModelsCard() {
    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>🧠 Modèles Ollama</h4>
            </div>
            <div class="settings-card__content">
                <p>Gérez les modèles IA installés localement.</p>
                <div class="models-list">
                    ${appState.ollamaModels.map(model => `
                        <div class="model-item">
                            <span class="model-name">${escapeHtml(model.name)}</span>
                            <span class="model-size">${(model.size / 1e9).toFixed(2)} GB</span>
                        </div>
                    `).join('') || '<p>Aucun modèle local trouvé.</p>'}
                </div>
                <div class="form-group-inline mt-16">
                    <input type="text" id="pullModelName" class="form-control" 
                           placeholder="ex: llama3.1:8b">
                    <button class="btn btn--primary" data-action="pullModel">
                        Télécharger
                    </button>
                </div>
            </div>
        </div>
    `;
}

function renderQueuesCard() {
    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>⚡ Files d'attente RQ</h4>
                <button class="btn btn--secondary btn--sm" data-action="refresh-queues">
                    🔄 Actualiser
                </button>
            </div>
            <div class="settings-card__content">
                <div id="queueStatusContainer">
                    <p>Chargement du statut des files...</p>
                </div>
            </div>
        </div>
    `;
}

function renderGridsCard() {
    const project = appState.currentProject;
    if (!project) return '';

    return `
        <div class="settings-card">
            <div class="settings-card__header">
                <h4>📋 Grilles d'Extraction</h4>
                <button class="btn btn--primary btn--sm" data-action="create-grid">
                    Créer une grille
                </button>
            </div>
            <div class="settings-card__content">
                <p>Gérez les grilles personnalisées pour le projet <strong>${escapeHtml(project.name)}</strong>.</p>
                <div class="grids-list">
                    ${appState.currentProjectGrids.map(grid => `
                        <div class="grid-item">
                            <div class="grid-item__info">
                                <h5>${escapeHtml(grid.name)}</h5>
                                <p>${grid.fields.length} champs</p>
                            </div>
                            <div class="grid-item__actions">
                                <button class="btn btn--secondary btn--sm" 
                                        data-action="edit-grid" 
                                        data-grid-id="${grid.id}">
                                    Modifier
                                </button>
                                <button class="btn btn--danger btn--sm" 
                                        data-action="delete-grid" 
                                        data-grid-id="${grid.id}">
                                    Supprimer
                                </button>
                            </div>
                        </div>
                    `).join('') || '<p>Aucune grille pour ce projet.</p>'}
                </div>
                <div class="grid-actions mt-16">
                    <button class="btn btn--outline" data-action="import-grid">
                        📥 Importer une grille
                    </button>
                    <input type="file" id="gridFileInput" class="hidden" accept=".json">
                </div>
            </div>
        </div>
    `;
}

async function loadQueueStatus() {
    try {
        const status = await fetchAPI('/queue-status');
        return status;
    } catch (e) {
        return {};
    }
}

function renderQueueStatus() {
    loadQueueStatus().then(queuesStatus => {
        const container = document.getElementById('queueStatusContainer');
        if (!container) return;
        
        container.innerHTML = Object.keys(queuesStatus).length > 0 ? 
            Object.entries(queuesStatus).map(([name, status]) => `
                <div class="queue-item">
                    <div class="queue-info">
                        <span class="queue-name">${escapeHtml(name)}</span>
                        <span class="queue-count">${status.count} tâches</span>
                    </div>
                    <button class="btn btn--danger btn--sm" 
                            data-action="clearQueue" 
                            data-queue-name="${name}">
                        Vider
                    </button>
                </div>
            `).join('') :
            '<p>Impossible de récupérer l\'état des files.</p>';
    });
}

// ================================================================
// ===== 9. GESTION DES MODALES ET FORMULAIRES
// ================================================================

function openGridModal(gridId = null) {
  const modal = document.getElementById('gridModal');
  const form = document.getElementById('gridForm');
  const title = document.getElementById('gridModalTitle');
  const nameInput = document.getElementById('gridNameInput');
  const idInput = document.getElementById('gridIdInput');
  const fieldsContainer = document.getElementById('gridFieldsContainer');

  if (!modal || !form) return;

  // Reset du formulaire et chargement des champs
  form.reset();
  idInput.value = gridId || '';
  title.textContent = gridId ? "Modifier la grille" : "Créer une grille";
  fieldsContainer.innerHTML = '';

  if (gridId) {
    const grid = appState.currentProjectGrids.find(g => g.id === gridId);
    if (grid) {
      nameInput.value = grid.name;
      grid.fields.forEach(field => addGridFieldInput(field));
    }
  } else {
    addGridFieldInput(); // champ vide par défaut
  }

  openModal('gridModal');
}

function addGridFieldInput(value = '') {
    const container = document.getElementById('gridFieldsContainer');
    if (!container) return;
    
    const fieldDiv = document.createElement('div');
    fieldDiv.className = 'form-group-dynamic';
    fieldDiv.innerHTML = `
        <input type="text" class="form-control" value="${escapeHtml(value)}" placeholder="Nom du champ" required>
        <button type="button" class="btn btn--danger btn--sm" data-action="removeGridField">×</button>
    `;
    
    container.appendChild(fieldDiv);
}

async function handleSaveGrid(e) {
    e.preventDefault();
    
    if (!appState.currentProject) return;
    
    const gridId = document.getElementById('gridIdInput').value;
    const name = document.getElementById('gridNameInput').value;
    const fieldInputs = document.querySelectorAll('#gridFieldsContainer input');
    const fields = Array.from(fieldInputs).map(input => input.value.trim()).filter(Boolean);
    
    if (!name || fields.length === 0) {
        showToast("Le nom et au moins un champ sont requis.", "error");
        return;
    }
    
    const url = gridId ? 
        `/projects/${appState.currentProject.id}/grids/${gridId}` : 
        `/projects/${appState.currentProject.id}/grids`;
    const method = gridId ? 'PUT' : 'POST';
    
    showLoadingOverlay(true, 'Sauvegarde...');
    try {
        await fetchAPI(url, {
            method,
            body: { name, fields }
        });
        
        showToast('Grille sauvegardée.', 'success');
        closeModal('gridModal');
        await loadProjectGrids(appState.currentProject.id);
        renderSettingsSection();
        
    } catch (error) {
        console.error('Erreur sauvegarde grille:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleDeleteGrid(gridId) {
    if (!confirm("Supprimer cette grille d'extraction ?")) return;
    if (!appState.currentProject) return;
    
    showLoadingOverlay(true, 'Suppression...');
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/grids/${gridId}`, {
            method: 'DELETE'
        });
        
        showToast('Grille supprimée.', 'success');
        await loadProjectGrids(appState.currentProject.id);
        renderSettingsSection();
        
    } catch (error) {
        console.error('Erreur suppression grille:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function openPromptModal(promptId) {
    const prompt = appState.prompts.find(p => p.id == promptId); // Use == for loose comparison
    if (!prompt) return;
    
    const modal = document.getElementById('editPromptModal');
    const title = document.getElementById('promptModalTitle');
    const description = document.getElementById('promptDescription');
    const idInput = document.getElementById('promptIdInput');
    const textarea = document.getElementById('promptTemplateTextarea');
    
    if (!modal) return;
    
    title.textContent = `Modifier le prompt: ${prompt.name}`;
    description.textContent = prompt.description || '';
    idInput.value = prompt.id;
    textarea.value = prompt.template || '';
    
    openModal('editPromptModal');
}

async function handleSavePrompt(e) {
    e.preventDefault();
    
    const promptId = document.getElementById('promptIdInput').value;
    const template = document.getElementById('promptTemplateTextarea').value;
    
    if (!template.trim()) {
        showToast("Le template ne peut pas être vide.", "error");
        return;
    }
    
    showLoadingOverlay(true, 'Sauvegarde...');
    try {
        await fetchAPI(`/prompts/${promptId}`, {
            method: 'PUT',
            body: { template }
        });
        
        showToast('Prompt mis à jour.', 'success');
        closeModal('editPromptModal');
        await loadPrompts();
        renderSettingsSection();
        
    } catch (error) {
        console.error('Erreur sauvegarde prompt:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function openProfileModal(profileId = null) {
    const modal = document.getElementById('profileModal');
    const form = document.getElementById('profileForm');
    const title = document.getElementById('profileModalTitle');
    const idInput = document.getElementById('profileIdInput');
    const nameInput = document.getElementById('profileNameInput');
    
    if (!modal || !form) return;
    
    form.reset();
    idInput.value = profileId || '';
    title.textContent = profileId ? "Modifier le profil" : "Créer un profil";
    
    // Remplir les sélecteurs de modèles
    ['profilePreprocessSelect', 'profileExtractSelect', 'profileSynthesisSelect'].forEach(selectId => {
        const select = document.getElementById(selectId);
        if (select) {
            select.innerHTML = appState.ollamaModels.map(model => 
                `<option value="${model.name}">${escapeHtml(model.name)}</option>`
            ).join('');
        }
    });
    
    if (profileId) {
        const profile = appState.analysisProfiles.find(p => p.id === profileId);
        if (profile) {
            nameInput.value = profile.name;
            document.getElementById('profilePreprocessSelect').value = profile.preprocess_model;
            document.getElementById('profileExtractSelect').value = profile.extract_model;
            document.getElementById('profileSynthesisSelect').value = profile.synthesis_model;
        }
    }
    
    openModal('profileModal');
}

async function handleSaveProfile(e) {
    e.preventDefault();
    
    const formData = new FormData(e.target);
    const profileId = formData.get('profileIdInput');
    const profileData = {
        name: formData.get('profileNameInput'),
        preprocess_model: formData.get('profilePreprocessSelect'),
        extract_model: formData.get('profileExtractSelect'),
        synthesis_model: formData.get('profileSynthesisSelect')
    };
    
    if (!profileData.name || !profileData.preprocess_model || !profileData.extract_model || !profileData.synthesis_model) {
        showToast("Tous les champs sont requis.", "error");
        return;
    }
    
    const url = profileId ? `/analysis-profiles/${profileId}` : '/analysis-profiles';
    const method = profileId ? 'PUT' : 'POST';
    
    showLoadingOverlay(true, 'Sauvegarde...');
    try {
        await fetchAPI(url, {
            method,
            body: profileData
        });
        
        showToast('Profil sauvegardé.', 'success');
        closeModal('profileModal');
        await loadAnalysisProfiles();
        renderSettingsSection();
        
    } catch (error) {
        console.error('Erreur sauvegarde profil:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleDeleteProfile(profileId) {
    const profile = appState.analysisProfiles.find(p => p.id === profileId);
    if (!profile || !profile.is_custom) return;
    
    if (!confirm(`Supprimer le profil "${profile.name}" ?`)) return;
    
    showLoadingOverlay(true, 'Suppression...');
    try {
        await fetchAPI(`/analysis-profiles/${profileId}`, { method: 'DELETE' });
        showToast('Profil supprimé.', 'success');
        await loadAnalysisProfiles();
        renderSettingsSection();
    } catch (error) {
        console.error('Erreur suppression profil:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handlePullModel() {
    const modelNameInput = document.getElementById('pullModelName');
    const modelName = modelNameInput?.value.trim();
    
    if (!modelName) {
        showToast("Veuillez saisir un nom de modèle.", "error");
        return;
    }
    
    showLoadingOverlay(true, 'Téléchargement du modèle...');
    try {
        await fetchAPI('/ollama/pull', {
            method: 'POST',
            body: { model_name: modelName }
        });
        
        showToast(`Téléchargement du modèle "${modelName}" lancé.`, 'info');
        modelNameInput.value = '';
        
        // Recharger la liste des modèles après un délai
        setTimeout(async () => {
            await loadOllamaModels();
            renderSettingsSection();
        }, 2000);
        
    } catch (error) {
        console.error('Erreur téléchargement modèle:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleClearQueue(queueName) {
    if (!confirm(`Vider la file "${queueName}" ?`)) return;
    
    try {
        await fetchAPI('/queues/clear', {
            method: 'POST',
            body: { queue_name: queueName }
        });
        
        showToast(`File "${queueName}" vidée.`, 'success');
        renderQueueStatus();
        
    } catch (error) {
        console.error('Erreur vidage file:', error);
    }
}

async function handleSaveZoteroSettings() {
    const userId = document.getElementById('zoteroUserId')?.value;
    const apiKey = document.getElementById('zoteroApiKey')?.value;
    
    if (!userId || !apiKey) {
        showToast("Veuillez remplir tous les champs.", "error");
        return;
    }
    
    try {
        await fetchAPI('/settings/zotero', {
            method: 'POST',
            body: { userId, apiKey }
        });
        
        showToast('Paramètres Zotero sauvegardés.', 'success');
        
    } catch (error) {
        console.error('Erreur sauvegarde Zotero:', error);
    }
}

// ================================================================
// ===== 10. SECTIONS IMPORT ET CHAT
// ================================================================

async function handleManualPDFUpload(articleId, file) {
    if (!file || !appState.currentProject) return;

    showLoadingOverlay(true, `Import du PDF pour ${articleId}...`);
    
    const formData = new FormData();
    formData.append('file', file);
    // Le backend utilisera le nom du fichier pour l'article_id, mais on peut le passer en paramètre pour plus de robustesse si nécessaire
    // Par exemple : `/projects/${appState.currentProject.id}/${articleId}/upload-pdf`
		
    try {
        // On utilise l'endpoint d'upload en lot qui est déjà intelligent
        const result = await fetchAPI(`/projects/${appState.currentProject.id}/upload-pdfs-bulk`, {
            method: 'POST',
            body: formData,
        });

        if (result.successful && result.successful.length > 0) {
            showToast(`PDF pour l'article ${articleId} importé avec succès.`, 'success');
            // Rafraîchir la liste pour montrer le changement d'icône
            await renderProjectArticlesList(appState.currentProject.id);
        } else {
            throw new Error(result.failed[0] || 'Échec de l\'import.');
        }
    } catch (error) {
        console.error(`Erreur d'import manuel pour ${articleId}:`, error);
        showToast(`Erreur: ${error.message}`, 'error');
    } finally {
        showLoadingOverlay(false);
    }
}

async function renderProjectArticlesList(projectId) {
    const container = document.getElementById('project-articles-list');
    if (!container) return;

    try {
        const [articles, pdfFiles] = await Promise.all([
            fetchAPI(`/projects/${projectId}/search-results?per_page=1000`),
            fetchAPI(`/projects/${projectId}/files`)
        ]);

        const pdfFilenames = new Set(pdfFiles.map(f => f.filename));

        if (!articles.results || articles.results.length === 0) {
            container.innerHTML = '<p>Aucun article dans ce projet. Commencez par en ajouter via l\'onglet "Recherche" ou un import Zotero.</p>';
            return;
        }

        container.innerHTML = `
        <ul class="articles-list">
            ${articles.results.map(article => {
                const safeFilename = sanitizeFilename(article.article_id) + ".pdf"; 
				const hasPdf = pdfFilenames.has(safeFilename);
                const pdfActionHtml = hasPdf
                    ? `<a href="/api/projects/${projectId}/files/${safeFilename}" target="_blank" class="btn btn--secondary btn--sm" title="Ouvrir le PDF">📄</a>`
                    : `<button class="btn btn--primary btn--sm" data-action="upload-single-pdf" data-article-id="${escapeHtml(article.article_id)}" title="Ajouter un PDF">➕</button>`;

                return `
                    <li class="article-item">
                        <input type="checkbox" class="article-select-checkbox" data-article-id="${escapeHtml(article.article_id)}">
                        <span class="article-title">${escapeHtml(article.title)}</span>
                        <div class="article-actions">
                            <span class="article-id">${escapeHtml(article.article_id)}</span>
                            ${pdfActionHtml}
                        </div>
                    </li>`;
            }).join('')}
        </ul>`;
    } catch (error) {
        console.error("Erreur lors de l'affichage de la liste d'articles du projet:", error);
        if(container) {
            container.innerHTML = "<p>Erreur lors du chargement des articles.</p>";
        }
    }
}

async function renderImportSection() {
    const container = elements.importContainer;
    const project = appState.currentProject;

    if (!project) {
        container.innerHTML = `<div class="import-placeholder">
            <h4>Sélectionnez un projet</h4>
            <p>Veuillez sélectionner un projet pour pouvoir importer des documents.</p>
        </div>`;
        return;
    }

    container.innerHTML = `
        <div class="import-sections">
            <div class="import-card">
                <h4>1. Ajouter des Articles</h4>
                <p>Utilisez l'une des méthodes ci-dessous pour ajouter des articles à votre projet.</p>
                <div class="form-group">
                    <label class="form-label">Liste d'identifiants (un par ligne)</label>
                    <textarea id="manualPmidTextarea" class="form-control" rows="6" placeholder="Collez des PMIDs ou DOIs ici..."></textarea>
                </div>
                <div class="import-actions">
                    <button class="btn btn--secondary" data-action="import-zotero-list" data-project-id="${project.id}">📚 Zotero (via ID)</button>
                    <button class="btn btn--secondary" data-action="fetch-online-pdfs" data-project-id="${project.id}">🌐 Open Access (via ID)</button>
                </div>
                <hr>
                <p>Ou importez un fichier pour ajouter des articles et leurs PDF en une seule fois (recommandé).</p>
                <div class="import-actions">
                    <button class="btn btn--primary" data-action="import-zotero-file">📂 Importer Fichier Zotero (.json)</button>
                </div>
            </div>

            <div class="import-card" style="grid-column: 1 / -1;">
                <h4>2. Gérer les Articles du Projet (${project.pmids_count || 0})</h4>
                <div class="project-actions-header">
                    <p>Cochez les articles à supprimer, puis cliquez sur le bouton.</p>
                    <button class="btn btn--danger" data-action="delete-selected-articles">🗑️ Supprimer la sélection</button>
                </div>
                <div id="project-articles-list" class="articles-list-container"><div class="loading-spinner"></div></div>
            </div>

            <div class="import-card" style="grid-column: 1 / -1;">
                <h4>3. Indexer le Corpus</h4>
                <p>Après avoir récupéré les PDF, lancez l'indexation pour activer le Chat.</p>
                <button class="btn btn--primary" data-action="run-indexing" data-project-id="${project.id}">⚙️ Lancer l'Indexation</button>
            </div>
        </div>`;

    await renderProjectArticlesList(project.id);
}

function setupPDFDragDrop() {
    const dropZone = document.getElementById('pdfDropZone');
    const fileInput = document.getElementById('pdfFileInput');
    
    if (!dropZone || !fileInput) return;
    
    dropZone.addEventListener('click', () => fileInput.click());
    
    ['dragenter', 'dragover', 'dragleave', 'drop'].forEach(eventName => {
        dropZone.addEventListener(eventName, e => {
            e.preventDefault();
            e.stopPropagation();
        });
    });
    
    dropZone.addEventListener('dragenter', () => dropZone.classList.add('pdf-drop-zone--dragover'));
    dropZone.addEventListener('dragleave', () => dropZone.classList.remove('pdf-drop-zone--dragover'));
    
    dropZone.addEventListener('drop', e => {
        dropZone.classList.remove('pdf-drop-zone--dragover');
        handlePDFUpload(e.dataTransfer.files);
    });
    
    fileInput.addEventListener('change', e => handlePDFUpload(e.target.files));
}

async function handlePDFUpload(files) {
    const project = appState.currentProject;
    if (!project) {
        showToast("Veuillez d'abord sélectionner un projet.", 'error');
        return;
    }
    
    if (files.length > 20) {
        showToast("Vous ne pouvez importer que 20 fichiers à la fois.", "error");
        return;
    }

    const formData = new FormData();
    Array.from(files).forEach(file => formData.append('files', file));

    showLoadingOverlay(true, `Import de ${files.length} fichier(s)...`);
    const statusContainer = document.getElementById('pdfUploadStatus');
    if (statusContainer) statusContainer.innerHTML = '';

    try {
        const result = await fetchAPI(`/projects/${project.id}/upload-pdfs-bulk`, {
            method: 'POST',
            body: formData,
        });

        if (statusContainer) {
            result.successful?.forEach(name => {
                statusContainer.innerHTML += `<li class="upload-success">✅ ${escapeHtml(name)}</li>`;
            });
            result.failed?.forEach(name => {
                statusContainer.innerHTML += `<li class="upload-error">❌ ${escapeHtml(name)}</li>`;
            });
        }
        
        showToast(`Import terminé: ${result.successful?.length || 0}/${files.length} fichiers.`, 'success');

    } catch (error) {
        console.error('Erreur upload PDF:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleZoteroFileUpload(event) {
    event.preventDefault(); // Empêche le rechargement de la page
    
    const fileInput = document.getElementById('zoteroFileInput');
    if (!fileInput.files || fileInput.files.length === 0) {
        showToast('Veuillez d\'abord sélectionner un fichier Zotero.', 'warning');
        return;
    }
    const file = fileInput.files[0];

    if (!appState.currentProject) {
        showToast('Veuillez sélectionner un projet.', 'error');
        return;
    }

    showLoadingOverlay(true, 'Traitement du fichier Zotero...');
    
    const formData = new FormData();
    formData.append('file', file);

    try {
        const result = await fetchAPI(`/projects/${appState.currentProject.id}/import-zotero-file`, {
            method: 'POST',
            body: formData,
        });
        
        showToast(result.message || 'Import depuis le fichier Zotero lancé.', 'info');
        // Rafraîchit les données du projet pour afficher les nouveaux articles
        await selectProject(appState.currentProject.id, true);
    } catch (error) {
        console.error('Erreur import fichier Zotero:', error);
    } finally {
        showLoadingOverlay(false);
        fileInput.value = ''; // Réinitialise le champ de fichier
    }
}

async function handleImportZotero(projectId) {
    const textarea = document.getElementById('manualPmidTextarea');
    // CORRECTION : On utilise .split('\n') pour correctement séparer les lignes
    const articleIds = textarea?.value.split('\n').map(id => id.trim()).filter(Boolean) || [];

    if (articleIds.length === 0) {
        showToast("Veuillez fournir au moins un PMID ou DOI.", 'warning');
        return;
    }

    showLoadingOverlay(true, `Ajout et import Zotero pour ${articleIds.length} article(s)...`);
    try {
        await fetchAPI(`/projects/${projectId}/import-zotero`, {
            method: 'POST',
            body: { articles: articleIds }
        });
        showToast('Tâche d\'import depuis Zotero lancée en arrière-plan.', 'info');
        textarea.value = ''; // On vide le champ de texte
        await selectProject(projectId, true); // On rafraîchit les données du projet
    } catch (error) {
        console.error('Erreur import Zotero:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleFetchOnlinePdfs(projectId) {
    const textarea = document.getElementById('manualPmidTextarea');
    // CORRECTION : On utilise .split('\n') pour correctement séparer les lignes
    const articleIds = textarea?.value.split('\n').map(id => id.trim()).filter(Boolean) || [];

    if (articleIds.length === 0) {
        showToast("Veuillez fournir au moins un PMID ou DOI.", 'warning');
        return;
    }

    showLoadingOverlay(true, `Ajout et recherche de PDF pour ${articleIds.length} article(s)...`);
    try {
        await fetchAPI(`/projects/${projectId}/fetch-online-pdfs`, {
            method: 'POST',
            body: { articles: articleIds }
        });
        showToast('Tâche de recherche de PDF lancée en arrière-plan.', 'info');
        textarea.value = ''; // On vide le champ de texte
        await selectProject(projectId, true); // On rafraîchit les données du projet
    } catch (error) {
        console.error('Erreur recherche PDF:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

async function handleRunIndexing(projectId) {
    showLoadingOverlay(true, "Lancement de l'indexation...");
    try {
        await fetchAPI(`/projects/${projectId}/index`, { method: 'POST' });
        showToast('Indexation du corpus lancée. Vous recevrez une notification quand ce sera terminé.', 'info');
    } catch (error) {
        console.error('Erreur indexation:', error);
    } finally {
        showLoadingOverlay(false);
    }
}

function renderChatSection() {
    const container = elements.chatContainer;
    const project = appState.currentProject;

    if (!project) {
        container.innerHTML = `
            <div class="chat-placeholder">
                <div class="chat-placeholder__icon">👈</div>
                <h4>Sélectionnez un projet</h4>
                <p>Sélectionnez un projet pour discuter avec ses documents.</p>
            </div>`;
        return;
    }

    container.innerHTML = `
        <div class="chat-header">
            <h3>💬 Chat avec ${escapeHtml(project.name)}</h3>
            <button class="btn btn--outline btn--sm" data-action="clearChatHistory">
                🗑️ Effacer historique
            </button>
        </div>
        
        <div id="chatMessages" class="chat-messages">
            <div class="chat-message chat-message--assistant">
                <div class="chat-message__content">
                    Bonjour ! Posez-moi une question sur les documents indexés de votre projet.
                </div>
            </div>
        </div>
        
        <div class="chat-input-area">
            <textarea id="chatTextarea" class="form-control" 
                      placeholder="Posez votre question ici..." 
                      rows="3"></textarea>
            <button class="btn btn--primary" data-action="sendChatMessage">
                📤 Envoyer
            </button>
        </div>
    `;
    
    loadChatHistory(project.id);
}

async function loadChatHistory(projectId) {
    try {
        const history = await fetchAPI(`/projects/${projectId}/chat-history`);
        const messagesContainer = document.getElementById('chatMessages');
        
        if (!messagesContainer) return;
        
        // Conserver le message d'accueil
        const welcomeMessage = messagesContainer.querySelector('.chat-message--assistant');
        messagesContainer.innerHTML = '';
        if (welcomeMessage) messagesContainer.appendChild(welcomeMessage);
        
        history.forEach(msg => {
            appendChatMessage(msg.role, msg.content, msg.sources);
        });
        
    } catch (e) {
        showToast("Impossible de charger l'historique du chat.", "error");
    }
}

async function sendChatMessage() {
    const project = appState.currentProject;
    if (!project) return;
    
    const textarea = document.getElementById('chatTextarea');
    const question = textarea?.value.trim();
    
    if (!question) {
        showToast("Veuillez saisir une question.", "warning");
        return;
    }

    appendChatMessage('user', question);
    textarea.value = '';
    textarea.disabled = true;

    try {
        const result = await fetchAPI(`/projects/${project.id}/chat`, {
            method: 'POST',
            body: { 
                question, 
                profile: project.profile_used || 'standard' 
            }
        });
        
        appendChatMessage('assistant', result.answer, result.sources);
        
    } catch (error) {
        console.error('Erreur chat:', error);
        appendChatMessage('assistant', "Désolé, une erreur est survenue lors de la génération de la réponse.", []);
    } finally {
        textarea.disabled = false;
        textarea.focus();
    }
}

function appendChatMessage(role, content, sources = null) {
    const container = document.getElementById('chatMessages');
    if (!container) return;
    
    const msgDiv = document.createElement('div');
    msgDiv.className = `chat-message chat-message--${role}`;

    let sourcesHtml = '';
    if (sources) {
        try {
            const sourcesList = typeof sources === 'string' ? JSON.parse(sources) : sources;
            if (Array.isArray(sourcesList) && sourcesList.length > 0) {
                sourcesHtml = `<div class="chat-message__sources"><strong>Sources:</strong> ${sourcesList.join(', ')}</div>`;
            }
        } catch (e) {
            console.warn('Erreur parsing sources:', e);
        }
    }

    msgDiv.innerHTML = `
        <div class="chat-message__content">
            ${escapeHtml(content).replace(/\n/g, '<br>')}
            ${sourcesHtml}
        </div>
    `;
    
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function clearChatHistory() {
    if (!confirm("Effacer tout l'historique de chat pour ce projet ?")) return;
    
    const messagesContainer = document.getElementById('chatMessages');
    if (messagesContainer) {
        messagesContainer.innerHTML = `
            <div class="chat-message chat-message--assistant">
                <div class="chat-message__content">
                    Historique effacé. Posez-moi une nouvelle question !
                </div>
            </div>
        `;
    }
}

// ================================================================
// ===== 11. FONCTIONS UTILITAIRES FINALES
// ================================================================

function viewAnalysisPlot(projectId, plotType) {
    const url = `/api/projects/${projectId}/analysis-plot/${plotType}`;
    window.open(url, '_blank');
}

async function handleValidateExtraction(extractionId, decision, evaluatorId) {
    if (!appState.currentProject) return;
    try {
        await fetchAPI(`/extractions/${extractionId}/validate`, {
            method: 'POST',
            body: { decision, evaluator_id: evaluatorId }
        });
        showToast(`Article marqué comme "${decision}"`, 'success');
        // Rafraîchir la vue pour voir le changement
        const extraction = appState.currentProjectExtractions.find(e => e.id === extractionId);
        if (extraction) {
            if (!extraction.validations) extraction.validations = "{}";
            const validations = JSON.parse(extraction.validations);
            validations[evaluatorId] = decision;
            extraction.validations = JSON.stringify(validations);
            renderValidationSection(); // Re-render la section
        }
    } catch (error) {
        showToast("Erreur lors de la validation", "error");
    }
}

function sanitizeFilename(articleId) {
    if (!articleId) return '';
    // Remplace les caractères non alphanumériques (sauf le point et le tiret) par un underscore.
    // Correspond à la logique Python re.sub(r'[^a-zA-Z0-9.-]', '_', article_id)
    return String(articleId).replace(/[^a-zA-Z0-9.-]/g, '_');
}

async function handleDeleteSelectedArticles() {
    const selectedCheckboxes = document.querySelectorAll('#project-articles-list .article-select-checkbox:checked');
    const articleIdsToDelete = Array.from(selectedCheckboxes).map(cb => cb.dataset.articleId);

    if (articleIdsToDelete.length === 0) {
        showToast("Veuillez sélectionner au moins un article à supprimer.", "warning");
        return;
    }

    if (!confirm(`Êtes-vous sûr de vouloir supprimer définitivement ${articleIdsToDelete.length} article(s) ?`)) {
        return;
    }

    showLoadingOverlay(true, 'Suppression des articles...');
    try {
        await fetchAPI(`/projects/${appState.currentProject.id}/delete-articles`, {
            method: 'POST',
            body: { article_ids: articleIdsToDelete }
        });
        showToast(`${articleIdsToDelete.length} article(s) supprimé(s).`, 'success');
        await selectProject(appState.currentProject.id, true); // Rafraîchir
    } finally {
        showLoadingOverlay(false);
    }
}

// ================================================================
// ===== 12. INITIALISATION FINALE
// ================================================================

// Fonction appelée quand le DOM est prêt (déjà définie plus haut)
console.log('📚 AnalyLit V4.0 Frontend - Script chargé et prêt');