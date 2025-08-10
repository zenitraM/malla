/**
 * Node Picker Component
 * Provides searchable node selection with autocomplete functionality
 */

class NodePicker {
    constructor(container) {
        this.container = container;
        this.input = container.querySelector('.node-picker-input');
        this.hiddenInput = container.querySelector('input[type="hidden"]');
        this.clearButton = container.querySelector('.node-picker-clear');
        this.dropdown = container.querySelector('.node-picker-dropdown');
        this.loadingElement = container.querySelector('.node-picker-loading');
        this.noResultsElement = container.querySelector('.node-picker-no-results');
        this.resultsContainer = container.querySelector('.node-picker-results');

        // Check if this picker should include broadcast option
        this.includeBroadcast = container.dataset.includeBroadcast === 'true';

        this.searchTimeout = null;
        this.currentFocus = -1;
        this.nodes = [];
        this.isOpen = false;

        this.init();
    }

    init() {
        // Bind event listeners with explicit context
        this.input.addEventListener('input', (e) => this.handleInput(e));
        this.input.addEventListener('focus', (e) => this.handleFocus(e));
        this.input.addEventListener('blur', (e) => this.handleBlur(e));
        this.input.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.clearButton.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.clearSelection();
        });

        // Close dropdown when clicking outside - use capture phase for Firefox
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.closeDropdown();
            }
        }, true);
    }

    handleInput(e) {
        const query = e.target.value.trim();

        // Clear the search timeout
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        // If input is empty, clear selection
        if (!query) {
            this.clearSelection();
            this.closeDropdown();
            return;
        }

        // Debounce the search
        this.searchTimeout = setTimeout(() => {
            this.searchNodes(query);
        }, 300);
    }

    handleFocus(e) {
        const query = e.target.value.trim();
        if (query && this.nodes.length > 0) {
            this.openDropdown();
        } else if (!query) {
            // Show popular nodes when focusing on empty field
            this.searchNodes('');
        }
    }

    handleBlur(e) {
        // Delay closing to allow for clicks on dropdown items
        // Use longer delay for Firefox
        setTimeout(() => {
            if (!this.container.contains(document.activeElement)) {
                this.closeDropdown();
            }
        }, 200);
    }

    handleKeydown(e) {
        if (!this.isOpen) return;

        const items = this.dropdown.querySelectorAll('.node-picker-item');

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.currentFocus = Math.min(this.currentFocus + 1, items.length - 1);
                this.updateFocus(items);
                break;

            case 'ArrowUp':
                e.preventDefault();
                this.currentFocus = Math.max(this.currentFocus - 1, -1);
                this.updateFocus(items);
                break;

            case 'Enter':
                e.preventDefault();
                if (this.currentFocus >= 0 && items[this.currentFocus]) {
                    this.selectNode(items[this.currentFocus].dataset.nodeId);
                }
                break;

            case 'Escape':
                e.preventDefault();
                this.closeDropdown();
                this.input.blur();
                break;
        }
    }

    updateFocus(items) {
        items.forEach((item, index) => {
            if (index === this.currentFocus) {
                item.classList.add('keyboard-active');
            } else {
                item.classList.remove('keyboard-active');
            }
        });

        // Scroll focused item into view - Firefox-compatible version
        if (this.currentFocus >= 0 && items[this.currentFocus]) {
            const item = items[this.currentFocus];
            const container = this.dropdown;
            const itemTop = item.offsetTop;
            const itemBottom = itemTop + item.offsetHeight;
            const containerTop = container.scrollTop;
            const containerBottom = containerTop + container.clientHeight;

            if (itemTop < containerTop) {
                container.scrollTop = itemTop;
            } else if (itemBottom > containerBottom) {
                container.scrollTop = itemBottom - container.clientHeight;
            }
        }
    }

    async searchNodes(query) {
        this.showLoading();
        this.openDropdown();

        try {
            // Ensure the global node list is loaded (from cache or API)
            await window.NodeCache.load();

            if (!query) {
                // Show popular nodes (top by packets) when query is empty
                this.nodes = await window.NodeCache.topByPackets(20);
                this.isPopular = true;
            } else {
                // Client-side search
                this.nodes = await window.NodeCache.search(query, 20);
                this.isPopular = false;
            }

            // Add broadcast node if this picker includes it
            if (this.includeBroadcast) {
                const broadcastNode = {
                    node_id: 4294967295,
                    long_name: "Broadcast",
                    short_name: "Broadcast",
                    hw_model: "Special",
                    role: "Broadcast",
                    hex_id: "!ffffffff",
                    packet_count_24h: 0
                };

                if (!query) {
                    // Add broadcast at the top for easy access when no query
                    this.nodes = [broadcastNode, ...this.nodes];
                } else {
                    // Check if query matches broadcast node
                    const queryLower = query.toLowerCase();
                    const matchesBroadcast = 
                        "broadcast".includes(queryLower) ||
                        "ffffffff".includes(queryLower) ||
                        "!ffffffff".includes(queryLower) ||
                        "4294967295".includes(query);
                    
                    if (matchesBroadcast) {
                        this.nodes = [broadcastNode, ...this.nodes];
                    }
                }
            }

            this.renderResults();
        } catch (error) {
            console.error('Error searching nodes:', error);
            this.showNoResults();
        }
    }

    filterNodes(nodes, query) {
        const lowerQuery = query.toLowerCase();

        return nodes.filter(node => {
            const name = (node.long_name || node.short_name || '').toLowerCase();
            const hexId = `!${node.node_id.toString(16).padStart(8, '0')}`.toLowerCase();
            const nodeIdStr = node.node_id.toString();

            return name.includes(lowerQuery) ||
                   hexId.includes(lowerQuery) ||
                   nodeIdStr.includes(lowerQuery);
        }).slice(0, 20); // Limit results
    }

    renderResults() {
        this.hideLoading();
        this.hideNoResults();

        if (this.nodes.length === 0) {
            this.showNoResults();
            return;
        }

        const html = this.nodes.map(node => {
            const longName = node.long_name || null;
            const shortName = node.short_name || null;
            let displayName = longName || shortName || 'Unnamed';
            // If both names present and different, append short in parentheses
            if (longName && shortName && longName !== shortName) {
                displayName = `${longName} (${shortName})`;
            }

            const hexId = `!${node.node_id.toString(16).padStart(8, '0')}`;
            const details = [];

            if (node.hw_model) {
                details.push(node.hw_model);
            }

            if (node.packet_count_24h !== undefined) {
                details.push(`${node.packet_count_24h} packets/24h`);
            } else if (this.isPopular) {
                details.push('Popular Node');
            }

            // Escape HTML attributes for Firefox compatibility
            const escapedDisplayName = this.escapeHtml(displayName);
            const escapedShortName = this.escapeHtml(shortName || '');
            const escapedNodeId = this.escapeHtml(node.node_id.toString());

            return `
                <div class="node-picker-item" data-node-id="${escapedNodeId}" data-display-name="${escapedDisplayName}" data-short-name="${escapedShortName}">
                    <div class="node-picker-item-name">${escapedDisplayName}</div>
                    <div class="node-picker-item-id">${hexId}</div>
                    ${details.length > 0 ? `<div class="node-picker-item-details">${details.join(' • ')}</div>` : ''}
                </div>
            `;
        }).join('');

        this.resultsContainer.innerHTML = html;

        // Add click listeners to items - Firefox-compatible approach
        const items = this.resultsContainer.querySelectorAll('.node-picker-item');
        items.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.selectNode(item.dataset.nodeId, item.dataset.displayName);
            });

            // Add mousedown event for Firefox compatibility
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
            });
        });

        this.currentFocus = -1;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    selectNode(nodeId, displayName = null) {
        // Find the node data if displayName not provided
        if (!displayName) {
            const node = this.nodes.find(n => n.node_id.toString() === nodeId.toString());
            if (node) {
                displayName = node.long_name || node.short_name || `!${parseInt(nodeId).toString(16).padStart(8, '0')}`;
            } else {
                displayName = `!${parseInt(nodeId).toString(16).padStart(8, '0')}`;
            }
        }

        // Update the inputs
        this.hiddenInput.value = nodeId;
        this.input.value = displayName;

        // Show clear button
        this.clearButton.style.display = 'block';

        // Close dropdown
        this.closeDropdown();

        // Trigger change event for form handling - Firefox-compatible
        const changeEvent = document.createEvent('Event');
        changeEvent.initEvent('change', true, true);
        this.hiddenInput.dispatchEvent(changeEvent);

        // Also trigger input event for additional compatibility
        const inputEvent = document.createEvent('Event');
        inputEvent.initEvent('input', true, true);
        this.hiddenInput.dispatchEvent(inputEvent);
    }

    clearSelection() {
        this.hiddenInput.value = '';
        this.input.value = '';
        this.clearButton.style.display = 'none';
        this.closeDropdown();

        // Trigger change event - Firefox-compatible
        const changeEvent = document.createEvent('Event');
        changeEvent.initEvent('change', true, true);
        this.hiddenInput.dispatchEvent(changeEvent);
    }

    openDropdown() {
        this.dropdown.classList.add('show');
        this.dropdown.style.display = 'block';
        this.isOpen = true;
    }

    closeDropdown() {
        this.dropdown.classList.remove('show');
        this.dropdown.style.display = 'none';
        this.isOpen = false;
        this.currentFocus = -1;
    }

    showLoading() {
        this.loadingElement.style.display = 'block';
        this.noResultsElement.style.display = 'none';
        this.resultsContainer.innerHTML = '';
    }

    hideLoading() {
        this.loadingElement.style.display = 'none';
    }

    showNoResults() {
        this.noResultsElement.style.display = 'block';
        this.loadingElement.style.display = 'none';
        this.resultsContainer.innerHTML = '';
    }

    hideNoResults() {
        this.noResultsElement.style.display = 'none';
    }

    // Public method to set initial value
    setValue(nodeId, displayName) {
        if (nodeId && displayName) {
            this.hiddenInput.value = nodeId;
            this.input.value = displayName;
            this.clearButton.style.display = 'block';
        }
    }
}

