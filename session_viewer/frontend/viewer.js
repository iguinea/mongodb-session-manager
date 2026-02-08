/**
 * Session Viewer - Main Application
 *
 * Architecture:
 * - APIClient: HTTP communication with backend
 * - FilterPanel: Dynamic filter management
 * - ResultsList: Search results with pagination
 * - SessionDetail: Session visualization with timeline
 * - SessionViewer: Main orchestrator
 */

/**
 * API Client Class
 * Handles all HTTP communication with the backend
 */
class APIClient {
  constructor(baseURL = '/api/session_viewer/v1') {
    this.baseURL = baseURL;
    this.axios = axios.create({
      baseURL: this.baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json',
        ...axios.defaults.headers.common  // Include authentication headers
      }
    });
  }

  /**
   * Check backend health
   */
  async checkHealth() {
    const response = await this.axios.get('/health', { baseURL: '/' });
    return response.data;
  }

  /**
   * Get available metadata fields
   */
  async getMetadataFields() {
    const response = await this.axios.get('/metadata-fields');
    return response.data;
  }

  /**
   * Search sessions with filters
   */
  async searchSessions(filters = {}, sessionId = '', dateStart = null, dateEnd = null, limit = 20, offset = 0) {
    const params = new URLSearchParams();

    // Add filters as JSON string
    if (Object.keys(filters).length > 0) {
      params.append('filters', JSON.stringify(filters));
    }

    // Add session ID
    if (sessionId) {
      params.append('session_id', sessionId);
    }

    // Add date range
    if (dateStart) {
      params.append('created_at_start', new Date(dateStart).toISOString());
    }
    if (dateEnd) {
      params.append('created_at_end', new Date(dateEnd).toISOString());
    }

    // Add pagination
    params.append('limit', limit);
    params.append('offset', offset);

    const response = await this.axios.get(`/sessions/search?${params.toString()}`);
    return response.data;
  }

  /**
   * Get session detail by ID
   * @param {string} sessionId - Session ID to retrieve
   * @param {Object} additionalHeaders - Optional additional headers to include
   */
  async getSessionDetail(sessionId, additionalHeaders = {}) {
    const response = await this.axios.get(`/sessions/${sessionId}`, {
      headers: additionalHeaders
    });
    return response.data;
  }
}

/**
 * Filter Panel Class
 * Manages dynamic filters for searching
 */
class FilterPanel {
  constructor(container, onSearch, onClear) {
    this.container = container;
    this.onSearch = onSearch;
    this.onClear = onClear;
    this.fieldInfos = [];
    this.dynamicFilters = [];

    this.init();
  }

  init() {
    // Get DOM elements
    this.sessionIdInput = document.getElementById('filter-session-id');
    this.dateStartInput = document.getElementById('filter-date-start');
    this.dateEndInput = document.getElementById('filter-date-end');
    this.filtersContainer = document.getElementById('dynamic-filters-container');
    this.addFilterBtn = document.getElementById('add-filter-btn');
    this.searchBtn = document.getElementById('search-btn');
    this.clearBtn = document.getElementById('clear-filters-btn');

    // Bind events
    this.addFilterBtn.addEventListener('click', () => this.addFilter());
    this.searchBtn.addEventListener('click', () => this.handleSearch());
    this.clearBtn.addEventListener('click', () => this.handleClear());

    // Allow Enter key to trigger search
    [this.sessionIdInput, this.dateStartInput, this.dateEndInput].forEach(input => {
      input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') this.handleSearch();
      });
    });
  }

  /**
   * Load available indexed fields from backend
   * Now receives FieldInfo objects with type information
   */
  async loadMetadataFields(apiClient) {
    try {
      const data = await apiClient.getMetadataFields();

      // Store FieldInfo objects and sort alphabetically by field name
      this.fieldInfos = (data.fields || []).sort((a, b) =>
        a.field.toLowerCase().localeCompare(b.field.toLowerCase())
      );

      console.log(`Loaded ${this.fieldInfos.length} indexed fields with types:`,
        this.fieldInfos.map(f => `${f.field} (${f.type})`).join(', ')
      );
    } catch (error) {
      console.error('Error loading metadata fields:', error);
      this.fieldInfos = [];
    }
  }

  /**
   * Add a new dynamic filter
   * Now passes fieldInfos instead of simple field names
   */
  addFilter() {
    // Render filter with type information
    const filterElement = Components.renderDynamicFilter(this.fieldInfos);

    // Bind remove button
    const removeBtn = filterElement.querySelector('.remove-filter-btn');
    removeBtn.addEventListener('click', () => {
      filterElement.remove();
      const index = this.dynamicFilters.indexOf(filterElement);
      if (index > -1) {
        this.dynamicFilters.splice(index, 1);
      }
    });

    this.dynamicFilters.push(filterElement);
    this.filtersContainer.appendChild(filterElement);
  }

  /**
   * Get all filter values
   */
  getFilters() {
    const filters = {};

    // Get dynamic metadata filters
    this.dynamicFilters.forEach(filterEl => {
      const field = filterEl.querySelector('.filter-field').value;
      const value = filterEl.querySelector('.filter-value').value.trim();

      if (field && value) {
        filters[field] = value;
      }
    });

    return {
      filters,
      sessionId: this.sessionIdInput.value.trim(),
      dateStart: this.dateStartInput.value,
      dateEnd: this.dateEndInput.value
    };
  }

  /**
   * Handle search button click
   */
  handleSearch() {
    const filterValues = this.getFilters();
    this.onSearch(filterValues);
  }

  /**
   * Handle clear button click
   */
  handleClear() {
    // Clear input fields
    this.sessionIdInput.value = '';
    this.dateStartInput.value = '';
    this.dateEndInput.value = '';

    // Remove all dynamic filters
    this.dynamicFilters.forEach(filter => filter.remove());
    this.dynamicFilters = [];

    // Trigger clear callback
    this.onClear();
  }
}

