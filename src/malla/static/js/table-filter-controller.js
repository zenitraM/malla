/*
 * TableFilterController – encapsulates the reactive link between:
 *  • sidebar form controls (filters)
 *  • URLFilterManager (URL sync)
 *  • ModernTable instance (data reloads)
 *  • Stats updater supplied by the page
 *
 * Requires createFilterStore (filter-store.js) to be loaded first.
 */
(function (global) {
    "use strict";

    if (!global.createFilterStore) {
        console.error("TableFilterController requires filter-store.js to be loaded first");
        return;
    }

    function debounce(fn, delay) {
        let t;
        return (...args) => {
            clearTimeout(t);
            t = setTimeout(() => fn.apply(this, args), delay);
        };
    }

    class TableFilterController {
        constructor(options) {
            const {
                table,
                urlManager,
                formSelector = '#filtersForm',
                groupingCheckboxSelector = '#group_packets',
                getDynamicColumns = null,
                updateStats = () => {},
                debounceDelay = 150,
            } = options;

            this.table = table;
            this.urlManager = urlManager;
            this.form = document.querySelector(formSelector);
            this.groupingCheckbox = document.querySelector(groupingCheckboxSelector);
            this.getDynamicColumns = getDynamicColumns;
            this.updateStats = updateStats;
            this.debounceDelay = debounceDelay;

            this.filterStore = global.createFilterStore({});
            this.lastAppliedJson = null;
            this.subscriberActive = false;

            this._bindFormFields();
            this._subscribe();
        }

        /* public ------------------------------------------------------------------ */

        /**
         * Apply current filters manually (useful for buttons, testing, etc.)
         */
        applyCurrentFilters() {
            // Sync form values to store first (for backward compatibility with tests)
            this._syncFormToStore();

            const filters = this.urlManager.getCurrentFilters();
            this.table.setFilters(filters);
            this.updateStats();
            this.urlManager.updateURL(filters);
        }

        clearFilters() {
            if (this.form) this.form.reset();
            if (this.groupingCheckbox) this.groupingCheckbox.checked = true;
            Object.keys(this.filterStore.state).forEach((k) => {
                this.filterStore.state[k] = '';
            });
            this.urlManager.clearFilters();
            this.table.clearFilters();
            this.updateStats();
        }

        /** Call after URL parameters are applied so we know whether to load unfiltered data. */
        initialLoad(hasParams) {
            if (hasParams) {
                // Sync current form state to store and capture it as "already applied"
                this._syncFormToStore();
                const filters = this.urlManager.getCurrentFilters();
                const cleaned = this._cleanFilters(filters);

                // Include grouping checkbox state in the filters for comparison
                if (this.groupingCheckbox) {
                    cleaned.group_packets = this.groupingCheckbox.checked;
                }

                this.lastAppliedJson = JSON.stringify(cleaned);

                // Apply filters once manually
                this.table.setFilters(cleaned);
                this.updateStats();

                // Now activate reactive mode
                this.subscriberActive = true;
            } else {
                // No filters: load once, then activate reactive mode.
                if (this.table.options.deferInitialLoad) {
                    this.table.loadData();
                }
                this.lastAppliedJson = JSON.stringify({});
                this.subscriberActive = true;
            }
        }

        /* private ----------------------------------------------------------------- */

        _bindFormFields() {
            if (!this.form) return;
            const inputs = this.form.querySelectorAll('input, select');
            inputs.forEach((input) => {
                const key = input.name;
                if (!key) return;

                // set initial state
                if (input.type === 'checkbox') {
                    this.filterStore.state[key] = input.checked;
                } else {
                    this.filterStore.state[key] = input.value;
                }

                const evt = (input.type === 'checkbox' || input.tagName === 'SELECT') ? 'change' : 'input';
                const handler = () => {
                    const val = input.type === 'checkbox' ? input.checked : input.value;
                    this.filterStore.state[key] = val;
                };
                input.addEventListener(evt, input.type === 'text' ? debounce(handler, this.debounceDelay) : handler);
            });
        }

        _cleanFilters(obj) {
            return Object.fromEntries(
                Object.entries(obj).filter(([_, v]) => {
                    if (typeof v === 'boolean') return v; // keep true booleans
                    return v !== undefined && v !== null && v !== '';
                })
            );
        }

        _subscribe() {
            this.filterStore.subscribe(
                debounce((current) => {
                    if (!this.subscriberActive) return;

                    // Update columns if function provided and packet type changed
                    if (this.getDynamicColumns && current.portnum !== this._lastPortnum) {
                        this._lastPortnum = current.portnum;
                        const cols = this.getDynamicColumns();
                        this.table.options.columns = cols;
                        this.table.updateTableHeader();
                    }

                    const cleaned = this._cleanFilters(current);

                    // Include grouping checkbox state in the filters for comparison
                    if (this.groupingCheckbox) {
                        cleaned.group_packets = this.groupingCheckbox.checked;
                    }

                    const cleanedJson = JSON.stringify(cleaned);
                    if (cleanedJson === this.lastAppliedJson) return;

                    this.table.setFilters(cleaned);
                    this.lastAppliedJson = cleanedJson;

                    this.updateStats();
                    this.urlManager.updateURL(cleaned);
                }, this.debounceDelay)
            );
        }

        _syncFormToStore() {
            if (!this.form) return;
            const inputs = this.form.querySelectorAll('input, select');
            inputs.forEach((input) => {
                const key = input.name;
                if (!key) return;

                // Sync form values to store
                if (input.type === 'checkbox') {
                    this.filterStore.state[key] = input.checked;
                } else {
                    this.filterStore.state[key] = input.value;
                }
            });
        }
    }

    global.TableFilterController = TableFilterController;
})(typeof window !== 'undefined' ? window : this);
