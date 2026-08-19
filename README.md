# Studio Booking Backend

A Django REST Framework backend for managing boutique fitness studio bookings.

The system supports:

- Studios and studio configuration
- Fitness classes
- STAFF and MEMBER authentication/authorization
- Credit packs and credit balances
- Credit transaction history
- Historical credit balances
- Class bookings
- Booking idempotency
- Booking cancellation
- Waitlists
- Affordability-aware waitlist promotion
- Concurrency-safe booking behavior
- End-to-end integration tests
- Docker Compose development environment
- GitHub Actions CI
- Ruff linting

---

## 1. Technology Stack

- Python 3.13
- Django 5.2.5
- Django REST Framework 3.16.1
- PostgreSQL 16
- psycopg 3.2.9
- Docker / Docker Compose
- Ruff
- mypy / django-stubs available as development dependencies
- GitHub Actions

The current development and Docker environment uses Python 3.13.

---

## 2. Project Structure

```text
studio-booking/
├── apps/
│   ├── accounts/
│   │   ├── models.py
│   │   ├── permissions.py
│   │   ├── serializers.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   └── views.py
│   │
│   ├── studios/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   ├── validators.py
│   │   └── views.py
│   │
│   ├── classes/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   └── views.py
│   │
│   ├── credits/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── services.py
│   │   ├── tests.py
│   │   ├── urls.py
│   │   ├── api_urls.py
│   │   └── views.py
│   │
│   ├── bookings/
│   │   ├── models.py
│   │   ├── serializers.py
│   │   ├── services.py
│   │   ├── tests.py
│   │   ├── test_e2e.py
│   │   ├── urls.py
│   │   └── views.py
│   │
│   └── waitlist/
│       ├── models.py
│       ├── serializers.py
│       ├── services.py
│       ├── tests.py
│       ├── urls.py
│       └── views.py
│
├── config/
│   ├── settings.py
│   ├── urls.py
│   ├── asgi.py
│   └── wsgi.py
│
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── requirements-dev.txt
├── pyproject.toml
├── manage.py
└── README.md