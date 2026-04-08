FROM python:3.10-slim

WORKDIR /app

# System dependencies for cairocffi / igraph
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc g++ libcairo2-dev pkg-config libigraph-dev && \
    rm -rf /var/lib/apt/lists/*

# Install Python deps first (layer caching)
COPY pyproject.toml ./
RUN pip install --no-cache-dir poetry && \
    poetry config virtualenvs.create false && \
    poetry install --no-interaction --no-ansi --no-root

# Copy application code
COPY . .
RUN pip install --no-cache-dir -e .

# Governance DB will be stored here
RUN mkdir -p /app/data

EXPOSE 8000

CMD ["uvicorn", "oasis.api:app", "--host", "0.0.0.0", "--port", "8000"]
