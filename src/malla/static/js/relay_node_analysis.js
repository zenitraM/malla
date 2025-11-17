/**
 * Relay Node Analysis Component
 * Displays relay_node statistics for gateway nodes with candidate source nodes
 */

class RelayNodeAnalysis {
    constructor(nodeId) {
        this.nodeId = nodeId;
        this.data = null;
    }

    /**
     * Initialize and load the relay node analysis
     */
    async initialize() {
        const cardContainer = document.getElementById('relay-node-analysis-card');

        if (!cardContainer) {
            return;
        }

        try {
            await this.loadData();
        } catch (error) {
            console.error('Error initializing relay node analysis:', error);
        }
    }

    /**
     * Load relay node analysis data from API
     */
    async loadData() {
        const cardContainer = document.getElementById('relay-node-analysis-card');
        const tableContainer = document.getElementById('relay-node-analysis-table');
        const loadingIndicator = document.getElementById('relay-node-analysis-loading');
        const contentDiv = document.getElementById('relay-node-analysis-content');

        if (!cardContainer || !tableContainer) {
            return;
        }

        try {
            // Show card and loading indicator
            cardContainer.style.display = 'block';
            loadingIndicator.style.display = 'block';
            contentDiv.style.display = 'none';

            const response = await fetch(`/api/node/${this.nodeId}/relay-node-analysis?limit=50`);
            if (!response.ok) {
                throw new Error(`HTTP error! status: ${response.status}`);
            }
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            this.data = data;

            // Hide loading, show content
            loadingIndicator.style.display = 'none';
            contentDiv.style.display = 'block';

            if (!data.relay_node_stats || data.relay_node_stats.length === 0) {
                this.showNoDataMessage(tableContainer);
                return;
            }

            // Render the table
            this.renderTable(data.relay_node_stats, tableContainer);

        } catch (error) {
            console.error('Error loading relay node analysis:', error);
            this.showErrorMessage(error, cardContainer, loadingIndicator, contentDiv);
        }
    }

    /**
     * Render the relay node analysis table
     */
    renderTable(stats, container) {
        const tbody = container.querySelector('tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        stats.forEach(stat => {
            const row = document.createElement('tr');

            // Relay node column
            const relayCell = document.createElement('td');
            relayCell.innerHTML = `<code class="text-primary">${stat.relay_hex}</code>`;
            row.appendChild(relayCell);

            // Count column
            const countCell = document.createElement('td');
            countCell.innerHTML = `<span class="badge bg-info">${stat.count}</span>`;
            row.appendChild(countCell);

            // Avg RSSI column
            const rssiCell = document.createElement('td');
            if (stat.avg_rssi !== null && stat.avg_rssi !== undefined) {
                const rssiValue = stat.avg_rssi.toFixed(1);
                rssiCell.innerHTML = `<span class="text-muted">${rssiValue} dBm</span>`;
            } else {
                rssiCell.innerHTML = '<span class="text-muted">-</span>';
            }
            row.appendChild(rssiCell);

            // Avg SNR column
            const snrCell = document.createElement('td');
            if (stat.avg_snr !== null && stat.avg_snr !== undefined) {
                const snrValue = stat.avg_snr.toFixed(1);
                snrCell.innerHTML = `<span class="text-muted">${snrValue} dB</span>`;
            } else {
                snrCell.innerHTML = '<span class="text-muted">-</span>';
            }
            row.appendChild(snrCell);

            // Candidates column
            const candidatesCell = document.createElement('td');
            if (stat.candidates && stat.candidates.length > 0) {
                const candidateLinks = stat.candidates.map(candidate => {
                    return `<a href="/node/${candidate.node_id}" class="node-link text-decoration-none">${candidate.node_name}</a> <small class="text-muted">(${candidate.last_byte})</small>`;
                }).join(', ');
                candidatesCell.innerHTML = candidateLinks;
            } else {
                candidatesCell.innerHTML = '<span class="text-muted">No matching 0-hop nodes</span>';
            }
            row.appendChild(candidatesCell);

            tbody.appendChild(row);
        });
    }

    /**
     * Show no data message
     */
    showNoDataMessage(container) {
        const tbody = container.querySelector('tbody');
        if (!tbody) return;

        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-muted py-3">
                    <i class="bi bi-info-circle"></i> No relay node data available for this gateway.
                    <br><small>This node may not have reported any packets with relay_node information.</small>
                </td>
            </tr>
        `;
    }

    /**
     * Show error message
     */
    showErrorMessage(error, cardContainer, loadingIndicator, contentDiv) {
        loadingIndicator.style.display = 'none';
        contentDiv.style.display = 'block';

        const tableContainer = document.getElementById('relay-node-analysis-table');
        const tbody = tableContainer.querySelector('tbody');
        if (!tbody) return;

        tbody.innerHTML = `
            <tr>
                <td colspan="5" class="text-center text-danger py-3">
                    <i class="bi bi-exclamation-triangle"></i> Error loading relay node analysis: ${error.message}
                </td>
            </tr>
        `;
    }
}

// Initialize when DOM is loaded
document.addEventListener('DOMContentLoaded', function() {
    const scriptTag = document.querySelector('script[data-node-id]');
    if (scriptTag) {
        const nodeId = scriptTag.getAttribute('data-node-id');
        const relayNodeAnalysis = new RelayNodeAnalysis(nodeId);
        relayNodeAnalysis.initialize();
    }
});
