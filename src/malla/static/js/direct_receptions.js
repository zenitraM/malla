/**
 * Direct Receptions Chart Component
 * Handles loading and displaying direct receptions data with interactive charts
 */
class DirectReceptionsChart {
    constructor(nodeId) {
        this.nodeId = nodeId;
        this.currentDirection = 'received';
        this.currentMetric = 'rssi';
        this.chartTraces = [];
        this.nodeStats = [];

        this.initializeEventListeners();
    }

    /**
     * Initialize event listeners for direction and metric toggles
     */
    initializeEventListeners() {
        // Direction toggle handler
        const directionToggleGroup = document.getElementById('direction-toggle-group');
        if (directionToggleGroup) {
            directionToggleGroup.addEventListener('click', (e) => {
                if (e.target && e.target.matches('button[data-direction]')) {
                    const selectedDirection = e.target.getAttribute('data-direction');
                    if (selectedDirection === this.currentDirection) return;

                    // Update active button styling
                    directionToggleGroup.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
                    e.target.classList.add('active');

                    // Reload chart with new direction
                    this.loadChart(selectedDirection);
                }
            });
        }

        // Metric toggle handler
        const metricToggleGroup = document.getElementById('metric-toggle-group');
        if (metricToggleGroup) {
            metricToggleGroup.addEventListener('click', (e) => {
                if (e.target && e.target.matches('button[data-metric]')) {
                    const selectedMetric = e.target.getAttribute('data-metric');
                    if (selectedMetric === this.currentMetric) return;

                    // Update active button styling
                    metricToggleGroup.querySelectorAll('button').forEach(btn => btn.classList.remove('active'));
                    e.target.classList.add('active');

                    this.switchMetric(selectedMetric);
                }
            });
        }
    }

    /**
     * Load the direct receptions chart
     */
    async loadChart(direction = 'received') {
        const cardContainer = document.getElementById('direct-receptions-card');
        const chartContainer = document.getElementById('direct-receptions-chart');

        if (!cardContainer || !chartContainer) {
            return;
        }

        try {
            // Show card and loading indicator
            cardContainer.style.display = 'block';
            document.getElementById('direct-receptions-loading').style.display = 'block';
            document.getElementById('direct-receptions-content').style.display = 'none';

            const response = await fetch(`/api/node/${this.nodeId}/direct-receptions?limit=1000&direction=${direction}`);
            const data = await response.json();

            if (data.error) {
                throw new Error(data.error);
            }

            // Update description based on direction
            this.updateDescription(direction);

            // Always show the content area (toggles) even if no data
            document.getElementById('direct-receptions-loading').style.display = 'none';
            document.getElementById('direct-receptions-content').style.display = 'block';
            this.currentDirection = direction;

            if (!data.direct_receptions || data.direct_receptions.length === 0) {
                this.showNoDataMessage(direction, chartContainer);
                this.clearLegendTable();
                this.chartTraces = [];
                this.nodeStats = [];
                return;
            }

            // Process data and create chart
            this.processChartData(data);
            this.createPlotlyChart(chartContainer);
            this.populateLegendTable();

        } catch (error) {
            console.error('Error loading direct receptions:', error);
            this.showErrorMessage(error, cardContainer, chartContainer);
        }
    }

    /**
     * Update the description text based on direction
     */
    updateDescription(direction) {
        const description = document.getElementById('direct-receptions-description');
        if (direction === 'received') {
            description.textContent = 'Packets received directly (0 hops) by this gateway from other nodes.';
        } else {
            description.textContent = 'Packets from this node received directly (0 hops) by other gateways.';
        }
    }

    /**
     * Show no data message
     */
    showNoDataMessage(direction, chartContainer) {
        chartContainer.innerHTML = `
            <div class="d-flex align-items-center justify-content-center h-100">
                <div class="text-center text-muted">
                    <i class="bi bi-info-circle" style="font-size: 2rem;"></i>
                    <div class="mt-2">No direct ${direction} data available</div>
                    <div class="small">Try switching to the other direction</div>
                </div>
            </div>
        `;
    }

    /**
     * Show error message
     */
    showErrorMessage(error, cardContainer, chartContainer) {
        cardContainer.style.display = 'block';
        document.getElementById('direct-receptions-loading').style.display = 'none';
        document.getElementById('direct-receptions-content').style.display = 'block';

        chartContainer.innerHTML = `
            <div class="d-flex align-items-center justify-content-center h-100">
                <div class="text-center text-danger">
                    <i class="bi bi-exclamation-triangle" style="font-size: 2rem;"></i>
                    <div class="mt-2">Error loading direct receptions data</div>
                    <div class="small">${error.message}</div>
                </div>
            </div>
        `;

        this.clearLegendTable('Error loading data');
    }

