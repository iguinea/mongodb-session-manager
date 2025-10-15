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
  constructor(baseURL = 'http://localhost:8882/api/v1') {
    this.baseURL = baseURL;
    this.axios = axios.create({
      baseURL: this.baseURL,
      timeout: 30000,
      headers: {
        'Content-Type': 'application/json'
      }
    });
  }

  /**
   * Check backend health
   */
  async checkHealth() {
    const response = await this.axios.get('/health', { baseURL: 'http://localhost:8882' });
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
   */
  async getSessionDetail(sessionId) {
    const response = await this.axios.get(`/sessions/${sessionId}`);
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
    this.availableFields = [];
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
   * Load available metadata fields from backend
   */
  async loadMetadataFields(apiClient) {
    try {
      const data = await apiClient.getMetadataFields();
      this.availableFields = data.fields || [];
    } catch (error) {
      console.error('Error loading metadata fields:', error);
      this.availableFields = [];
    }
  }

  /**
   * Add a new dynamic filter
   */
  addFilter() {
    const filterElement = Components.renderDynamicFilter(this.availableFields);

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
 * Displays complete session with timeline
 */
class SessionDetail {
  constructor(container) {
    this.container = container;

    this.emptyElement = document.getElementById('detail-empty');
    this.loadingElement = document.getElementById('detail-loading');
    this.detailContainer = document.getElementById('detail-container');

    this.sessionIdDisplay = document.getElementById('detail-session-id');
    this.metadataContent = document.getElementById('metadata-content');
    this.metadataDisplay = document.getElementById('metadata-display');
    this.agentsSummary = document.getElementById('agents-summary');
    this.timelineContainer = document.getElementById('timeline-container');

    this.closeBtn = document.getElementById('close-detail-btn');
    this.toggleMetadataBtn = document.getElementById('toggle-metadata-btn');
    this.metadataChevron = document.getElementById('metadata-chevron');
    this.metadataControls = document.getElementById('metadata-controls');
    this.expandAllMetadataBtn = document.getElementById('expand-all-metadata-btn');
    this.collapseAllMetadataBtn = document.getElementById('collapse-all-metadata-btn');

    this.init();
  }

  init() {
    // Bind close button
    this.closeBtn.addEventListener('click', () => this.hide());

    // Bind metadata toggle
    this.toggleMetadataBtn.addEventListener('click', () => this.toggleMetadata());

    // Bind metadata control buttons
    this.expandAllMetadataBtn?.addEventListener('click', () => this.expandAllMetadata());
    this.collapseAllMetadataBtn?.addEventListener('click', () => this.collapseAllMetadata());
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
  }

  /**
   * Toggle metadata visibility
   */
  toggleMetadata() {
    const isHidden = this.metadataContent.classList.contains('hidden');
    if (isHidden) {
      this.metadataContent.classList.remove('hidden');
      this.metadataChevron.style.transform = 'rotate(180deg)';
      this.metadataControls.classList.remove('hidden');
    } else {
      this.metadataContent.classList.add('hidden');
      this.metadataChevron.style.transform = 'rotate(0deg)';
      this.metadataControls.classList.add('hidden');
    }
  }

  /**
   * Expand all metadata JSON nodes
   */
  expandAllMetadata() {
    const allDisclosures = this.metadataDisplay.querySelectorAll('.disclosure');
    allDisclosures.forEach(disclosure => {
      if (disclosure.textContent === '▶') {
        disclosure.click(); // Expand collapsed nodes
      }
    });
  }

  /**
   * Collapse all metadata JSON nodes
   */
  collapseAllMetadata() {
    const allDisclosures = this.metadataDisplay.querySelectorAll('.disclosure');
    allDisclosures.forEach(disclosure => {
      if (disclosure.textContent === '▼') {
        disclosure.click(); // Collapse expanded nodes
      }
    });
  }

  /**
   * Render session detail
   */
  render(sessionData) {
    this.emptyElement.classList.add('hidden');
    this.loadingElement.classList.add('hidden');
    this.detailContainer.classList.remove('hidden');

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
    this.renderTimeline(sessionData.timeline);
  }

  /**
   * Render timeline items
   */
  renderTimeline(timeline) {
    this.timelineContainer.innerHTML = '';

    if (!timeline || timeline.length === 0) {
      this.timelineContainer.innerHTML = '<p class="text-sm text-gray-500 text-center py-4">Sin mensajes</p>';
      return;
    }

    timeline.forEach(item => {
      let element;

      if (item.type === 'message') {
        element = Components.renderTimelineMessage(item);
      } else if (item.type === 'feedback') {
        element = Components.renderTimelineFeedback(item);
      }

      if (element) {
        this.timelineContainer.appendChild(element);
      }
    });

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
  constructor() {
    this.apiClient = new APIClient();
    this.currentFilters = null;

    this.init();
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

    // Load metadata fields
    await this.filterPanel.loadMetadataFields(this.apiClient);

    // Check URL parameters for direct session loading
    this.checkURLParameters();
  }

  /**
   * Check URL parameters and load session if session_id is present
   */
  checkURLParameters() {
    const urlParams = new URLSearchParams(window.location.search);
    const sessionId = urlParams.get('session_id');

    if (sessionId) {
      console.log(`Loading session from URL parameter: ${sessionId}`);
      // Load the session directly
      this.handleSessionSelect(sessionId);
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
      const sessionData = await this.apiClient.getSessionDetail(sessionId);
      this.sessionDetail.render(sessionData);
    } catch (error) {
      console.error('Error loading session:', error);
      alert('Error al cargar la sesión. Por favor, intenta de nuevo.');
      this.sessionDetail.hide();
    }
  }
}

// Application will be initialized from index.html