// Initialize all node pickers on the page
function initializeNodePickers() {
    const containers = document.querySelectorAll('.node-picker-container');
    containers.forEach(container => {
        if (!container.nodePicker) {
            container.nodePicker = new NodePicker(container);
        }
    });
}

// Auto-initialize when DOM is ready - Firefox-compatible
function initWhenReady() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeNodePickers);
    } else {
        // Use setTimeout for Firefox compatibility
        setTimeout(initializeNodePickers, 0);
    }
}

initWhenReady();

// Export for manual initialization
window.NodePicker = NodePicker;
window.initializeNodePickers = initializeNodePickers;

/**
 * Gateway Picker Component
 * Provides searchable gateway selection with autocomplete functionality
 */

class GatewayPicker {
    constructor(container) {
        this.container = container;
        this.input = container.querySelector('.gateway-picker-input');
        this.hiddenInput = container.querySelector('input[type="hidden"]');
        this.clearButton = container.querySelector('.gateway-picker-clear');
        this.dropdown = container.querySelector('.gateway-picker-dropdown');
        this.loadingElement = container.querySelector('.gateway-picker-loading');
        this.noResultsElement = container.querySelector('.gateway-picker-no-results');
        this.resultsContainer = container.querySelector('.gateway-picker-results');

        this.searchTimeout = null;
        this.currentFocus = -1;
        this.gateways = [];
        this.isOpen = false;

        this.init();
    }

