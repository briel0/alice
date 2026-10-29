FROM python:3.14-slim

# Instala ferramentas básicas e uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copia dependências primeiro para cache do Docker
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copia o código da aplicação
COPY . .

# Garante que logs em stdout saiam sem buffer
ENV PYTHONUNBUFFERED=1

CMD ["uv", "run", "python", "main.py"]
