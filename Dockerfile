FROM python:3.12-slim

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy dependency files and install
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --frozen --no-install-project

# Copy source and install project
COPY src/ src/
RUN uv sync --no-dev --frozen

VOLUME /app/data

CMD [".venv/bin/python", "-m", "newspulse"]