    init() {
        // Bind event listeners with explicit context
        this.input.addEventListener('input', (e) => this.handleInput(e));
        this.input.addEventListener('focus', (e) => this.handleFocus(e));
        this.input.addEventListener('blur', (e) => this.handleBlur(e));
        this.input.addEventListener('keydown', (e) => this.handleKeydown(e));
        this.clearButton.addEventListener('click', (e) => {
            e.preventDefault();
            e.stopPropagation();
            this.clearSelection();
        });

        // Close dropdown when clicking outside - use capture phase for Firefox
        document.addEventListener('click', (e) => {
            if (!this.container.contains(e.target)) {
                this.closeDropdown();
            }
        }, true);
    }

    handleInput(e) {
        const query = e.target.value.trim();

        // Clear the search timeout
        if (this.searchTimeout) {
            clearTimeout(this.searchTimeout);
        }

        // If input is empty, clear selection
        if (!query) {
            this.clearSelection();
            this.closeDropdown();
            return;
        }

        // Debounce the search
        this.searchTimeout = setTimeout(() => {
            this.searchGateways(query);
        }, 300);
    }

    handleFocus(e) {
        const query = e.target.value.trim();
        if (query && this.gateways.length > 0) {
            this.openDropdown();
        } else if (!query) {
            // Show popular gateways when focusing on empty field
            this.searchGateways('');
        }
    }

