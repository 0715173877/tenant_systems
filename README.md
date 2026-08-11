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

## Quick Start
```bash
cp .env.example .env   # configure DB, SMS, etc.
docker compose up -d   # starts db, redis, web, celery_worker
```
# tenant_systems
