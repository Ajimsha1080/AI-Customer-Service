import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

function decodeJwtPayload(token: string): { sub?: string; role?: string; exp?: number; org_id?: string } | null {
  try {
    const parts = token.split('.');
    if (parts.length !== 3) return null;
    const base64Url = parts[1];
    const base64 = base64Url.replace(/-/g, '+').replace(/_/g, '/');
    const jsonPayload = Buffer.from(base64, 'base64').toString('utf-8');
    const parsed = JSON.parse(jsonPayload);
    // Expiration check
    if (parsed.exp && parsed.exp * 1000 < Date.now()) {
      return null;
    }
    return parsed;
  } catch {
    return null;
  }
}

export function middleware(request: NextRequest) {
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
  // Default-Deny: require server-set session token from httpOnly cookie
  const sessionToken = request.cookies.get('session_token')?.value || request.cookies.get('access_token')?.value;

  if (!sessionToken) {
    // Unauthenticated -> redirect to login (default-deny)
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('redirect', pathname);
    return NextResponse.redirect(loginUrl);
  }

  const session = decodeJwtPayload(sessionToken);
  if (!session || !session.sub) {
    // Invalid or expired token -> clear cookie & redirect to login
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
      return NextResponse.redirect(new URL('/guest/agt_concierge_01', request.url));
    }
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/platform/:path*', '/app/:path*', '/guest/:path*']
};
