export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export function getAuthHeaders(): HeadersInit {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('token') || localStorage.getItem('access_token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }
  return headers;
}

let isRefreshing = false;
let refreshSubscribers: ((token: string) => void)[] = [];

function subscribeTokenRefresh(cb: (token: string) => void) {
  refreshSubscribers.push(cb);
}

function onRefreshed(token: string) {
  refreshSubscribers.forEach(cb => cb(token));
  refreshSubscribers = [];
}

export async function authFetch(url: string, init?: RequestInit): Promise<Response> {
  const requestUrl = url.startsWith('http') ? url : `${API_BASE}${url}`;
  const headers: Record<string, string> = {
    ...((getAuthHeaders() as Record<string, string>) || {}),
    ...(((init?.headers as Record<string, string>) || {})),
  };

  const response = await fetch(requestUrl, {
    ...init,
    credentials: 'include',
    headers,
  });

  if (response.status === 401 && typeof window !== 'undefined' && !url.includes('/auth/login') && !url.includes('/auth/refresh')) {
    const refreshToken = localStorage.getItem('refresh_token');
    if (refreshToken) {
      if (!isRefreshing) {
        isRefreshing = true;
        try {
          const refreshRes = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
            method: 'POST',
            credentials: 'include',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: refreshToken }),
          });

          if (refreshRes.ok) {
            const data = await refreshRes.json();
            if (data.access_token) {
              localStorage.setItem('token', data.access_token);
              localStorage.setItem('access_token', data.access_token);
              if (data.refresh_token) {
                localStorage.setItem('refresh_token', data.refresh_token);
              }
              onRefreshed(data.access_token);
              headers['Authorization'] = `Bearer ${data.access_token}`;
              return fetch(requestUrl, {
                ...init,
                credentials: 'include',
                headers,
              });
            }
          } else {
            localStorage.removeItem('token');
            localStorage.removeItem('access_token');
            localStorage.removeItem('refresh_token');
            if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/guest')) {
              window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
            }
          }
        } catch {
          // ignore
        } finally {
          isRefreshing = false;
        }
      } else {
        return new Promise((resolve) => {
          subscribeTokenRefresh((newToken: string) => {
            headers['Authorization'] = `Bearer ${newToken}`;
            resolve(fetch(requestUrl, {
              ...init,
              credentials: 'include',
              headers,
            }));
          });
        });
      }
    } else {
      if (!window.location.pathname.startsWith('/login') && !window.location.pathname.startsWith('/guest') && !window.location.pathname.startsWith('/status')) {
        window.location.href = `/login?redirect=${encodeURIComponent(window.location.pathname)}`;
      }
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
    const refreshToken = typeof window !== 'undefined' ? localStorage.getItem('refresh_token') : null;
    await authFetch('/api/v1/auth/logout', {
      method: 'POST',
      body: JSON.stringify({ refresh_token: refreshToken || undefined })
    });
  } catch {}
  if (typeof window !== 'undefined') {
    localStorage.removeItem('token');
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    window.location.href = '/login';
  }
}
