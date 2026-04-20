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

        tbody.replaceChildren();

        stats.forEach(stat => {
            const row = document.createElement('tr');

            const relayCell = document.createElement('td');
            relayCell.appendChild(el('code', { className: 'text-primary' }, stat.relay_hex));
            row.appendChild(relayCell);

            const countCell = document.createElement('td');
            countCell.appendChild(badge(String(stat.count), 'bg-info'));
            row.appendChild(countCell);

            const rssiCell = document.createElement('td');
            if (stat.avg_rssi !== null && stat.avg_rssi !== undefined) {
                const rssiValue = stat.avg_rssi.toFixed(1);
                rssiCell.appendChild(el('span', { className: 'text-muted' }, `${rssiValue} dBm`));
            } else {
                rssiCell.appendChild(el('span', { className: 'text-muted' }, '-'));
            }
            row.appendChild(rssiCell);

            const snrCell = document.createElement('td');
            if (stat.avg_snr !== null && stat.avg_snr !== undefined) {
                const snrValue = stat.avg_snr.toFixed(1);
                snrCell.appendChild(el('span', { className: 'text-muted' }, `${snrValue} dB`));
            } else {
                snrCell.appendChild(el('span', { className: 'text-muted' }, '-'));
            }
            row.appendChild(snrCell);

            const candidatesCell = document.createElement('td');
            if (stat.candidates && stat.candidates.length > 0) {
                const candidateNodes = [];
                stat.candidates.forEach((candidate, index) => {
                    if (index > 0) candidateNodes.push(textNode(', '));
                    candidateNodes.push(
                        nodeLink(candidate.node_id, candidate.node_name, {
                            className: 'node-link text-decoration-none'
                        }),
                        textNode(' '),
                        el('small', { className: 'text-muted' }, `(${candidate.last_byte})`)
                    );
                });
                candidatesCell.appendChild(fragment(candidateNodes));
            } else {
                candidatesCell.appendChild(el('span', { className: 'text-muted' }, 'No matching 0-hop nodes'));
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

        tbody.replaceChildren(
            el('tr', null,
                el('td', { colspan: '5', className: 'text-center text-muted py-3' },
                    icon('bi bi-info-circle'),
                    textNode(' No relay node data available for this gateway.'),
                    el('br'),
                    el('small', null, 'This node may not have reported any packets with relay_node information.')
                )
            )
        );
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

        tbody.replaceChildren(
            el('tr', null,
                el('td', { colspan: '5', className: 'text-center text-danger py-3' },
                    icon('bi bi-exclamation-triangle'),
                    textNode(` Error loading relay node analysis: ${error.message}`)
                )
            )
        );
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