    handleBlur(e) {
        // Delay closing to allow for clicks on dropdown items
        // Use longer delay for Firefox
        setTimeout(() => {
            if (!this.container.contains(document.activeElement)) {
                this.closeDropdown();
            }
        }, 200);
    }

    handleKeydown(e) {
        if (!this.isOpen) return;

        const items = this.dropdown.querySelectorAll('.gateway-picker-item');

        switch (e.key) {
            case 'ArrowDown':
                e.preventDefault();
                this.currentFocus = Math.min(this.currentFocus + 1, items.length - 1);
                this.updateFocus(items);
                break;

            case 'ArrowUp':
                e.preventDefault();
                this.currentFocus = Math.max(this.currentFocus - 1, -1);
                this.updateFocus(items);
                break;

            case 'Enter':
                e.preventDefault();
                if (this.currentFocus >= 0 && items[this.currentFocus]) {
                    this.selectGateway(items[this.currentFocus].dataset.gatewayId);
                }
                break;

            case 'Escape':
                e.preventDefault();
                this.closeDropdown();
                this.input.blur();
                break;
        }
    }

    updateFocus(items) {
        items.forEach((item, index) => {
            if (index === this.currentFocus) {
                item.classList.add('keyboard-active');
            } else {
                item.classList.remove('keyboard-active');
            }
        });

        // Scroll focused item into view - Firefox-compatible version
        if (this.currentFocus >= 0 && items[this.currentFocus]) {
            const item = items[this.currentFocus];
            const container = this.dropdown;
            const itemTop = item.offsetTop;
            const itemBottom = itemTop + item.offsetHeight;
            const containerTop = container.scrollTop;
            const containerBottom = containerTop + container.clientHeight;

            if (itemTop < containerTop) {
                container.scrollTop = itemTop;
            } else if (itemBottom > containerBottom) {
                container.scrollTop = itemBottom - container.clientHeight;
            }
        }
    }

