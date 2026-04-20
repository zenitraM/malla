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
            totalPages: 0,
            isGrouped: false
        };

        this.searchTimeout = null;
        this.eventListeners = {};
        this.paginationClickHandler = null;
        this.init();
    }

    init() {
        this.setupContainer();
        this.setupEventListeners();

        window.modernTableInstances = window.modernTableInstances || [];
        window.modernTableInstances.push(this);

        if (!this.options.deferInitialLoad) {
            this.loadData();
        }
    }

    setupContainer() {
        this.container.replaceChildren(
            el('div', { className: 'modern-table-container' },
                this.options.enableSearch ? this.buildSearchBar() : null,
                el('div', { className: 'table-wrapper' },
                    el('table', { className: 'modern-table' },
                        el('thead'),
                        el('tbody', { id: `${this.container.id}-tbody` })
                    )
                ),
                this.options.enablePagination ? this.buildPaginationShell() : null
            )
        );

        this.updateTableHeader();
        this.showLoading();
    }

    buildSearchBar() {
        const select = el('select', {
            id: `${this.container.id}-pagesize`,
            className: 'form-select form-select-sm',
            style: { width: 'auto', display: 'inline-block' }
        });

        [10, 25, 50, 100].forEach((size) => {
            select.appendChild(el('option', {
                value: String(size),
                selected: this.state.pageSize === size
            }, String(size)));
        });

        return el('div', {
            className: 'table-search-bar',
            style: { padding: '1rem 1.5rem', borderBottom: '1px solid #e5e7eb' }
        },
            el('div', { className: 'row align-items-center' },
                el('div', { className: 'col-md-6' },
                    el('div', { className: 'input-group' },
                        el('span', { className: 'input-group-text' }, icon('bi bi-search')),
                        el('input', {
                            type: 'text',
                            className: 'form-control',
                            placeholder: this.options.searchPlaceholder || 'Search...',
                            id: `${this.container.id}-search`
                        })
                    )
                ),
                el('div', { className: 'col-md-6 text-end' },
                    el('div', { className: 'page-size-selector' },
                        el('label', { htmlFor: `${this.container.id}-pagesize` }, 'Show:'),
                        textNode(' '),
                        select
                    )
                )
            )
        );
    }

    buildPaginationShell() {
        return el('div', { className: 'modern-pagination' },
            el('div', { className: 'pagination-info' },
                'Showing ',
                el('span', { id: `${this.container.id}-start` }, '0'),
                ' to ',
                el('span', { id: `${this.container.id}-end` }, '0'),
                ' of ',
                el('span', { id: `${this.container.id}-total` }, '0'),
                ' entries'
            ),
            el('div', { className: 'pagination-controls', id: `${this.container.id}-pagination` })
        );
    }

    buildHeaderRow() {
        return el('tr', null,
            this.options.columns.map((column) => {
                const sortable = column.sortable !== false;
                const sortKey = column.sortKey || column.key;
                const isSorted = this.state.sortBy === sortKey;
                let sortClass = sortable ? 'sortable' : '';
                if (isSorted) {
                    sortClass += ` ${this.state.sortOrder}`;
                }

                return el('th', {
                    className: sortClass,
                    ...(sortable ? { 'data-sort': sortKey } : {})
                }, column.title);
            })
        );
    }

    renderLoadingState() {
        return el('tr', null,
            el('td', {
                colspan: String(this.options.columns.length),
                className: 'text-center py-4'
            },
                el('div', { className: 'loading-spinner mx-auto' }),
                el('div', { className: 'mt-2 text-muted' }, 'Loading...')
            )
        );
    }

    renderEmptyState() {
        return el('tr', null,
            el('td', { colspan: String(this.options.columns.length) },
                el('div', { className: 'empty-state' },
                    el('div', { className: 'empty-state-icon' }, icon('bi bi-inbox')),
                    el('div', { className: 'empty-state-title' }, this.options.emptyMessage || 'No data found'),
                    el('div', { className: 'empty-state-description' },
                        this.state.search ? 'Try adjusting your search terms' : 'No records match your current filters'
                    )
                )
            )
        );
    }

    setupEventListeners() {
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

            const pageSizeSelect = document.getElementById(`${this.container.id}-pagesize`);
            if (pageSizeSelect) {
                pageSizeSelect.addEventListener('change', (e) => {
                    this.state.pageSize = parseInt(e.target.value, 10);
                    this.state.page = 1;
                    this.loadData();
                });
            }
        }

        if (this.options.enableSorting) {
            this.container.addEventListener('click', (e) => {
                const th = e.target.closest('th[data-sort]');
                if (!th) return;

                const sortBy = th.dataset.sort;
                if (this.state.sortBy === sortBy) {
                    this.state.sortOrder = this.state.sortOrder === 'asc' ? 'desc' : 'asc';
                } else {
                    this.state.sortBy = sortBy;
                    this.state.sortOrder = 'desc';
                }
                this.updateTableHeader();
                this.loadData();
            });
        }
    }

    updateTableHeader() {
        const thead = this.container.querySelector('thead');
        setChildren(thead, this.buildHeaderRow());
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

            if ('group_packets' in this.state.filters) {
                params.set('group_packets', this.state.filters.group_packets.toString());
            } else {
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
        setChildren(tbody, this.renderLoadingState());
    }

    showError(message) {
        const tbody = document.getElementById(`${this.container.id}-tbody`);
        setChildren(tbody,
            el('tr', null,
                el('td', {
                    colspan: String(this.options.columns.length),
                    className: 'text-center py-4 text-danger'
                },
                    icon('bi bi-exclamation-triangle fs-1 mb-2'),
                    el('div', null, `Error loading data: ${message}`)
                )
            )
        );
    }

    renderTableBody() {
        const tbody = document.getElementById(`${this.container.id}-tbody`);

        if (this.state.data.length === 0) {
            setChildren(tbody, this.renderEmptyState());
            return;
        }

        const rows = this.state.data.map((row) => el('tr', null,
            this.options.columns.map((column) => el('td', null, this.renderCell(row, column)))
        ));

        setChildren(tbody, rows);

        if (window.reinitializeTooltips) {
            window.reinitializeTooltips();
        }
    }

    renderCell(row, column) {
        const value = this.getNestedValue(row, column.key);

        if (column.render && typeof column.render === 'function') {
            const rendered = column.render(value, row);
            if (typeof rendered === 'string') {
                throw new Error(`ModernTable renderers must return DOM nodes, not strings (column: ${column.key})`);
            }
            return rendered == null ? textNode('') : rendered;
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
            return this.renderLink(value, row, column);
        }

        return textNode(value == null ? '' : String(value));
    }

    getNestedValue(obj, path) {
        return path.split('.').reduce((current, key) => current?.[key], obj);
    }

    renderLink(value, row, column) {
        const href = safePath(column.linkTemplate.replace('{id}', encodeURIComponent(String(row.id))));
        return el('a', { href, className: 'text-decoration-none' }, value || 'Unknown');
    }

    renderBadge(value, badgeMap = {}) {
        return el('span', {
            className: `modern-badge ${badgeMap[value] || 'modern-badge-secondary'}`
        }, value == null ? '' : String(value));
    }

    renderSignalIndicator(value, unit = '') {
        if (value === null || value === undefined || value === '') {
            return el('span', { className: 'text-muted' }, 'N/A');
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

        return el('span', { className }, `${value}${unit ? ` ${unit}` : ''}`);
    }

    renderActions(row, actions = []) {
        return el('div', { className: 'action-buttons' },
            actions.map((action) => el('a', {
                href: safePath(action.url.replace('{id}', encodeURIComponent(String(row.id)))),
                className: `action-btn ${action.class || ''}`.trim(),
                title: action.title || ''
            }, icon(`bi bi-${action.icon}`)))
        );
    }

    updatePagination() {
        if (!this.options.enablePagination) return;

        const start = (this.state.page - 1) * this.state.pageSize + 1;
        const end = Math.min(this.state.page * this.state.pageSize, this.state.totalCount);

        document.getElementById(`${this.container.id}-start`).textContent = this.state.totalCount > 0 ? start : 0;
        document.getElementById(`${this.container.id}-end`).textContent = end;

        const totalElement = document.getElementById(`${this.container.id}-total`);
        if (this.state.isGrouped && this.state.data.length === this.state.pageSize) {
            totalElement.textContent = `${this.state.totalCount}+`;
            totalElement.title = 'Estimated count (optimized for performance)';
        } else {
            totalElement.textContent = this.state.totalCount;
            totalElement.title = '';
        }

        const paginationContainer = document.getElementById(`${this.container.id}-pagination`);
        setChildren(paginationContainer, this.renderPaginationButtons());

        if (this.paginationClickHandler) {
            paginationContainer.removeEventListener('click', this.paginationClickHandler);
        }

        this.paginationClickHandler = (e) => {
            const button = e.target.closest('.pagination-btn');
            if (button && !button.disabled) {
                const page = parseInt(button.dataset.page, 10);
                if (page && page !== this.state.page) {
                    this.state.page = page;
                    this.loadData();
                }
            }
        };

        paginationContainer.addEventListener('click', this.paginationClickHandler);
    }

    renderPaginationButtons() {
        const { page, totalPages } = this.state;
        const nodes = [];

        nodes.push(el('button', {
            className: 'pagination-btn',
            dataset: { page: page - 1 },
            disabled: page <= 1
        }, icon('bi bi-chevron-left'), textNode(' Previous')));

        if (this.state.isGrouped && this.state.data.length === this.state.pageSize) {
            const maxDisplayPages = Math.min(totalPages, page + 5);
            for (let i = Math.max(1, page - 2); i <= Math.min(maxDisplayPages, page + 2); i++) {
                nodes.push(this.createPageButton(i, i === page));
            }
            if (page < maxDisplayPages) {
                nodes.push(el('span', { className: 'pagination-ellipsis' }, '...'));
            }
        } else {
            const startPage = Math.max(1, page - 2);
            const endPage = Math.min(totalPages, page + 2);

            if (startPage > 1) {
                nodes.push(this.createPageButton(1, false));
                if (startPage > 2) {
                    nodes.push(el('span', { className: 'pagination-ellipsis' }, '...'));
                }
            }

            for (let i = startPage; i <= endPage; i++) {
                nodes.push(this.createPageButton(i, i === page));
            }

            if (endPage < totalPages) {
                if (endPage < totalPages - 1) {
                    nodes.push(el('span', { className: 'pagination-ellipsis' }, '...'));
                }
                nodes.push(this.createPageButton(totalPages, false));
            }
        }

        const hasNextPage = this.state.isGrouped ?
            this.state.data.length === this.state.pageSize :
            page < totalPages;

        nodes.push(el('button', {
            className: 'pagination-btn',
            dataset: { page: page + 1 },
            disabled: !hasNextPage
        }, textNode('Next '), icon('bi bi-chevron-right')));

        return nodes;
    }

    createPageButton(pageNumber, active) {
        return el('button', {
            className: `pagination-btn${active ? ' active' : ''}`,
            dataset: { page: pageNumber }
        }, String(pageNumber));
    }

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

    on(event, callback) {
        if (!this.eventListeners[event]) {
            this.eventListeners[event] = [];
        }
        this.eventListeners[event].push(callback);
    }

    emit(event, data) {
        if (this.eventListeners[event]) {
            this.eventListeners[event].forEach((callback) => callback(data));
        }
    }
}

window.ModernTable = ModernTable;
