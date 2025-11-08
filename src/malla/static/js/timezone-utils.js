/**
 * Timezone Utility Functions
 * Provides helper functions for formatting timestamps based on timezone preference
 */

/**
 * Get current timezone preference
 * @returns {string} 'local' or 'utc'
 */
function getTimezonePreference() {
    if (window.timezoneToggle) {
        return window.timezoneToggle.getTimezonePreference();
    }
    // Default to local if toggle not initialized yet
    const saved = localStorage.getItem('malla-timezone-preference');
    return (saved && ['local', 'utc'].includes(saved)) ? saved : 'local';
}

/**
 * Format a timestamp string or unix timestamp according to current timezone preference
 * This is the main function to use for displaying timestamps
 * @param {string|number} timestamp - Unix timestamp (seconds) or ISO string
 * @param {string} format - 'datetime' (default), 'date', or 'time'
 * @returns {string} Formatted timestamp string
 */
function formatTimestamp(timestamp, format = 'datetime') {
    if (!timestamp) return '';

    // Convert to unix timestamp if it's a string
    let unixTimestamp;
    if (typeof timestamp === 'string') {
        // Check if it's already a formatted string (contains spaces, dashes, or 'T')
        // Note: This assumes timestamps are always positive, as '-' in negative numbers would be
        // incorrectly detected as a formatted string. This is acceptable for timestamp use cases.
        // If so, try to parse it (strip " UTC" suffix if present to avoid Date parsing issues)
        if (timestamp.includes('-') || timestamp.includes(' ') || timestamp.includes('T')) {
            // Remove " UTC" suffix if present before parsing
            const cleanedTimestamp = timestamp.replace(/\s+UTC\s*$/, '');
            const date = new Date(cleanedTimestamp);
            if (!isNaN(date.getTime())) {
                unixTimestamp = date.getTime() / 1000;
            } else {
                return timestamp; // Return as-is if we can't parse it
            }
        } else {
            // Assume it's a unix timestamp string
            unixTimestamp = parseFloat(timestamp);
        }
    } else {
        unixTimestamp = timestamp;
    }

    if (isNaN(unixTimestamp)) {
        return timestamp; // Return original if we can't parse it
    }

    const preference = getTimezonePreference();
    const date = new Date(unixTimestamp * 1000);

    if (preference === 'utc') {
        return formatUTC(date, format);
    } else {
        return formatLocal(date, format);
    }
}

/**
 * Format date as UTC
 */
function formatUTC(date, format = 'datetime') {
    const year = date.getUTCFullYear();
    const month = String(date.getUTCMonth() + 1).padStart(2, '0');
    const day = String(date.getUTCDate()).padStart(2, '0');
    const hours = String(date.getUTCHours()).padStart(2, '0');
    const minutes = String(date.getUTCMinutes()).padStart(2, '0');
    const seconds = String(date.getUTCSeconds()).padStart(2, '0');

    if (format === 'date') {
        return `${year}-${month}-${day}`;
    } else if (format === 'time') {
        return `${hours}:${minutes}:${seconds} UTC`;
    } else {
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds} UTC`;
    }
}

/**
 * Format date as local time
 */
function formatLocal(date, format = 'datetime') {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    const seconds = String(date.getSeconds()).padStart(2, '0');

    if (format === 'date') {
        return `${year}-${month}-${day}`;
    } else if (format === 'time') {
        return `${hours}:${minutes}:${seconds}`;
    } else {
        return `${year}-${month}-${day} ${hours}:${minutes}:${seconds}`;
    }
}

/**
 * Convert datetime-local input value to Unix timestamp
 * datetime-local is always in the browser's local timezone
 * @param {string} datetimeLocalValue - Value from datetime-local input
 * @returns {number|null} Unix timestamp in seconds
 */
function datetimeLocalToTimestamp(datetimeLocalValue) {
    if (!datetimeLocalValue) return null;
    const date = new Date(datetimeLocalValue);
    if (isNaN(date.getTime())) return null;
    return date.getTime() / 1000;
}

/**
 * Convert Unix timestamp to datetime-local input value
 * Always returns in local time (as required by datetime-local inputs)
 * @param {number} timestamp - Unix timestamp in seconds
 * @returns {string} Value for datetime-local input
 */
function timestampToDatetimeLocal(timestamp) {
    if (!timestamp) return '';

    const date = new Date(timestamp * 1000);
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');

    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

/**
 * Escape HTML special characters to prevent XSS
 * @param {string} str - String to escape
 * @returns {string} HTML-escaped string
 */
function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function(match) {
        const escape = {
            '&': '&amp;',
            '<': '&lt;',
            '>': '&gt;',
            '"': '&quot;',
            "'": '&#39;'
        };
        return escape[match];
    });
}

/**
 * Render a timestamp column for tables
 * Use this in ModernTable column render functions
 * @param {object} row - Table row data
 * @param {string} timestampField - Field name containing the timestamp (default: 'timestamp')
 * @param {string} idField - Field name for the row ID (default: 'id')
 * @param {string} linkPath - Path template for link (default: '/packet/{id}')
 * @returns {string} HTML for timestamp cell
 */
function renderTimestampColumn(row, timestampField = 'timestamp', idField = 'id', linkPath = '/packet/{id}') {
    const timestamp = row[timestampField];
    const formattedTime = formatTimestamp(timestamp);
    const id = row[idField];

    // Escape HTML to prevent XSS
    const escapedId = escapeHtml(id);
    const escapedFormattedTime = escapeHtml(formattedTime);
    const escapedTimestamp = escapeHtml(timestamp);

    const link = linkPath.replace('{id}', escapedId);

    return `<a href="${link}" class="text-decoration-none" title="View details">
                <small class="timestamp-display" data-timestamp="${escapedTimestamp}">${escapedFormattedTime}</small>
            </a>`;
}

/**
 * Update all timestamps on the page based on current timezone preference
 * Call this when timezone changes
 */
function updateAllTimestamps() {
    // Update all elements with data-timestamp attribute
    const timestampElements = document.querySelectorAll('[data-timestamp]');
    timestampElements.forEach(element => {
        const timestamp = element.getAttribute('data-timestamp');
        if (timestamp) {
            const format = element.getAttribute('data-timestamp-format') || 'datetime';
            element.textContent = formatTimestamp(timestamp, format);
        }
    });

    // Also trigger table refresh if ModernTable exists
    if (window.modernTableInstances) {
        window.modernTableInstances.forEach(table => {
            if (table && typeof table.renderTableBody === 'function') {
                table.renderTableBody();
            }
        });
    }
}

/**
 * Listen for timezone changes and update timestamps
 */
window.addEventListener('timezoneChanged', function(event) {
    // Reload the page when timezone changes.
    // Rationale: Reloading ensures all server-rendered timestamps and dynamic content
    // are consistently updated, avoiding the need to track and update every timestamp
    // location in the DOM. This is simpler and more robust than attempting to update
    // all possible timestamp locations dynamically, especially for content rendered
    // on the server or by third-party components.
    window.location.reload();
});

// Export for module systems
if (typeof module !== 'undefined' && module.exports) {
    module.exports = {
        getTimezonePreference,
        formatTimestamp,
        formatUTC,
        formatLocal,
        datetimeLocalToTimestamp,
        timestampToDatetimeLocal,
        escapeHtml,
        renderTimestampColumn,
        updateAllTimestamps
    };
}
