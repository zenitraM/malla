/**
 * Modern Table Implementation using HTMX and TanStack Table concepts
 * Replaces DataTables with a more modern, lightweight solution
 */

class ModernTable {
    constructor(containerId, options = {}) {
        this.container = document.getElementById(containerId);
        this.options = {
            endpoint: options.endpoint,
            pageSize: options.pageSize || 100,
            searchDelay: options.searchDelay || 300,
            enableSearch: options.enableSearch !== false,
            enablePagination: options.enablePagination !== false,
            enableSorting: options.enableSorting !== false,
            deferInitialLoad: options.deferInitialLoad || false,
            columns: options.columns || [],
            filters: options.filters || {},
            ...options
        };

        this.state = {
            page: 1,
            pageSize: this.options.pageSize,
            sortBy: null,
            sortOrder: 'desc',
            search: '',
            filters: { ...this.options.filters },
            loading: false,
            data: [],
            totalCount: 0,
            totalPages: 0
        };

        this.searchTimeout = null;
        this.eventListeners = {}; // Add event listener support
        this.init();
    }

    init() {
        this.setupContainer();
        this.setupEventListeners();
        if (!this.options.deferInitialLoad) {
            this.loadData();
        }
    }

    setupContainer() {
        this.container.innerHTML = `
            <div class="modern-table-container">
                ${this.options.enableSearch ? this.renderSearchBar() : ''}
                <div class="table-wrapper">
                    <table class="modern-table">
                        <thead>
                            ${this.renderTableHeader()}
                        </thead>
                        <tbody id="${this.container.id}-tbody">
                            ${this.renderLoadingState()}
                        </tbody>
                    </table>
                </div>
                ${this.options.enablePagination ? this.renderPagination() : ''}
            </div>
        `;
    }

    renderSearchBar() {
        return `
            <div class="table-search-bar" style="padding: 1rem 1.5rem; border-bottom: 1px solid #e5e7eb;">
                <div class="row align-items-center">
                    <div class="col-md-6">
                        <div class="input-group">
                            <span class="input-group-text">
                                <i class="bi bi-search"></i>
                            </span>
                            <input type="text"
                                   class="form-control"
                                   placeholder="Search..."
                                   id="${this.container.id}-search">
                        </div>
                    </div>
                    <div class="col-md-6 text-end">
                        <div class="page-size-selector">
                            <label for="${this.container.id}-pagesize">Show:</label>
                            <select id="${this.container.id}-pagesize" class="form-select form-select-sm" style="width: auto; display: inline-block;">
                                <option value="10" ${this.state.pageSize === 10 ? 'selected' : ''}>10</option>
                                <option value="25" ${this.state.pageSize === 25 ? 'selected' : ''}>25</option>
                                <option value="50" ${this.state.pageSize === 50 ? 'selected' : ''}>50</option>
                                <option value="100" ${this.state.pageSize === 100 ? 'selected' : ''}>100</option>
                            </select>
                        </div>
                    </div>
                </div>
            </div>
        `;
    }

    renderTableHeader() {
        return `
            <tr>
                ${this.options.columns.map(column => {
                    const sortable = column.sortable !== false;
                    const sortKey = column.sortKey || column.key;
                    const isSorted = this.state.sortBy === sortKey;

                    // Use proper CSS classes for ::after pseudo-element
                    let sortClass = sortable ? 'sortable' : '';
                    if (isSorted) {
                        sortClass += ` ${this.state.sortOrder}`;
                    }

                    return `
                        <th class="${sortClass}"
                            ${sortable ? `data-sort="${sortKey}"` : ''}>
                            ${column.title}
                        </th>
                    `;
                }).join('')}
            </tr>
        `;
    }

    renderLoadingState() {
        return `
            <tr>
                <td colspan="${this.options.columns.length}" class="text-center py-4">
                    <div class="loading-spinner mx-auto"></div>
                    <div class="mt-2 text-muted">Loading...</div>
                </td>
            </tr>
        `;
    }

