/**
 * Malla API client — fetch wrapper shared by all pages.
 *
 * Envelope contract (/api/v1):
 *   success: {"data": ..., "meta": {...}}   (lists: meta.pagination {...})
 *   error:   {"error": {"code": "...", "message": "..."}} with 4xx/5xx status
 *
 * Legacy endpoints return flat bodies ({data: [...], total_count, ...} or a
 * bare object); they pass through untouched (meta: null).
 *
 * - Errors raise ApiError and surface a toast (unless `silent`).
 * - One silent automatic retry on network failure (connection blips).
 * - AbortSignal pass-through; aborted requests never toast.
 *
 * Module usage:   import { apiGet, apiSend } from './api-client.js';
 * Legacy usage:   await window.MallaAPI.get('/api/v1/stats/summary')
 */

import { showToast } from './toast.js';

export class ApiError extends Error {
    constructor(message, { status = 0, code = 'unknown', body = null } = {}) {
        super(message);
        this.name = 'ApiError';
        this.status = status;
        this.code = code;
        this.body = body;
    }
}

function normalizeErrorPayload(raw, status) {
    // Envelope: {"error": {"code", "message"}}; legacy: {"error": "str"}
    if (raw && typeof raw === 'object' && raw.error) {
        if (typeof raw.error === 'string') {
            return { code: `http_${status}`, message: raw.error };
        }
        return {
            code: raw.error.code || `http_${status}`,
            message: raw.error.message || 'Request failed',
        };
    }
    return { code: `http_${status}`, message: `Request failed (HTTP ${status})` };
}

function isAbort(error) {
    return error && (error.name === 'AbortError' || error.name === 'TimeoutError');
}

/**
 * Core request. Returns `{ response, payload, data, meta }` where `data` is
 * the unwrapped envelope data (or the raw body for legacy endpoints) and
 * `meta` the envelope metadata (null for legacy bodies).
 */
async function requestRaw(path, {
    method = 'GET',
    body = null,
    headers = {},
    signal = null,
    silent = false,
    timeoutMs = 0,
} = {}) {
    const doFetch = () => {
        const controller = timeoutMs > 0 && !signal ? new AbortController() : null;
        const timer = controller
            ? setTimeout(
                () => controller.abort(new DOMException('Timeout', 'TimeoutError')),
                timeoutMs
            )
            : null;
        return fetch(path, {
            method,
            headers: {
                Accept: 'application/json',
                ...(body !== null ? { 'Content-Type': 'application/json' } : {}),
                ...headers,
            },
            body: body !== null ? JSON.stringify(body) : undefined,
            signal: signal ?? controller?.signal ?? undefined,
        }).finally(() => timer && clearTimeout(timer));
    };

    let response;
    try {
        response = await doFetch();
    } catch (error) {
        if (isAbort(error)) throw error;
        try {
            response = await doFetch(); // single silent retry
        } catch (retryError) {
            if (isAbort(retryError)) throw retryError;
            if (!silent) {
                showToast('Network error — check your connection.', {
                    variant: 'error',
                    title: 'Request failed',
                });
            }
            throw new ApiError('Network error', { code: 'network_error' });
        }
    }

    const text = await response.text();
    let payload = null;
    if (text) {
        try {
            payload = JSON.parse(text);
        } catch (_) {
            payload = null;
        }
    }

    if (!response.ok) {
        const normalized = normalizeErrorPayload(payload, response.status);
        if (!silent) {
            showToast(normalized.message, { variant: 'error', title: `Error ${response.status}` });
        }
        throw new ApiError(normalized.message, {
            status: response.status,
            code: normalized.code,
            body: payload,
        });
    }

    let data = payload;
    let meta = null;
    if (
        payload &&
        typeof payload === 'object' &&
        !Array.isArray(payload) &&
        'data' in payload &&
        'meta' in payload
    ) {
        data = payload.data; // versioned envelope
        meta = payload.meta ?? {};
        if (payload.error) {
            // 200 with an error envelope: treat as failure.
            const normalized = normalizeErrorPayload(payload, response.status);
            if (!silent) showToast(normalized.message, { variant: 'error', title: 'Request failed' });
            throw new ApiError(normalized.message, {
                status: response.status,
                code: normalized.code,
                body: payload,
            });
        }
    }

    return { response, payload, data, meta };
}

/** GET returning unwrapped data. */
export async function apiGet(path, options = {}) {
    return (await requestRaw(path, { ...options, method: 'GET' })).data;
}

/** POST/PUT/PATCH/DELETE with a JSON-serializable body. */
export async function apiSend(path, body, { method = 'POST', ...options } = {}) {
    return (await requestRaw(path, { ...options, method, body: body ?? null })).data;
}

/**
 * GET for callers that need envelope metadata (e.g. pagination) or top-level
 * siblings of the envelope (e.g. the `links` object on /api/v1/locations):
 * returns `{ data, meta, response, payload }`; `meta` is null for legacy
 * bodies and `payload` is the parsed body as received.
 */
export async function apiGetDetailed(path, options = {}) {
    const { response, payload, data, meta } = await requestRaw(path, { ...options, method: 'GET' });
    return { data, meta, response, payload };
}

const MallaAPI = {
    ApiError,
    get: apiGet,
    send: apiSend,
    getDetailed: apiGetDetailed,
    requestRaw,
};

window.MallaAPI = MallaAPI;