    /**
     * Process chart data from API response
     */
    processChartData(data) {
        const colors = [
            '#007bff', '#28a745', '#dc3545', '#fd7e14', '#6610f2', '#20c997',
            '#6f42c1', '#ffc107', '#0dcaf0', '#d63384',
        ];

        this.chartTraces = [];
        this.nodeStats = [];
        let colorIndex = 0;

        data.direct_receptions.forEach((nodeData) => {
            const color = colors[colorIndex % colors.length];
            colorIndex += 1;

            // Convert packet data to chart format
            const timestamps = nodeData.packets.map(pkt => new Date(pkt.timestamp * 1000));
            const rssiValues = nodeData.packets.map(pkt => pkt.rssi);
            const snrValues = nodeData.packets.map(pkt => pkt.snr);
            const packetIds = nodeData.packets.map(pkt => pkt.packet_id);

            this.nodeStats.push({
                nodeId: nodeData.from_node_id,
                label: nodeData.from_node_name,
                color: color,
                packetCount: nodeData.packet_count,
                rssiAvg: nodeData.rssi_avg,
                rssiMin: nodeData.rssi_min,
                rssiMax: nodeData.rssi_max,
                snrAvg: nodeData.snr_avg,
                snrMin: nodeData.snr_min,
                snrMax: nodeData.snr_max,
                visible: true
            });

            this.chartTraces.push({
                x: timestamps,
                y: rssiValues, // default metric is RSSI
                mode: 'lines+markers',
                type: 'scatter',
                name: nodeData.from_node_name,
                line: { color: color, width: 2 },
                marker: { color: color, size: 4 },
                visible: true,
                meta: {
                    rssi: rssiValues,
                    snr: snrValues,
                    packetIds: packetIds,
                    nodeId: nodeData.from_node_id,
                    timestamps: timestamps,
                },
                customdata: packetIds,
                hovertemplate: '<b>%{fullData.name}</b><br>' +
                              'Time: %{x}<br>' +
                              'Value: %{y}<br>' +
                              '<extra></extra>'
            });
        });
    }

    /**
     * Create the Plotly chart
     */
    createPlotlyChart(chartContainer) {
        const layout = {
            title: '',
            xaxis: {
                title: 'Time',
                type: 'date',
                fixedrange: false // Allow zooming on x-axis
            },
            yaxis: {
                title: 'RSSI (dBm)',
                fixedrange: true // Prevent zooming on y-axis
            },
            showlegend: false, // We use custom legend
            hovermode: 'closest',
            margin: { l: 60, r: 20, t: 20, b: 60 },
            dragmode: 'pan' // Enable pan by default
        };

        const config = {
            displayModeBar: true,
            modeBarButtonsToRemove: ['select2d', 'lasso2d', 'autoScale2d', 'resetScale2d'],
            displaylogo: false,
            responsive: true,
            scrollZoom: true, // Enable scroll to zoom
            doubleClick: 'reset' // Double-click resets to original view
        };

        // Create the plot
        Plotly.newPlot(chartContainer, this.chartTraces, layout, config);

        // Click handler to open packet details
        chartContainer.on('plotly_click', (data) => {
            if (data.points.length > 0) {
                const point = data.points[0];
                const packetId = point.customdata;
                window.open(`/packet/${packetId}`, '_blank');
            }
        });

        // Double-click handler to reset zoom
        chartContainer.on('plotly_doubleclick', () => {
            if (this.chartTraces.length > 0) {
                const allTimestamps = this.chartTraces.flatMap(trace => trace.x);
                const minTime = Math.min(...allTimestamps);
                const maxTime = Math.max(...allTimestamps);

                Plotly.relayout(chartContainer, {
                    'xaxis.range': [minTime, maxTime]
                });
            }
        });
    }

    /**
     * Switch between RSSI and SNR metrics
     */
    switchMetric(selectedMetric) {
        if (selectedMetric === this.currentMetric || this.chartTraces.length === 0) return;

        // Update traces with new metric data
        const update = {
            y: this.chartTraces.map(trace => trace.meta[selectedMetric])
        };

        // Update y-axis label
        const layoutUpdate = {
            'yaxis.title': selectedMetric.toUpperCase() + (selectedMetric === 'rssi' ? ' (dBm)' : ' (dB)'),
            'yaxis.fixedrange': true // Keep y-axis zoom disabled
        };

        this.currentMetric = selectedMetric;

        // Update chart
        const chartContainer = document.getElementById('direct-receptions-chart');
        if (chartContainer) {
            Plotly.restyle(chartContainer, update);
            Plotly.relayout(chartContainer, layoutUpdate);
        }
    }

