# Use Python 3.13 slim image
FROM python:3.13-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV MALLA_HOST=0.0.0.0
ENV MALLA_PORT=5008

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Create app user
RUN groupadd --gid 1000 app && \
    useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash app

# Set working directory
WORKDIR /app

# Copy dependency files and LICENSE (required for package build)
COPY pyproject.toml uv.lock LICENSE ./

# Install dependencies
RUN uv sync --frozen --no-dev

# Copy application source
COPY src/ ./src/
COPY malla-web malla-capture ./
COPY config.sample.yaml ./

# Create data directory for database
RUN mkdir -p /app/data && chown -R app:app /app

# Switch to non-root user
USER app

# Expose port
EXPOSE 5008

# Default command runs the web UI
CMD ["uv", "run", "./malla-web"]
