import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const API_BASE = process.env.INTERNAL_API_URL || process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000';
const JWT_SECRET = process.env.JWT_SECRET_KEY;

async function verifyToken(token: string): Promise<{ sub?: string; role?: string; exp?: number; org_id?: string } | null> {
  // 1. If JWT_SECRET is available, verify cryptographically via Web Crypto HMAC-SHA256
  if (JWT_SECRET) {
    try {
      const parts = token.split('.');
      if (parts.length !== 3) return null;
      const [headerB64, payloadB64, sigB64] = parts;

      const enc = new TextEncoder();
      const key = await crypto.subtle.importKey(
        'raw',
        enc.encode(JWT_SECRET),
        { name: 'HMAC', hash: 'SHA-256' },
        false,
        ['verify']
      );

      const data = enc.encode(`${headerB64}.${payloadB64}`);
      const sigBinaryStr = atob(sigB64.replace(/-/g, '+').replace(/_/g, '/'));
      const sigBytes = new Uint8Array(sigBinaryStr.length);
      for (let i = 0; i < sigBinaryStr.length; i++) {
        sigBytes[i] = sigBinaryStr.charCodeAt(i);
      }

      const isValid = await crypto.subtle.verify('HMAC', key, sigBytes, data);
      if (!isValid) return null;

      const payloadJson = atob(payloadB64.replace(/-/g, '+').replace(/_/g, '/'));
      const payload = JSON.parse(payloadJson);
      if (payload.exp && payload.exp * 1000 < Date.now()) {
        return null;
      }
      return payload;
    } catch {
      return null;
    }
  }

  // 2. Otherwise verify server-side against /api/v1/auth/me to never trust unverified client signatures
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/me`, {
      headers: { 'Authorization': `Bearer ${token}` },
      cache: 'no-store'
    });
    if (!res.ok) return null;
    const userData = await res.json();
    return {
      sub: userData.id,
      role: userData.role,
      org_id: userData.organization_id
    };
  } catch {
    return null;
  }
}

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Legacy route redirect
  if (pathname.startsWith('/dashboard')) {
    return NextResponse.redirect(new URL('/app/dashboard', request.url));
  }

  // Guest widget routes are public
  if (pathname.startsWith('/guest')) {
    return NextResponse.next();
  }

  // Protected paths: /platform/* and /app/*
  const sessionToken = request.cookies.get('session_token')?.value || request.cookies.get('access_token')?.value;

  if (!sessionToken) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(loginUrl);
  }

  // Strictly verify token cryptographically or via server
  const session = await verifyToken(sessionToken);
  if (!session || !session.sub) {
    const response = NextResponse.redirect(new URL('/login', request.url));
    response.cookies.delete('session_token');
    response.cookies.delete('access_token');
    return response;
  }

  const role = session.role || 'VIEWER';

  // 1. STRICT ROUTE GUARD: Platform Super Admin (/platform/*)
  if (pathname.startsWith('/platform')) {
    if (role !== 'SUPER_ADMIN') {
      return NextResponse.redirect(new URL('/app/dashboard', request.url));
    }
  }

  // 2. STRICT ROUTE GUARD: Organization Hospitality SaaS UI (/app/*)
  if (pathname.startsWith('/app')) {
    if (role === 'GUEST') {
      return NextResponse.redirect(new URL('/login', request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/platform/:path*', '/app/:path*', '/guest/:path*']
};