    /**
     * Populate the custom legend table
     */
    populateLegendTable() {
        const tbody = document.querySelector('#direct-receptions-legend tbody');
        if (!tbody) return;

        tbody.innerHTML = '';

        this.nodeStats.forEach((stats, index) => {
            const row = document.createElement('tr');
            row.style.cursor = 'pointer';
            row.dataset.datasetIndex = index;

            // Format values with proper null handling
            const formatValue = (val, decimals = 1) => val !== null ? val.toFixed(decimals) : 'N/A';

            row.innerHTML = `
                <td>
                    <span class="d-inline-block" style="width: 12px; height: 12px; background-color: ${stats.color}; margin-right: 8px;"></span>
                    ${stats.label}
                </td>
                <td>${stats.packetCount}</td>
                <td>${formatValue(stats.rssiAvg)}</td>
                <td>${formatValue(stats.rssiMin)}</td>
                <td>${formatValue(stats.rssiMax)}</td>
                <td>${formatValue(stats.snrAvg)}</td>
                <td>${formatValue(stats.snrMin)}</td>
                <td>${formatValue(stats.snrMax)}</td>
                <td>
                    <input type="checkbox" ${stats.visible ? 'checked' : ''} class="form-check-input">
                </td>
            `;

            // Add click handler for row
            row.addEventListener('click', (e) => {
                if (e.target.type !== 'checkbox') {
                    const checkbox = row.querySelector('input[type="checkbox"]');
                    checkbox.checked = !checkbox.checked;
                    checkbox.dispatchEvent(new Event('change'));
                }
            });

            // Add change handler for checkbox
            const checkbox = row.querySelector('input[type="checkbox"]');
            checkbox.addEventListener('change', () => {
                const datasetIndex = parseInt(row.dataset.datasetIndex);
                this.nodeStats[datasetIndex].visible = checkbox.checked;

                // Update row styling
                row.style.opacity = checkbox.checked ? '1' : '0.5';

                // Update trace visibility
                const chartContainer = document.getElementById('direct-receptions-chart');
                if (chartContainer && this.chartTraces.length > 0) {
                    const update = { visible: checkbox.checked };
                    Plotly.restyle(chartContainer, update, datasetIndex);
                }
            });

            tbody.appendChild(row);
        });

        this.setupLegendButtons(tbody);
    }

    /**
     * Setup select all / deselect all buttons
     */
    setupLegendButtons(tbody) {
        // Remove existing event listeners to avoid duplicates
        const selectAllBtn = document.getElementById('select-all-nodes');
        const deselectAllBtn = document.getElementById('deselect-all-nodes');

        if (selectAllBtn) {
            selectAllBtn.replaceWith(selectAllBtn.cloneNode(true));
            document.getElementById('select-all-nodes').addEventListener('click', () => {
                this.nodeStats.forEach((stats, index) => {
                    const row = tbody.children[index];
                    if (row) {
                        const checkbox = row.querySelector('input[type="checkbox"]');
                        stats.visible = true;
                        checkbox.checked = true;
                        row.style.opacity = '1';
                    }
                });
                // Show all traces
                const chartContainer = document.getElementById('direct-receptions-chart');
                if (chartContainer && this.chartTraces.length > 0) {
                    const update = { visible: true };
                    Plotly.restyle(chartContainer, update);
                }
            });
        }

        if (deselectAllBtn) {
            deselectAllBtn.replaceWith(deselectAllBtn.cloneNode(true));
            document.getElementById('deselect-all-nodes').addEventListener('click', () => {
                this.nodeStats.forEach((stats, index) => {
                    const row = tbody.children[index];
                    if (row) {
                        const checkbox = row.querySelector('input[type="checkbox"]');
                        stats.visible = false;
                        checkbox.checked = false;
                        row.style.opacity = '0.5';
                    }
                });
                // Hide all traces
                const chartContainer = document.getElementById('direct-receptions-chart');
                if (chartContainer && this.chartTraces.length > 0) {
                    const update = { visible: false };
                    Plotly.restyle(chartContainer, update);
                }
            });
        }
    }

    /**
     * Clear the legend table
     */
    clearLegendTable(message = 'No data available') {
        const tbody = document.querySelector('#direct-receptions-legend tbody');
        if (tbody) {
            tbody.innerHTML = `<tr><td colspan="9" class="text-center text-muted">${message}</td></tr>`;
        }
    }

    /**
     * Initialize the component
     */
    async initialize() {
        await this.loadChart();
    }
}

// Export for use in other scripts
window.DirectReceptionsChart = DirectReceptionsChart;