    async searchGateways(query) {
        this.showLoading();
        this.openDropdown();

        try {
            await window.NodeCache.load();

            const nodeToGateway = (node) => {
                const hexId = `!${node.node_id.toString(16).padStart(8, '0')}`;
                return {
                    id: hexId,
                    gateway_id: hexId,
                    name: node.long_name && node.short_name && node.long_name !== node.short_name
                        ? `${node.long_name} (${node.short_name})`
                        : (node.long_name || node.short_name || hexId),
                    display_name: node.long_name && node.short_name && node.long_name !== node.short_name
                        ? `${node.long_name} (${node.short_name})`
                        : (node.long_name || node.short_name || hexId),
                    node_id: node.node_id.toString(),
                    packet_count: node.gateway_packet_count_24h || 0,
                };
            };

            if (!query) {
                const popularNodes = await window.NodeCache.topByGatewayPackets(20);
                this.gateways = popularNodes.map(nodeToGateway);
                this.isPopular = true;
            } else {
                const matchedNodes = await window.NodeCache.search(query, 20);
                this.gateways = matchedNodes.map(nodeToGateway);
                this.isPopular = false;
            }

            // If no results (could be non-node gateways), fallback to API
            if (this.gateways.length === 0) {
                try {
                    const response = await fetch(`/api/gateways/search?q=${encodeURIComponent(query)}&limit=20`);
                    if (response.ok) {
                        const data = await response.json();
                        this.gateways = data.gateways || [];
                        this.isPopular = data.is_popular || false;
                    } else {
                        const allGatewaysResponse = await fetch('/api/gateways');
                        const allGatewaysData = await allGatewaysResponse.json();
                        this.gateways = this.filterGateways(allGatewaysData.gateways, query);
                    }
                } catch (fallbackErr) {
                    console.warn('GatewayPicker: API fallback failed', fallbackErr);
                }
            }

            this.renderResults();

        } catch (error) {
            console.error('Error searching gateways:', error);
            this.showNoResults();
        }
    }

    filterGateways(gateways, query) {
        const lowerQuery = query.toLowerCase();

        return gateways.filter(gateway => {
            // Gateway can be a string ID or an object with name/id
            const gatewayStr = typeof gateway === 'string' ? gateway : (gateway.name || gateway.id || '');
            return gatewayStr.toLowerCase().includes(lowerQuery);
        }).slice(0, 20); // Limit results
    }

