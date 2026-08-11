import os, shutil

base = '/Users/carlmihanjo/Documents/My Projects/tenant_systems'

mig_dirs = [
    'properties/migrations',
    'tenants/migrations', 
    'bookings/migrations',
    'payments/migrations',
    'notifications/migrations',
]
for d in mig_dirs:
    path = os.path.join(base, d)
    for f in os.listdir(path):
        if f != '__init__.py' and f.endswith('.py'):
            os.remove(os.path.join(path, f))
        if f.endswith('.pyc'):
            os.remove(os.path.join(path, f))
    pycache = os.path.join(path, '__pycache__')
    if os.path.exists(pycache):
        shutil.rmtree(pycache)

db = os.path.join(base, 'db.sqlite3')
if os.path.exists(db):
    os.remove(db)
print('Database and migrations reset.')
