# One image for Azure: the API with the demo cloud mounted at /gen. Build from the repo root:
#   docker build -f deploy/azure/Dockerfile .
FROM python:3.12-slim
WORKDIR /srv/backend
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock ./
# exact versions from uv.lock (they include everything the generator needs)
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o /tmp/requirements.txt \
 && uv pip install --system --no-cache -r /tmp/requirements.txt
COPY backend/ ./
COPY generator/syncgen /srv/generator/syncgen
ENV PYTHONPATH=/srv/generator
EXPOSE 8000
CMD ["uvicorn", "app.combined:create_combined_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
