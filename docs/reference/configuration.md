# Configuration

Environment variables and application settings.

## Environment Variables

All configuration is done via environment variables in a `.env` file.

### Required Variables

```bash
# Database
DATABASE_URL=postgresql+asyncpg://user:password@host:port/database

# Security (generate secure random strings!)
SECRET_KEY=your-secret-key-minimum-32-characters
JWT_SECRET_KEY=your-jwt-secret-minimum-32-characters

# OpenAI (required for QNR generation)
OPENAI_API_KEY=sk-...
```

### Optional Variables

```bash
# Application
ENVIRONMENT=development  # development, staging, production
DEBUG=true              # Enable debug mode
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR, CRITICAL

# Base URL (for email links, Stripe redirects, etc.)
BASE_URL=http://localhost:8000   # Local dev; set to your domain for staging/production
# On Render: RENDER_EXTERNAL_URL is set automatically; app prefers it over BASE_URL
# Custom domain: set BASE_URL to override (e.g. BASE_URL=https://smeme.ai)

# Authentication
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:8000

# Tavily (for agentic QNR generation)
TAVILY_API_KEY=tvly-...

# LangSmith (for observability)
LANGCHAIN_API_KEY=ls__...
LANGCHAIN_PROJECT=smeme-platform
LANGCHAIN_TRACING_V2=true

# Test Database
TEST_DATABASE_URL=postgresql+asyncpg://user:password@host:port/test_db

# Stripe (Sprint 7 - billing)
STRIPE_SECRET_KEY=sk_test_...       # Test mode secret key
STRIPE_WEBHOOK_SECRET=whsec_...     # From Stripe Dashboard or Stripe CLI
STRIPE_PREMIUM_PRICE_ID=price_...   # Premium $29/mo product price ID
```

## Configuration Class

Configuration is managed by Pydantic Settings in `smeme/core/config.py`:

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Application
    app_name: str = "SMEme Platform"
    version: str = "2.0.0"
    environment: str = "development"
    debug: bool = False
    log_level: str = "INFO"
    
    # Database
    database_url: str
    test_database_url: str | None = None
    
    # Security
    secret_key: str
    jwt_secret_key: str
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 30
    
    # OpenAI
    openai_api_key: str
    
    # Tavily (optional)
    tavily_api_key: str | None = None
    
    # LangSmith (optional)
    langchain_api_key: str | None = None
    langchain_project: str = "smeme-platform"
    langchain_tracing_v2: bool = False
    
    # CORS
    allowed_origins: list[str] = ["http://localhost:8000"]
    
    class Config:
        env_file = ".env"
        case_sensitive = False
```

## Generating Secrets

```bash
# Generate SECRET_KEY and JWT_SECRET_KEY
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

## Environment-Specific Configuration

### Development

```bash
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=DEBUG
DATABASE_URL=postgresql+asyncpg://smeme:smeme_dev_password@localhost:5432/smeme_dev
```

### Staging

```bash
ENVIRONMENT=staging
DEBUG=false
LOG_LEVEL=INFO
DATABASE_URL=<neon-dev-branch-url>
```

### Production

```bash
ENVIRONMENT=production
DEBUG=false
LOG_LEVEL=WARNING
DATABASE_URL=<neon-main-branch-url>
LANGCHAIN_TRACING_V2=true
```

## Database Connection Pooling

Connection pool settings are automatically configured based on environment:

- **Development**: 5 connections
- **Staging**: 10 connections
- **Production**: 20 connections

See `smeme/core/database.py` for details.

---

**Next:** [Data Schema](data-schema.md){ .md-button }