    renderEmptyState() {
        return `
            <tr>
                <td colspan="${this.options.columns.length}">
                    <div class="empty-state">
                        <div class="empty-state-icon">
                            <i class="bi bi-inbox"></i>
                        </div>
                        <div class="empty-state-title">No data found</div>
                        <div class="empty-state-description">
                            ${this.state.search ? 'Try adjusting your search terms' : 'No records match your current filters'}
                        </div>
                    </div>
                </td>
            </tr>
        `;
    }

    renderPagination() {
        return `
            <div class="modern-pagination">
                <div class="pagination-info">
                    Showing <span id="${this.container.id}-start">0</span> to <span id="${this.container.id}-end">0</span>
                    of <span id="${this.container.id}-total">0</span> entries
                </div>
                <div class="pagination-controls" id="${this.container.id}-pagination">
                    <!-- Pagination buttons will be rendered here -->
                </div>
            </div>
        `;
    }

    setupEventListeners() {
        // Search functionality
        if (this.options.enableSearch) {
            const searchInput = document.getElementById(`${this.container.id}-search`);
            if (searchInput) {
                searchInput.addEventListener('input', (e) => {
                    clearTimeout(this.searchTimeout);
                    this.searchTimeout = setTimeout(() => {
                        this.state.search = e.target.value;
                        this.state.page = 1;
                        this.loadData();
                    }, this.options.searchDelay);
                });
            }

            // Page size selector
            const pageSizeSelect = document.getElementById(`${this.container.id}-pagesize`);
            if (pageSizeSelect) {
                pageSizeSelect.addEventListener('change', (e) => {
                    this.state.pageSize = parseInt(e.target.value);
                    this.state.page = 1;
                    this.loadData();
                });
            }
        }

        // Add sorting event listeners
        if (this.options.enableSorting) {
            this.container.addEventListener('click', (e) => {
                const th = e.target.closest('th[data-sort]');
                if (th) {
                    const sortBy = th.dataset.sort;
                    if (this.state.sortBy === sortBy) {
                        this.state.sortOrder = this.state.sortOrder === 'asc' ? 'desc' : 'asc';
                    } else {
                        this.state.sortBy = sortBy;
                        this.state.sortOrder = 'desc';
                    }
                    this.updateTableHeader();
                    this.loadData();
                }
            });
        }
    }

    updateTableHeader() {
        const thead = this.container.querySelector('thead');
        thead.innerHTML = this.renderTableHeader();
    }