/**
 * Results List Class
 * Displays search results with pagination
 */
class ResultsList {
  constructor(container, onSessionSelect) {
    this.container = container;
    this.onSessionSelect = onSessionSelect;

    this.resultsContainer = document.getElementById('results-list');
    this.loadingElement = document.getElementById('results-loading');
    this.emptyElement = document.getElementById('results-empty');
    this.countElement = document.getElementById('results-count');
    this.paginationContainer = document.getElementById('pagination-container');

    this.prevBtn = document.getElementById('prev-page-btn');
    this.nextBtn = document.getElementById('next-page-btn');
    this.pageInfo = document.getElementById('page-info');

    this.currentPage = 1;
    this.totalPages = 1;
    this.pageSize = 20;

    this.init();
  }

  init() {
    // Bind pagination buttons
    this.prevBtn.addEventListener('click', () => this.goToPrevPage());
    this.nextBtn.addEventListener('click', () => this.goToNextPage());
  }

  /**
   * Show loading state
   */
  showLoading() {
    this.loadingElement.classList.remove('hidden');
    this.emptyElement.classList.add('hidden');
    this.resultsContainer.innerHTML = '';
  }

  /**
   * Show empty state
   */
  showEmpty() {
    this.loadingElement.classList.add('hidden');
    this.emptyElement.classList.remove('hidden');
    this.resultsContainer.innerHTML = '';
    this.paginationContainer.classList.add('hidden');
    this.countElement.textContent = '0 sesiones';
  }

  /**
   * Render search results
   */
  render(searchResults) {
    this.loadingElement.classList.add('hidden');
    this.emptyElement.classList.add('hidden');

    const { sessions, total, limit, offset } = searchResults;

    // Update count
    this.countElement.textContent = `${Components.Format.number(total)} ${total === 1 ? 'sesión' : 'sesiones'}`;

    // Check if empty
    if (sessions.length === 0) {
      this.showEmpty();
      return;
    }

    // Clear previous results
    this.resultsContainer.innerHTML = '';

    // Render session cards
    sessions.forEach(session => {
      const card = Components.renderSessionCard(session);
      card.addEventListener('click', () => this.onSessionSelect(session.session_id));
      this.resultsContainer.appendChild(card);
    });

    // Update pagination
    this.currentPage = Math.floor(offset / limit) + 1;
    this.totalPages = Math.ceil(total / limit);
    this.pageSize = limit;
    this.updatePagination(total > limit);
  }

  /**
   * Update pagination UI
   */
  updatePagination(show = true) {
    if (!show) {
      this.paginationContainer.classList.add('hidden');
      return;
    }

    this.paginationContainer.classList.remove('hidden');
    this.pageInfo.textContent = `Página ${this.currentPage} de ${this.totalPages}`;

    // Update button states
    this.prevBtn.disabled = this.currentPage <= 1;
    this.nextBtn.disabled = this.currentPage >= this.totalPages;
  }

