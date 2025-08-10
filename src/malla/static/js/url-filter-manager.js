/**
 * URL Filter Manager - Reusable utility for managing URL parameters and filters
 * Handles URL parameter parsing, updating, and form population across table views
 */
class URLFilterManager {
    constructor(options = {}) {
        this.options = {
            formSelector: '#filtersForm',
            groupingSelector: '#group_packets',
            ...options
        };

        this.form = document.querySelector(this.options.formSelector);
        this.groupingCheckbox = document.querySelector(this.options.groupingSelector);
    }

    /**
     * Get all URL parameters as an object
     */
    getParams() {
        const params = new URLSearchParams(window.location.search);
        const result = {};
        for (let [key, value] of params.entries()) {
            if (value.trim()) {
                result[key] = value;
            }
        }
        return result;
    }

    /**
     * Update URL with new parameters without page reload
     */
    updateURL(filters) {
        const url = new URL(window.location);
        url.search = ''; // Clear existing params

        // Add non-empty filters to URL
        Object.entries(filters).forEach(([key, value]) => {
            if (value && value.toString().trim()) {
                url.searchParams.set(key, value);
            }
        });

        // Update URL without page reload
        window.history.replaceState({}, '', url);
    }

    /**
     * Apply URL parameters to form fields
     */
    async applyURLParameters() {
        const urlParams = this.getParams();

        if (Object.keys(urlParams).length === 0) {
            return false; // No parameters to apply
        }

        // Apply simple form field values
        Object.entries(urlParams).forEach(([key, value]) => {
            if (key === 'group_packets') {
                if (this.groupingCheckbox) {
                    this.groupingCheckbox.checked = value === 'true';
                }
            } else {
                const field = this.form?.querySelector(`[name="${key}"]`);
                if (field) {
                    // Special handling for checkboxes
                    if (field.type === 'checkbox') {
                        field.checked = (value === 'true' || value === '1' || value === 'on');
                    } else {
                        field.value = value;
                    }

                    // Trigger change event for inputs that listeners may rely on
                    if (field.tagName === 'SELECT' || field.type === 'checkbox') {
                        field.dispatchEvent(new Event('change', { bubbles: true }));
                    }
                }
            }
        });

        // Handle special picker fields
        const nodePickerFields = ['from_node', 'to_node', 'route_node', 'exclude_from', 'exclude_to'];
        for (const fieldName of nodePickerFields) {
            const nodeId = urlParams[fieldName];
            if (nodeId) {
                await this.setNodePickerValue(fieldName, nodeId);
            }
        }

        // Handle gateway picker
        const gatewayId = urlParams['gateway_id'];
        if (gatewayId) {
            await this.setGatewayPickerValue('gateway_id', gatewayId);
        }

        return true; // Parameters were applied
    }

    /**
     * Set node picker value by node ID
     */
    async setNodePickerValue(fieldName, nodeId) {
        try {
            let displayName = `Node ${nodeId}`; // Default fallback

            // Try to fetch node info to get display name
            try {
                const response = await fetch(`/api/node/${nodeId}/info`);
                if (response.ok) {
                    const data = await response.json();
                    const node = data.node || data;
                    displayName = node.long_name || node.short_name || node.hex_id || `Node ${nodeId}`;
                }
                // If response is not ok, we'll use the fallback display name
            } catch (fetchError) {
                console.warn(`Could not fetch node info for ${nodeId}, using fallback display name`);
            }

            // Set the picker value (try multiple selector patterns)
            const hiddenField = document.querySelector(`input[name="${fieldName}"]`);
            const visibleField = document.querySelector(`#${fieldName}`) ||
                               document.querySelector(`input[data-field="${fieldName}"]`) ||
                               document.querySelector(`.node-picker-input[data-field="${fieldName}"]`);

            if (hiddenField && visibleField) {
                hiddenField.value = nodeId;
                visibleField.value = displayName;

                // Trigger change events for any listeners
                hiddenField.dispatchEvent(new Event('change', { bubbles: true }));
                visibleField.dispatchEvent(new Event('change', { bubbles: true }));
            }
        } catch (error) {
            console.error(`Error setting node picker value for ${fieldName}:`, error);
        }
    }

