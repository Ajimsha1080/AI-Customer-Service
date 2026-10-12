export const API_BASE = process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';

export function getAuthHeaders(): HeadersInit {
  // Uses httpOnly cookie session; authorization headers only used if explicitly provided
  return {
    'Content-Type': 'application/json',
  };
}

export function authFetch(url: string, init?: RequestInit): Promise<Response> {
  return fetch(url, {
    ...init,
    credentials: 'include',
    headers: {
      ...getAuthHeaders(),
      ...(init?.headers || {}),
    },
  });
}