  /**
   * Go to previous page
   */
  goToPrevPage() {
    if (this.currentPage > 1) {
      this.currentPage--;
      this.onPageChange(this.currentPage);
    }
  }

  /**
   * Go to next page
   */
  goToNextPage() {
    if (this.currentPage < this.totalPages) {
      this.currentPage++;
      this.onPageChange(this.currentPage);
    }
  }

  /**
   * Set page change callback
   */
  setPageChangeCallback(callback) {
    this.onPageChange = callback;
  }
}

/**
 * Session Detail Class
 * Displays complete session with timeline using tabbed interface
 */
class SessionDetail {
  constructor(container) {
    this.container = container;

    this.emptyElement = document.getElementById('detail-empty');
    this.loadingElement = document.getElementById('detail-loading');
    this.detailContainer = document.getElementById('detail-container');

    this.sessionIdDisplay = document.getElementById('detail-session-id');
    this.metadataDisplay = document.getElementById('metadata-display');
    this.agentsSummary = document.getElementById('agents-summary');
    this.timelineContainer = document.getElementById('timeline-container');
    this.tokenSummaryContainer = document.getElementById('token-summary-container');

    this.closeBtn = document.getElementById('close-detail-btn');

    // Tab elements
    this.tabs = document.querySelectorAll('.session-tab');
    this.tabPanels = document.querySelectorAll('.tab-panel');
    this.activeTab = 'timeline';

    this.init();
  }

  init() {
    // Bind close button
    this.closeBtn.addEventListener('click', () => this.hide());

    // Initialize tab switching
    this.initTabs();
  }

  /**
   * Initialize tab switching functionality
   */
  initTabs() {
    this.tabs.forEach(tab => {
      tab.addEventListener('click', () => {
        const tabName = tab.dataset.tab;
        this.switchTab(tabName);
      });
    });
  }

  /**
   * Switch to a specific tab
   */
  switchTab(tabName) {
    // Update active tab state
    this.activeTab = tabName;

    // Update tab button styles
    this.tabs.forEach(tab => {
      if (tab.dataset.tab === tabName) {
        tab.classList.add('active');
      } else {
        tab.classList.remove('active');
      }
    });

    // Show/hide tab panels
    this.tabPanels.forEach(panel => {
      const panelTab = panel.id.replace('tab-panel-', '');
      if (panelTab === tabName) {
        panel.classList.remove('hidden');
      } else {
        panel.classList.add('hidden');
      }
    });
  }

  /**
   * Show loading state
   */
  showLoading() {
    this.emptyElement.classList.add('hidden');
    this.loadingElement.classList.remove('hidden');
    this.detailContainer.classList.add('hidden');
  }

  /**
   * Hide detail panel
   */
  hide() {
    this.emptyElement.classList.remove('hidden');
    this.loadingElement.classList.add('hidden');
    this.detailContainer.classList.add('hidden');

    // Reset to Timeline tab when hiding
    this.switchTab('timeline');
  }

  /**
   * Render session detail
   */
  async render(sessionData) {
    this.emptyElement.classList.add('hidden');
    this.loadingElement.classList.add('hidden');
    this.detailContainer.classList.remove('hidden');

    // Reset to Timeline tab when loading a new session
    this.switchTab('timeline');

    // Display session ID
    this.sessionIdDisplay.textContent = sessionData.session_id;

    // Render metadata
    this.metadataDisplay.innerHTML = '';
    this.metadataDisplay.appendChild(Components.renderMetadata(sessionData.metadata));

    // Render agents summary
    this.agentsSummary.innerHTML = '';
    Object.entries(sessionData.agents_summary).forEach(([agentId, summary]) => {
      this.agentsSummary.appendChild(Components.renderAgentSummary(agentId, summary));
    });

    // Render timeline
    await this.renderTimeline(sessionData.timeline);

    // Render token summary
    this.renderTokenSummary(sessionData.timeline, sessionData.agents_summary);
  }