    /**
     * Set gateway picker value by gateway ID
     */
    async setGatewayPickerValue(fieldName, gatewayId) {
        try {
            // Normalise: convert !hex to decimal string if applicable
            let nodeId = gatewayId;
            if (typeof gatewayId === 'string' && gatewayId.startsWith('!')) {
                try {
                    nodeId = parseInt(gatewayId.substring(1), 16).toString();
                } catch (_) {
                    // keep original if conversion fails
                    nodeId = gatewayId;
                }
            }

            let displayName = gatewayId;

            // Attempt to get node info from NodeCache first (fast, no network)
            if (window.NodeCache && typeof window.NodeCache.getNode === 'function') {
                try {
                    const node = await window.NodeCache.getNode(nodeId);
                    if (node) {
                        displayName = node.long_name || node.short_name || `!${parseInt(node.node_id).toString(16).padStart(8, '0')}`;
                    }
                } catch (_) { /* ignore */ }
            }

            // Fallback: call /api/node/<id>/info for more accurate name
            if (displayName === gatewayId) {
                try {
                    const resp = await fetch(`/api/node/${nodeId}/info`);
                    if (resp.ok) {
                        const data = await resp.json();
                        const node = data.node || data;
                        displayName = node.long_name || node.short_name || node.hex_id || gatewayId;
                    }
                } catch (_) { /* ignore */ }
            }

            // Final fallback: attempt /api/gateways/search (handles non-node gateways)
            if (displayName === gatewayId) {
                try {
                    const response = await fetch(`/api/gateways/search?q=${encodeURIComponent(gatewayId)}&limit=1`);
                    if (response.ok) {
                        const data = await response.json();
                        if (data.gateways && data.gateways.length) {
                            const gw = data.gateways[0];
                            displayName = gw.display_name || gw.name || gw.gateway_id || gatewayId;
                        }
                    }
                } catch (_) { /* ignore */ }
            }

            // Set the picker value (try multiple selector patterns)
            const hiddenField = document.querySelector(`input[name="${fieldName}"]`);
            const visibleField = document.querySelector(`#${fieldName}`) ||
                               document.querySelector(`input[data-field="${fieldName}"]`) ||
                               document.querySelector(`.gateway-picker-input[data-field="${fieldName}"]`);

            if (hiddenField && visibleField) {
                hiddenField.value = nodeId;
                visibleField.value = displayName;

                // Trigger change events for any listeners
                hiddenField.dispatchEvent(new Event('change', { bubbles: true }));
                visibleField.dispatchEvent(new Event('change', { bubbles: true }));
            }
        } catch (error) {
            console.error(`Error setting gateway picker value for ${fieldName}:`, error);
        }
    }

    /**
     * Get current filter values from form
     */
    getCurrentFilters() {
        if (!this.form) return {};

        const filters = {};

        // Get all form inputs including unchecked checkboxes
        const inputs = this.form.querySelectorAll('input, select, textarea');
        inputs.forEach(input => {
            const key = input.name;
            if (!key) return;

            if (input.type === 'checkbox') {
                // Include checkbox state (true/false)
                filters[key] = input.checked;
            } else if (input.value && input.value.trim()) {
                // Include non-empty text/select values
                filters[key] = input.value;
            }
        });

        // Add grouping parameter if checkbox exists
        if (this.groupingCheckbox) {
            filters.group_packets = this.groupingCheckbox.checked;
        }

        return filters;
    }

    /**
     * Clear all form fields and URL parameters
     */
    clearFilters() {
        if (this.form) {
            this.form.reset();
        }

        if (this.groupingCheckbox) {
            this.groupingCheckbox.checked = true;
        }

        // Clear picker values using multiple selector patterns
        const pickerInputs = document.querySelectorAll('.node-picker-input, .gateway-picker-input');
        pickerInputs.forEach(input => {
            input.value = '';
        });

        const hiddenInputs = document.querySelectorAll('input[name="from_node"], input[name="to_node"], input[name="route_node"], input[name="gateway_id"], input[name="exclude_from"], input[name="exclude_to"]');
        hiddenInputs.forEach(input => {
            input.value = '';
        });

        // Clear URL parameters
        this.updateURL({});
    }

    /**
     * Create a URL with filters for linking to filtered views
     */
    createFilteredURL(baseUrl, filters) {
        const url = new URL(baseUrl, window.location.origin);

        Object.entries(filters).forEach(([key, value]) => {
            if (value && value.toString().trim()) {
                url.searchParams.set(key, value);
            }
        });

        return url.toString();
    }
}

// Make URLFilterManager available globally
window.URLFilterManager = URLFilterManager;