    renderResults() {
        this.hideLoading();
        this.hideNoResults();

        if (this.gateways.length === 0) {
            this.showNoResults();
            return;
        }

        const html = this.gateways.map(gateway => {
            // Handle both string gateways and gateway objects
            let gatewayId, displayName, details = [];

            if (typeof gateway === 'string') {
                gatewayId = gateway;
                displayName = gateway;

                // If it looks like a node ID, format it nicely
                if (gateway.startsWith('!')) {
                    displayName = gateway;
                    details.push('Node Gateway');
                }
            } else {
                gatewayId = gateway.id || gateway.gateway_id;
                displayName = gateway.display_name || gateway.name || gatewayId;

                if (gateway.node_id) {
                    details.push('Node Gateway');
                }
                if (gateway.packet_count) {
                    details.push(`${gateway.packet_count} packets`);
                }
                if (this.isPopular && !gateway.packet_count) {
                    details.push('Popular Gateway');
                }
            }

            // Escape HTML attributes for Firefox compatibility
            const escapedGatewayId = this.escapeHtml(gatewayId);
            const escapedDisplayName = this.escapeHtml(displayName);

            return `
                <div class="gateway-picker-item" data-gateway-id="${escapedGatewayId}" data-display-name="${escapedDisplayName}">
                    <div class="gateway-picker-item-name">${escapedDisplayName}</div>
                    <div class="gateway-picker-item-id">${escapedGatewayId}</div>
                    ${details.length > 0 ? `<div class="gateway-picker-item-details">${details.join(' • ')}</div>` : ''}
                </div>
            `;
        }).join('');

        this.resultsContainer.innerHTML = html;

        // Add click listeners to items - Firefox-compatible approach
        const items = this.resultsContainer.querySelectorAll('.gateway-picker-item');
        items.forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                e.stopPropagation();
                this.selectGateway(item.dataset.gatewayId, item.dataset.displayName);
            });

            // Add mousedown event for Firefox compatibility
            item.addEventListener('mousedown', (e) => {
                e.preventDefault();
            });
        });

        this.currentFocus = -1;
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    selectGateway(gatewayId, displayName = null) {
        // Convert Meshtastic hex-style ID (e.g., !abcd1234) to decimal node ID for consistency
        let storedId = gatewayId;
        if (typeof gatewayId === 'string' && gatewayId.startsWith('!')) {
            try {
                storedId = parseInt(gatewayId.substring(1), 16).toString();
            } catch (e) {
                storedId = gatewayId;
            }
        }

        // Update inputs: hidden input uses unified decimal ID
        this.hiddenInput.value = storedId;
        this.input.value = displayName || storedId;

        // Show clear button
        this.clearButton.style.display = 'block';

        // Close dropdown
        this.closeDropdown();

        // Trigger change event for form handling - Firefox-compatible
        const changeEvent = document.createEvent('Event');
        changeEvent.initEvent('change', true, true);
        this.hiddenInput.dispatchEvent(changeEvent);
    }

    clearSelection() {
        this.hiddenInput.value = '';
        this.input.value = '';
        this.clearButton.style.display = 'none';
        this.closeDropdown();

        // Trigger change event - Firefox-compatible
        const changeEvent = document.createEvent('Event');
        changeEvent.initEvent('change', true, true);
        this.hiddenInput.dispatchEvent(changeEvent);
    }

    openDropdown() {
        this.dropdown.classList.add('show');
        this.dropdown.style.display = 'block';
        this.isOpen = true;
    }

    closeDropdown() {
        this.dropdown.classList.remove('show');
        this.dropdown.style.display = 'none';
        this.isOpen = false;
        this.currentFocus = -1;
    }

    showLoading() {
        this.loadingElement.style.display = 'block';
        this.noResultsElement.style.display = 'none';
        this.resultsContainer.innerHTML = '';
    }

    hideLoading() {
        this.loadingElement.style.display = 'none';
    }

    showNoResults() {
        this.noResultsElement.style.display = 'block';
        this.loadingElement.style.display = 'none';
        this.resultsContainer.innerHTML = '';
    }

    hideNoResults() {
        this.noResultsElement.style.display = 'none';
    }

    // Public method to set initial value
    async setValue(gatewayId, displayName) {
        if (!gatewayId) return;

        // Convert Meshtastic hex-style ID (e.g., !abcd1234) to decimal node ID for consistency
        let storedId = gatewayId;
        if (typeof gatewayId === 'string' && gatewayId.startsWith('!')) {
            try {
                storedId = parseInt(gatewayId.substring(1), 16).toString();
            } catch (e) {
                storedId = gatewayId;
            }
        }

        // Determine displayName if missing
        if (!displayName) {
            if (window.NodeCache && typeof window.NodeCache.getNode === 'function') {
                try {
                    const node = await window.NodeCache.getNode(storedId);
                    if (node) {
                        displayName = node.long_name || node.short_name || `!${parseInt(node.node_id).toString(16).padStart(8, '0')}`;
                    }
                } catch (_) { /* ignore */ }
            }
        }

        // Fallback display
        if (!displayName) {
            displayName = gatewayId;
        }

        this.hiddenInput.value = storedId;
        this.input.value = displayName;
        this.clearButton.style.display = 'block';
    }
}

// Initialize all gateway pickers on the page
function initializeGatewayPickers() {
    const containers = document.querySelectorAll('.gateway-picker-container');
    containers.forEach(container => {
        if (!container.gatewayPicker) {
            container.gatewayPicker = new GatewayPicker(container);
        }
    });
}

// Update the main initialization function
function initializeAllPickers() {
    initializeNodePickers();
    initializeGatewayPickers();
}

// Auto-initialize when DOM is ready - Firefox-compatible
function initAllWhenReady() {
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initializeAllPickers);
    } else {
        // Use setTimeout for Firefox compatibility
        setTimeout(initializeAllPickers, 0);
    }
}

initAllWhenReady();

// Export for manual initialization
window.NodePicker = NodePicker;
window.GatewayPicker = GatewayPicker;
window.initializeNodePickers = initializeNodePickers;
window.initializeGatewayPickers = initializeGatewayPickers;
window.initializeAllPickers = initializeAllPickers;