  /**
   * Render token consumption summary with cost calculation
   * Calculates cost per agent/model when multiple models are used
   * Now displayed in dedicated "Consumo" tab
   */
  renderTokenSummary(timeline, agentsSummary) {
    if (!this.tokenSummaryContainer) return;

    // Get the last assistant message with metrics for EACH agent
    const agentMetrics = {};

    for (const item of timeline) {
      if (item.type === 'message' && item.role === 'assistant' && item.metrics) {
        // Store/update the last metrics for this agent
        agentMetrics[item.agent_id] = {
          metrics: item.metrics,
          model: agentsSummary[item.agent_id]?.model || 'claude-3-5-sonnet'
        };
      }
    }

    // Check if we have any metrics
    if (Object.keys(agentMetrics).length === 0) {
      this.tokenSummaryContainer.innerHTML = '<p class="text-sm text-gray-500 italic">Sin métricas de consumo disponibles para esta sesión.</p>';
      return;
    }

    // Render token summary with per-agent breakdown
    const summaryElement = Components.renderTokenSummary(agentMetrics);
    this.tokenSummaryContainer.innerHTML = '';
    this.tokenSummaryContainer.appendChild(summaryElement);
  }

  /**
   * Render timeline items
   */
  async renderTimeline(timeline) {
    this.timelineContainer.innerHTML = '';

    if (!timeline || timeline.length === 0) {
      this.timelineContainer.innerHTML = '<p class="text-sm text-gray-500 text-center py-4">Sin mensajes</p>';
      return;
    }

    // Use for...of to support await
    for (const item of timeline) {
      let element;

      if (item.type === 'message') {
        element = await Components.renderTimelineMessage(item);
      } else if (item.type === 'feedback') {
        element = Components.renderTimelineFeedback(item);
      }

      if (element) {
        this.timelineContainer.appendChild(element);
      }
    }

    // Scroll to top
    this.timelineContainer.scrollTop = 0;
  }
}

/**
 * Panel Resizer Class
 * Handles drag-based resizing of left panel
 */
class PanelResizer {
  constructor() {
    this.leftPanel = document.getElementById('left-panel');
    this.rightPanel = document.getElementById('right-panel');
    this.resizeHandle = document.getElementById('resize-handle');
    this.mainLayout = document.getElementById('main-layout');
    this.isDragging = false;
    this.minWidth = 20; // 20%
    this.maxWidth = 70; // 70%
    this.storageKey = 'session-viewer-left-panel-width';

    this.init();
  }

  init() {
    // Load saved width from localStorage
    this.loadSavedWidth();

    // Bind mouse events
    this.resizeHandle.addEventListener('mousedown', (e) => this.startDrag(e));
    document.addEventListener('mousemove', (e) => this.drag(e));
    document.addEventListener('mouseup', () => this.stopDrag());
  }

  /**
   * Start dragging
   */
  startDrag(e) {
    e.preventDefault();
    this.isDragging = true;
    this.resizeHandle.classList.add('dragging');
    document.body.classList.add('resizing');
  }

  /**
   * Handle drag movement
   */
  drag(e) {
    if (!this.isDragging) return;

    e.preventDefault();

    // Get container width
    const containerWidth = this.mainLayout.offsetWidth;

    // Calculate new left panel width based on mouse position
    const newWidth = e.clientX - this.mainLayout.getBoundingClientRect().left;

    // Convert to percentage
    const widthPercentage = (newWidth / containerWidth) * 100;

    // Apply constraints
    const constrainedWidth = Math.min(Math.max(widthPercentage, this.minWidth), this.maxWidth);

    // Apply width
    this.leftPanel.style.width = `${constrainedWidth}%`;

    // Save to localStorage
    this.saveWidth(constrainedWidth);
  }

  /**
   * Stop dragging
   */
  stopDrag() {
    if (!this.isDragging) return;

    this.isDragging = false;
    this.resizeHandle.classList.remove('dragging');
    document.body.classList.remove('resizing');
  }

  /**
   * Save width to localStorage
   */
  saveWidth(percentage) {
    try {
      localStorage.setItem(this.storageKey, percentage.toString());
    } catch (error) {
      console.warn('Failed to save panel width to localStorage:', error);
    }
  }

  /**
   * Load saved width from localStorage
   */
  loadSavedWidth() {
    try {
      const savedWidth = localStorage.getItem(this.storageKey);
      if (savedWidth) {
        const width = parseFloat(savedWidth);
        // Validate width is within constraints
        if (width >= this.minWidth && width <= this.maxWidth) {
          this.leftPanel.style.width = `${width}%`;
        }
      }
    } catch (error) {
      console.warn('Failed to load panel width from localStorage:', error);
    }
  }
}

/**
 * Main Session Viewer Class
 * Orchestrates all components
 */
