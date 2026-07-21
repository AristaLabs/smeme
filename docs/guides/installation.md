# Installation

Detailed installation instructions for SMEme Platform v2.0.

For a quick start guide, see [Getting Started](getting-started.md).

## System Requirements

### Operating System
- **macOS** 10.15+ (Catalina or later)
- **Linux** - Ubuntu 20.04+, Debian 11+, or similar
- **Windows** - Windows 10+ with WSL2

### Software Requirements
- **Python** 3.13 or later
- **Docker** 20.10+ and Docker Compose 2.0+
- **Git** 2.30+
- **4GB RAM** minimum (8GB recommended)
- **2GB disk space** for dependencies and databases

## Installing Python 3.13

### macOS (using Homebrew)

```bash
brew install python@3.13
```

### Ubuntu/Debian

```bash
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install python3.13 python3.13-venv python3.13-dev
```

### Windows (WSL2)

```bash
# In WSL2 terminal
sudo apt update
sudo apt install python3.13 python3.13-venv python3.13-dev
```

## Installing uv (Package Manager)

```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or using pip
pip install uv

# Verify installation
uv --version
```

## Installing Docker

### macOS

Download [Docker Desktop for Mac](https://www.docker.com/products/docker-desktop/)

### Linux

```bash
# Ubuntu/Debian
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Start Docker
sudo systemctl start docker
sudo systemctl enable docker
```

### Windows

Download [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) (requires WSL2)

## Project Setup

### 1. Clone Repository

```bash
git clone https://github.com/yourusername/smeme_v2.git
cd smeme_v2
```

### 2. Install Dependencies

```bash
# Private monorepo: development tools + hosted overlay adapters
uv sync --extra dev --extra saas

# Verify installation
uv run python --version
```

### 3. Start Databases

```bash
# Start PostgreSQL containers
docker-compose up -d

# Verify containers are running
docker ps
```

### 4. Configure Environment

Create `.env` file (see [Getting Started](getting-started.md#4-configure-environment) for full example):

```bash
cp .env.example .env  # If example exists
# Or create manually
```

### 5. Apply Migrations

```bash
uv run alembic upgrade head
```

### 6. Start Development Server

```bash
make dev
```

Visit [http://localhost:8000](http://localhost:8000)

## Verification

Run these commands to verify your installation:

```bash
# Check Python version
python --version  # Should be 3.13+

# Check uv
uv --version

# Check Docker
docker --version
docker-compose --version

# Check databases
docker ps | grep postgres

# Check API
curl http://localhost:8000/api/v1/health
```

## Optional Tools

### PostgreSQL Client (psql)

```bash
# macOS
brew install postgresql

# Ubuntu/Debian
sudo apt install postgresql-client

# Access dev database
psql postgresql://smeme:smeme_dev_password@localhost:5432/smeme_dev
```

### Database GUI

- **pgAdmin** - [Download](https://www.pgadmin.org/download/)
- **DBeaver** - [Download](https://dbeaver.io/download/)
- **DataGrip** - [JetBrains](https://www.jetbrains.com/datagrip/)

### IDE/Editor

- **VS Code** with Python extension
- **PyCharm** Professional or Community
- **Cursor** (AI-powered IDE)

## Troubleshooting

### uv command not found

```bash
# Add to PATH
export PATH="$HOME/.cargo/bin:$PATH"

# Or reinstall
curl -LsSf https://astral.sh/uv/install.sh | sh
```

### Docker permission denied

```bash
# Linux only
sudo usermod -aG docker $USER
# Log out and back in
```

### Port already in use

```bash
# Find process using port 8000
lsof -i :8000  # macOS/Linux
netstat -ano | findstr :8000  # Windows

# Kill process or use different port
uvicorn smeme.main:app --port 8001
```

### Database connection failed

```bash
# Check if containers are running
docker ps

# Restart containers
docker-compose restart

# Check logs
docker-compose logs postgres
```

## Next Steps

- [Getting Started Guide](getting-started.md) - Complete setup walkthrough
- [Architecture Overview](../architecture/overview.md) - Understand the system
- [Contributing Guide](../contributing/) - Development guidelines

---

**Installation complete?** → [Getting Started](getting-started.md){ .md-button .md-button--primary }