    async loadData() {
        if (this.state.loading) return;

        this.state.loading = true;
        this.showLoading();

        try {
            const params = new URLSearchParams({
                page: this.state.page,
                limit: this.state.pageSize,
                search: this.state.search,
                ...(this.state.sortBy && { sort_by: this.state.sortBy }),
                ...(this.state.sortBy && { sort_order: this.state.sortOrder }),
                ...this.state.filters
            });

            // Add grouping parameter - prefer filter value over DOM check to avoid race conditions
            if ('group_packets' in this.state.filters) {
                // Use the filter value when available (from reactive updates)
                params.set('group_packets', this.state.filters.group_packets.toString());
            } else {
                // Fall back to DOM check for backward compatibility
                const groupingCheckbox = document.getElementById('groupPackets') ||
                                       document.getElementById('groupTraceroutes') ||
                                       document.getElementById('group_packets');
                if (groupingCheckbox && groupingCheckbox.checked) {
                    params.set('group_packets', 'true');
                }
            }

            const response = await fetch(`${this.options.endpoint}?${params}`);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}: ${response.statusText}`);
            }

            const data = await response.json();
            this.state.data = data.data || [];
            this.state.totalCount = data.total_count || 0;
            this.state.totalPages = Math.ceil(this.state.totalCount / this.state.pageSize);

            // Track if this is a grouped query for pagination display
            this.state.isGrouped = params.get('group_packets') === 'true';

            this.renderTableBody();
            this.updatePagination();

            this.emit('dataLoaded', { data: this.state.data, totalCount: this.state.totalCount });

        } catch (error) {
            console.error('Error loading table data:', error);
            this.showError(error.message);
        } finally {
            this.state.loading = false;
        }
    }

    showLoading() {
        const tbody = document.getElementById(`${this.container.id}-tbody`);
        tbody.innerHTML = this.renderLoadingState();
    }

    showError(message) {
        const tbody = document.getElementById(`${this.container.id}-tbody`);
        tbody.innerHTML = `
            <tr>
                <td colspan="${this.options.columns.length}" class="text-center py-4 text-danger">
                    <i class="bi bi-exclamation-triangle fs-1 mb-2"></i>
                    <div>Error loading data: ${message}</div>
                </td>
            </tr>
        `;
    }

    renderTableBody() {
        const tbody = document.getElementById(`${this.container.id}-tbody`);

        if (this.state.data.length === 0) {
            tbody.innerHTML = this.renderEmptyState();
            return;
        }

        tbody.innerHTML = this.state.data.map(row => `
            <tr>
                ${this.options.columns.map(column => `
                    <td>${this.renderCell(row, column)}</td>
                `).join('')}
            </tr>
        `).join('');

        // Re-initialize tooltips and other interactive elements
        if (window.reinitializeTooltips) {
            window.reinitializeTooltips();
        }
    }

    renderCell(row, column) {
        const value = this.getNestedValue(row, column.key);

        if (column.render && typeof column.render === 'function') {
            return column.render(value, row);
        }

        if (column.type === 'badge') {
            return this.renderBadge(value, column.badgeMap);
        }

        if (column.type === 'signal') {
            return this.renderSignalIndicator(value, column.unit);
        }

        if (column.type === 'actions') {
            return this.renderActions(row, column.actions);
        }

        if (column.type === 'link') {
            return `<a href="${column.linkTemplate.replace('{id}', row.id)}" class="text-decoration-none">${value || 'Unknown'}</a>`;
        }

        return value || '';
    }

    getNestedValue(obj, path) {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }

    renderBadge(value, badgeMap = {}) {
        const badgeClass = badgeMap[value] || 'modern-badge-secondary';
        return `<span class="modern-badge ${badgeClass}">${value}</span>`;
    }

    renderSignalIndicator(value, unit = '') {
        if (value === null || value === undefined || value === '') {
            return '<span class="text-muted">N/A</span>';
        }

        const numValue = parseFloat(value);
        let className = 'signal-poor';

        if (unit === 'dBm') {
            if (numValue >= -60) className = 'signal-excellent';
            else if (numValue >= -70) className = 'signal-good';
            else if (numValue >= -80) className = 'signal-fair';
        } else if (unit === 'dB') {
            if (numValue > 5) className = 'signal-excellent';
            else if (numValue > 0) className = 'signal-good';
            else if (numValue > -5) className = 'signal-fair';
        }

        return `<span class="${className}">${value}${unit ? ' ' + unit : ''}</span>`;
    }

    renderActions(row, actions = []) {
        return `
            <div class="action-buttons">
                ${actions.map(action => `
                    <a href="${action.url.replace('{id}', row.id)}"
                       class="action-btn ${action.class || ''}"
                       title="${action.title || ''}">
                        <i class="bi bi-${action.icon}"></i>
                    </a>
                `).join('')}
            </div>
        `;
    }

    updatePagination() {
        if (!this.options.enablePagination) return;

        // Update info
        const start = (this.state.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.page * this.state.pageSize, this.state.totalCount);

        document.getElementById(`${this.container.id}-start`).textContent = this.state.totalCount > 0 ? start : 0;
        document.getElementById(`${this.container.id}-end`).textContent = end;

        // Handle estimated counts for grouped queries
        const totalElement = document.getElementById(`${this.container.id}-total`);
        if (this.state.isGrouped && this.state.data.length === this.state.pageSize) {
            // For grouped queries where we got a full page, show estimated count
            totalElement.textContent = `${this.state.totalCount}+`;
            totalElement.title = 'Estimated count (optimized for performance)';
        } else {
            totalElement.textContent = this.state.totalCount;
            totalElement.title = '';
        }

        // Update pagination controls
        const paginationContainer = document.getElementById(`${this.container.id}-pagination`);
        paginationContainer.innerHTML = this.renderPaginationButtons();

        // Add event listeners to pagination buttons
        paginationContainer.addEventListener('click', (e) => {
            const button = e.target.closest('.pagination-btn');
            if (button && !button.disabled) {
                const page = parseInt(button.dataset.page);
                if (page && page !== this.state.page) {
                    this.state.page = page;
                    this.loadData();
                }
            }
        });
    }

    renderPaginationButtons() {
        const { page, totalPages } = this.state;
        const buttons = [];

        // Previous button
        buttons.push(`
            <button class="pagination-btn"
                    data-page="${page - 1}"
                    ${page <= 1 ? 'disabled' : ''}>
                <i class="bi bi-chevron-left"></i> Previous
            </button>
        `);

        // For grouped queries with estimated counts, limit pagination display
        if (this.state.isGrouped && this.state.data.length === this.state.pageSize) {
            // Show current page and next few pages only
            const maxDisplayPages = Math.min(totalPages, page + 5);

            for (let i = Math.max(1, page - 2); i <= Math.min(maxDisplayPages, page + 2); i++) {
                buttons.push(`
                    <button class="pagination-btn ${i === page ? 'active' : ''}"
                            data-page="${i}">
                        ${i}
                    </button>
                `);
            }

            if (page < maxDisplayPages) {
                buttons.push(`<span class="pagination-ellipsis">...</span>`);
            }
        } else {
            // Standard pagination for exact counts
            const startPage = Math.max(1, page - 2);
            const endPage = Math.min(totalPages, page + 2);

            if (startPage > 1) {
                buttons.push(`<button class="pagination-btn" data-page="1">1</button>`);
                if (startPage > 2) {
                    buttons.push(`<span class="pagination-ellipsis">...</span>`);
                }
            }

            for (let i = startPage; i <= endPage; i++) {
                buttons.push(`
                    <button class="pagination-btn ${i === page ? 'active' : ''}"
                            data-page="${i}">
                        ${i}
                    </button>
                `);
            }

            if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                    buttons.push(`<span class="pagination-ellipsis">...</span>`);
                }
                buttons.push(`<button class="pagination-btn" data-page="${totalPages}">${totalPages}</button>`);
            }
        }

        // Next button - for grouped queries, only disable if we got less than a full page
        const hasNextPage = this.state.isGrouped ?
            this.state.data.length === this.state.pageSize :
            page < totalPages;

        buttons.push(`
            <button class="pagination-btn"
                    data-page="${page + 1}"
                    ${!hasNextPage ? 'disabled' : ''}>
                Next <i class="bi bi-chevron-right"></i>
            </button>
        `);

        return buttons.join('');
    }

    // Public methods for external control
    setFilters(filters) {
        this.state.filters = filters;
        this.state.page = 1;
        this.loadData();
    }

    clearFilters() {
        this.state.filters = {};
        this.state.page = 1;
        this.loadData();
    }

    refresh() {
        this.loadData();
    }

    updateColumns(newColumns) {
        this.options.columns = newColumns;
        this.updateTableHeader();
        // Re-render the table body with the new columns
        this.renderTableBody();
    }

    setPage(page) {
        if (page >= 1 && page <= this.state.totalPages) {
            this.state.page = page;
            this.loadData();
        }
    }

    setPageSize(pageSize) {
        this.state.pageSize = pageSize;
        this.state.page = 1;
        this.loadData();
    }

    setSearch(search) {
        this.state.search = search;
        this.state.page = 1;
        const searchInput = document.getElementById(`${this.container.id}-search`);
        if (searchInput) {
            searchInput.value = search;
        }
        this.loadData();
    }

    // Add event listener support
    on(event, callback) {
        if (!this.eventListeners[event]) {
            this.eventListeners[event] = [];
        }
        this.eventListeners[event].push(callback);
    }

    // Emit events
    emit(event, data) {
        if (this.eventListeners[event]) {
            this.eventListeners[event].forEach(callback => callback(data));
        }
    }
}

// Export for use in other scripts
window.ModernTable = ModernTable;
