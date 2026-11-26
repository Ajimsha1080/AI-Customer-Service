export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export function getCsrfToken(): string | null {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(^|;)\s*csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[2].trim()) : null;
}

export function getAuthHeaders(method: string = 'GET'): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  const upperMethod = method.toUpperCase();
  if (['POST', 'PUT', 'PATCH', 'DELETE'].includes(upperMethod)) {
    const csrf = getCsrfToken();
    if (csrf) {
      headers['X-CSRF-Token'] = csrf;
    }
  }
  return headers;
}

let isRefreshing = false;
let refreshSubscribers: (() => void)[] = [];

function subscribeTokenRefresh(cb: () => void) {
  refreshSubscribers.push(cb);
}

function onRefreshed() {
  refreshSubscribers.forEach(cb => cb());
  refreshSubscribers = [];
}

export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const requestUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const method = (init?.method || 'GET').toUpperCase();
  const defaultHeaders = getAuthHeaders(method) as Record<string, string>;
  const headers: Record<string, string> = {
    ...defaultHeaders,
    ...(((init?.headers as Record<string, string>) || {})),
  };

  const response = await fetch(requestUrl, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (response.status === 401 && typeof window !== 'undefined' && !url.includes('/auth/login') && !url.includes('/auth/refresh')) {
    if (!isRefreshing) {
      isRefreshing = true;
      try {
        const csrfToken = getCsrfToken();
        const refreshRes = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
          method: 'POST',
          credentials: 'include',
          headers: {
            'Content-Type': 'application/json',
            ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {})
          },
        });

        if (refreshRes.ok) {
          onRefreshed();
          // Replay original request with rotated cookies
          return fetch(requestUrl, {
            ...init,
            credentials: 'include',
            headers: {
              ...headers,
              ...(getCsrfToken() ? { 'X-CSRF-Token': getCsrfToken()! } : {})
            },
          });
        } else {
          if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/guest')) {
            window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
          }
        }
      } catch {
        // ignore network error
      } finally {
        isRefreshing = false;
      }
    } else {
      return new Promise((resolve) => {
        subscribeTokenRefresh(() => {
          resolve(fetch(requestUrl, {
            ...init,
            credentials: 'include',
            headers: {
              ...headers,
              ...(getCsrfToken() ? { 'X-CSRF-Token': getCsrfToken()! } : {})
            },
          }));
        });
      });
    }
  }

  return response;
}

export async function getCurrentSession(): Promise<any> {
  try {
    const res = await authFetch('/api/v1/auth/me');
    if (res.ok) {
      return await res.json();
    }
  } catch {}
  return null;
}

export async function logout(): Promise<void> {
  try {
    const csrfToken = getCsrfToken();
    await fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/json',
        ...(csrfToken ? { 'X-CSRF-Token': csrfToken } : {})
      }
    });
  } catch {}
  if (typeof window !== 'undefined') {
    window.location.href = '/login';
  }
}
