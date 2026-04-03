/**
 * api.js — Centralized API call utility with CSRF handling
 */

async function apiCall(url, options = {}) {
    const csrfToken = document.querySelector('meta[name="csrf-token"]')?.getAttribute('content');

    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    if (csrfToken && options.method && options.method !== 'GET') {
        headers['X-CSRFToken'] = csrfToken;
    }

    const response = await fetch(url, { ...options, headers });
    const data = await response.json();

    if (!response.ok) {
        const message = data.error?.message || data.error || data.message || 'Request failed';
        throw new Error(message);
    }

    return data;
}