class SessionViewer {
  constructor(directSessionId = null) {
    this.apiClient = new APIClient();
    this.currentFilters = null;
    this.sessionPasswordCache = new Map();  // Cache of session passwords for repeated access
    this.pendingSessionId = directSessionId;  // Session ID passed from index.html
    this.isDirectSessionAccess = !!directSessionId;  // Flag for direct session access
  }

  static async create(directSessionId = null) {
    const viewer = new SessionViewer(directSessionId);
    await viewer.init();
    return viewer;
  }

  async init() {
    // Initialize components
    this.filterPanel = new FilterPanel(
      document.querySelector('.col-span-3'),
      (filters) => this.handleSearch(filters),
      () => this.handleClearFilters()
    );

    this.resultsList = new ResultsList(
      document.querySelector('.col-span-4'),
      (sessionId) => this.handleSessionSelect(sessionId)
    );

    this.sessionDetail = new SessionDetail(
      document.querySelector('.col-span-5')
    );

    // Set pagination callback
    this.resultsList.setPageChangeCallback((page) => {
      this.handlePageChange(page);
    });

    // Check backend health
    await this.checkBackendHealth();

    // Only load metadata fields if NOT direct session access
    // Direct session access with session password should not have access to search/metadata
    if (!this.isDirectSessionAccess) {
      await this.filterPanel.loadMetadataFields(this.apiClient);
    }

    // Handle direct session loading if session_id was passed
    if (this.isDirectSessionAccess && this.pendingSessionId) {
      this.handleDirectSessionAccess(this.pendingSessionId);
    }
  }

  /**
   * Handle direct session access via ?session_id=... query parameter
   */
  handleDirectSessionAccess(sessionId) {
    console.log(`Loading session from URL parameter: ${sessionId}`);

    // Hide left panel (filters + results) and resize handle
    const leftPanel = document.getElementById('left-panel');
    const resizeHandle = document.getElementById('resize-handle');
    const rightPanel = document.getElementById('right-panel');

    if (leftPanel) leftPanel.classList.add('hidden-panel');
    if (resizeHandle) resizeHandle.classList.add('hidden-panel');
    if (rightPanel) rightPanel.style.width = '100%';

    // Store pending session ID
    this.pendingSessionId = sessionId;

    // Check if password is already cached for this session
    if (this.sessionPasswordCache.has(sessionId)) {
      console.log(`Using cached password for session ${sessionId}`);
      this.handleSessionSelect(sessionId);
    } else {
      // Prompt for session password
      this.promptSessionPassword(sessionId);
    }
  }

  /**
   * Check backend health and update indicator
   */
  async checkBackendHealth() {
    const indicator = document.getElementById('health-indicator');

    try {
      const health = await this.apiClient.checkHealth();

      if (health.status === 'healthy') {
        indicator.innerHTML = `
          <div class="w-2 h-2 bg-green-500 rounded-full"></div>
          <span class="text-sm text-green-600">Conectado</span>
        `;
      } else {
        indicator.innerHTML = `
          <div class="w-2 h-2 bg-yellow-500 rounded-full"></div>
          <span class="text-sm text-yellow-600">Degradado</span>
        `;
      }
    } catch (error) {
      indicator.innerHTML = `
        <div class="w-2 h-2 bg-red-500 rounded-full"></div>
        <span class="text-sm text-red-600">Desconectado</span>
      `;
      console.error('Backend health check failed:', error);
    }
  }

  /**
   * Handle search
   */
  async handleSearch(filters) {
    this.currentFilters = filters;
    this.resultsList.showLoading();

    try {
      const results = await this.apiClient.searchSessions(
        filters.filters,
        filters.sessionId,
        filters.dateStart,
        filters.dateEnd,
        20,
        0
      );

      this.resultsList.render(results);
    } catch (error) {
      console.error('Search error:', error);
      alert('Error al buscar sesiones. Por favor, intenta de nuevo.');
      this.resultsList.showEmpty();
    }
  }

  /**
   * Handle clear filters
   */
  handleClearFilters() {
    this.currentFilters = null;
    this.resultsList.showEmpty();
    this.sessionDetail.hide();
  }

