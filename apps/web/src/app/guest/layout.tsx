import React from 'react';

export const metadata = {
  title: 'AI Concierge - Guest Portal',
  description: 'Instant 24/7 guest support for room bookings, amenities, dining, and local activities.',
};

export default function GuestLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="bg-slate-950 text-slate-100 font-sans antialiased min-h-screen">
        {children}
      </body>
    </html>
  );
}
