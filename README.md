# Tenant Systems

A full-stack property management system built with Django + Bootstrap 5 + HTMX.

## Features
- Property, Block, Unit hierarchy management
- Long-term tenant & lease management with PDF generation
- Short-term booking system with availability calendar
- Payment tracking & financial reporting
- SMS notifications via Beem Africa API
- Celery async task processing
- Staff role management (owner, manager, receptionist, accountant)
- **Progressive Web App (PWA)** – installable/launchable as a native app with offline support

## PWA (Progressive Web App)

This project is a Progressive Web App, so it can be **saved to your home screen and opened like a native app** (on desktop & mobile), with offline-capable caching.

### How to use
1. Serve the site over **HTTPS** (or `localhost` during development).
2. Open the app in Chrome, Edge, Safari, or Firefox.
3. Click the **Install App** button in the top navigation bar (or use the browser's native "Install" option in the address bar).
4. On iOS Safari: tap **Share → Add to Home Screen**.

### Files
| File | Purpose |
|------|---------|
| `static/manifest.webmanifest` | App name, icons, colors, start URL, display mode |
| `static/sw.js` | Service worker – caches the app shell & runtime assets |
| `static/js/pwa.js` | Registers the service worker, handles install prompt & updates |
| `static/img/icons/*.png` | PWA icons (72–512px, incl. maskable) |

### Notes for production
- The service worker and manifest are only registered over `HTTPS` (except `localhost`).
- When you change the app shell, bump the `CACHE_NAME` in `static/sw.js` (e.g. `tenant-systems-v2`) so clients pick up updates.
- Generated icons are derived from `static/img/logo.png` — regenerate if you change the logo (requires Pillow):
  ```bash
  mkdir -p static/img/icons
  python -c "..." # or re-run the icon generation script
  ```

## Quick Start
```bash
cp .env.example .env   # configure DB, SMS, etc.
docker compose up -d   # starts db, redis, web, celery_worker
```
# tenant_systems