  /**
   * Prompt for session password (Direct access via URL)
   */
  promptSessionPassword(sessionId) {
    const modal = document.getElementById('session-password-modal');
    const input = document.getElementById('session-password-input');
    const form = document.getElementById('session-password-form');
    const errorDiv = document.getElementById('session-password-error');
    const cancelBtn = document.getElementById('session-password-cancel-btn');

    // Show modal
    modal.classList.remove('hidden');
    input.value = '';
    errorDiv.classList.add('hidden');
    errorDiv.textContent = '';
    input.focus();

    // Clear previous listeners
    form.onsubmit = null;
    cancelBtn.onclick = null;

    // Handle form submission
    form.onsubmit = async (e) => {
      e.preventDefault();
      const password = input.value.trim();

      if (!password) {
        errorDiv.textContent = 'Por favor, introduce una contraseña';
        errorDiv.classList.remove('hidden');
        return;
      }

      // Validate password
      await this.checkSessionPassword(sessionId, password);
    };

    // Handle cancel
    cancelBtn.onclick = () => {
      modal.classList.add('hidden');
      this.pendingSessionId = null;
      // Optionally redirect to main view
      window.location.href = '/';
    };
  }

  /**
   * Check session password against backend
   */
  async checkSessionPassword(sessionId, password) {
    const modal = document.getElementById('session-password-modal');
    const errorDiv = document.getElementById('session-password-error');
    const submitBtn = document.getElementById('session-password-submit-btn');
    const input = document.getElementById('session-password-input');

    try {
      // Disable submit button and show loading
      submitBtn.disabled = true;
      submitBtn.textContent = 'Verificando...';
      errorDiv.classList.add('hidden');

      // Hash password with SHA-256
      const passwordHash = await this.hashPassword(password);

      // Call backend to validate
      const response = await fetch(`/api/session_viewer/v1/sessions/${sessionId}/check_password`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ password_hash: passwordHash })
      });

      const result = await response.json();

      if (result.valid) {
        // Password is correct - cache it and load session
        this.sessionPasswordCache.set(sessionId, passwordHash);

        console.log(result.used_global
          ? `Access granted with master password for session ${sessionId}`
          : `Access granted with session password for session ${sessionId}`
        );

        // Hide modal and load session
        // The password will be sent in the request via handleSessionSelect()
        modal.classList.add('hidden');
        await this.handleSessionSelect(sessionId);
      } else {
        // Invalid password
        errorDiv.textContent = 'Contraseña incorrecta. Debe usar la contraseña de sesión o la contraseña maestra.';
        errorDiv.classList.remove('hidden');
        input.value = '';
        input.focus();

        // Re-enable submit button
        submitBtn.disabled = false;
        submitBtn.textContent = 'Acceder';
      }
    } catch (error) {
      console.error('Error checking session password:', error);
      errorDiv.textContent = 'Error al validar la contraseña. Por favor, intenta de nuevo.';
      errorDiv.classList.remove('hidden');

      // Re-enable submit button
      submitBtn.disabled = false;
      submitBtn.textContent = 'Acceder';
    }
  }

  /**
   * Hash password using SHA-256
   */
  async hashPassword(password) {
    const encoder = new TextEncoder();
    const data = encoder.encode(password);
    const hashBuffer = await crypto.subtle.digest('SHA-256', data);
    const hashArray = Array.from(new Uint8Array(hashBuffer));
    return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
  }

  /**
   * Handle page change
   */
  async handlePageChange(page) {
    if (!this.currentFilters) return;

    this.resultsList.showLoading();

    try {
      const offset = (page - 1) * this.resultsList.pageSize;
      const results = await this.apiClient.searchSessions(
        this.currentFilters.filters,
        this.currentFilters.sessionId,
        this.currentFilters.dateStart,
        this.currentFilters.dateEnd,
        this.resultsList.pageSize,
        offset
      );

      this.resultsList.render(results);
    } catch (error) {
      console.error('Pagination error:', error);
      alert('Error al cargar la página. Por favor, intenta de nuevo.');
    }
  }

  /**
   * Handle session selection
   */
  async handleSessionSelect(sessionId) {
    this.sessionDetail.showLoading();

    try {
      // If this session has a cached password (direct access mode), send it in the request
      const additionalHeaders = {};
      if (this.sessionPasswordCache.has(sessionId)) {
        additionalHeaders['X-Session-Password'] = this.sessionPasswordCache.get(sessionId);
      }

      const sessionData = await this.apiClient.getSessionDetail(sessionId, additionalHeaders);
      this.sessionDetail.render(sessionData);
    } catch (error) {
      console.error('Error loading session:', error);
      alert('Error al cargar la sesión. Por favor, intenta de nuevo.');
      this.sessionDetail.hide();
    }
  }
}

// Application will be initialized from index.html
