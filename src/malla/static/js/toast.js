/**
 * Toast notifications — thin wrapper over Bootstrap toasts with the Malla
 * design-system look (see .toast-* rules in malla.css).
 *
 * Module usage:  import { showToast } from './toast.js';
 * Legacy usage:  window.MallaToast.error('...', { title: 'Save failed' });
 */

const CONTAINER_ID = 'malla-toast-container';

const VARIANT_META = {
    success: { icon: 'bi-check-circle-fill', label: 'Success' },
    error: { icon: 'bi-exclamation-triangle-fill', label: 'Error' },
    warning: { icon: 'bi-exclamation-circle-fill', label: 'Warning' },
    info: { icon: 'bi-info-circle-fill', label: 'Info' },
};

function ensureContainer() {
    let container = document.getElementById(CONTAINER_ID);
    if (!container) {
        container = document.createElement('div');
        container.id = CONTAINER_ID;
        container.className = 'toast-container';
        container.setAttribute('role', 'region');
        container.setAttribute('aria-label', 'Notifications');
        document.body.appendChild(container);
    }
    return container;
}

/**
 * Show a toast.
 * @param {string} message body text
 * @param {object} [options]
 * @param {string} [options.title] header title (defaults to variant label)
 * @param {'success'|'error'|'warning'|'info'} [options.variant]
 * @param {number} [options.delay] ms before auto-hide; 0 = sticky
 * @returns {bootstrap.Toast|null}
 */
export function showToast(message, { title, variant = 'info', delay = 5000 } = {}) {
    if (typeof bootstrap === 'undefined') {
        // Bootstrap bundle missing: last-resort console output, never throw.
        console.warn(`[toast:${variant}] ${title ?? ''} ${message}`);
        return null;
    }

    const meta = VARIANT_META[variant] ?? VARIANT_META.info;
    // Whitelist: variant lands in class attributes via this template.
    if (!VARIANT_META[variant]) variant = 'info';
    const container = ensureContainer();

    const element = document.createElement('div');
    element.className = 'toast';
    element.setAttribute('role', variant === 'error' ? 'alert' : 'status');
    element.setAttribute('aria-live', variant === 'error' ? 'assertive' : 'polite');
    element.innerHTML = `
        <div class="d-flex align-items-stretch">
            <div class="toast-indicator ${meta.icon ? variant : ''}"></div>
            <div class="flex-grow-1">
                <div class="toast-header">
                    <i class="bi ${meta.icon} me-2 text-${variant === 'error' ? 'danger' : variant}"></i>
                    <strong class="me-auto">${escapeHtml(title ?? meta.label)}</strong>
                    <button type="button" class="btn-close" data-bs-dismiss="toast" aria-label="Close"></button>
                </div>
                <div class="toast-body"></div>
            </div>
        </div>`;
    element.querySelector('.toast-body').textContent = message ?? '';

    container.appendChild(element);
    const toast = new bootstrap.Toast(element, { delay, autohide: delay > 0 });
    toast.show();
    element.addEventListener('hidden.bs.toast', () => element.remove());
    return toast;
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = String(text ?? '');
    return div.innerHTML;
}

export const MallaToast = {
    success: (message, options = {}) => showToast(message, { ...options, variant: 'success' }),
    error: (message, options = {}) => showToast(message, { ...options, variant: 'error', delay: 8000 }),
    warning: (message, options = {}) => showToast(message, { ...options, variant: 'warning' }),
    info: (message, options = {}) => showToast(message, { ...options, variant: 'info' }),
};

// Global bridge for legacy inline scripts.
window.MallaToast = MallaToast;
