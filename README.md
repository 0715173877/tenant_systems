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
- Rent invoicing with arrears / aging reporting
- **Progressive Web App (PWA)** – installable/launchable as a native app with offline support

## Data isolation (multi-landlord) — mandatory

Every landlord (`owner`) must only ever see and act on **their own** data.
This is enforced centrally in `properties/access.py` and **any new feature
must follow the same pattern**:

| Rule | How |
|------|-----|
| Scope class-based views | Subclass `properties.access.PropertyScopedMixin` (or `LoginRequiredMixin` + it) and set `property_filter` to the ORM lookup that reaches `Property`, e.g. `"lease__unit__block__property__in"`. |
| Scope function views / object lookups | Use `get_accessible_properties(request.user)` (or `get_accessible_property_ids`) as a queryset filter, **never** bare `Model.objects...`. |
| Foreign keys | Every record must trace back to a `Property` (via `unit__block__property` or an `owner` FK) so it can be filtered. |
| Admin | Django admin is superuser-only (`{% if request.user.is_superuser %}` in `base.html`); landlord-facing screens must not rely on it. |

Access rules: superuser → all properties · `owner` group → properties they own
(`Property.owner`) · other staff → properties they are actively assigned to via
`PropertyStaff` · anonymous → nothing.

**Tenants always belong to a property.** `Tenant.property` is **required**
(non-null), so every tenant is reachable by its property's owner *and* that
owner's staff (manager / receptionist / accountant). It must never be `NULL`:
scoping filters use `property__in=<accessible properties>`, and SQL `IN` never
matches `NULL`, so a detached tenant would be invisible to everyone (even
superusers) — exactly the bug fixed by migration
`0003_backfill_tenant_property` + `0004_alter_tenant_property`.

When adding a feature, add a regression test proving landlord A cannot list,
open (404), or mutate landlord B's records (see `tenants/tests.py` for examples).


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
