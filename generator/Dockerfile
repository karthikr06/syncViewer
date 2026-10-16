FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY pyproject.toml uv.lock ./
# exact versions from uv.lock
RUN uv export --frozen --no-dev --no-hashes --no-emit-project -o requirements.txt \
 && uv pip install --system --no-cache -r requirements.txt
COPY . .
CMD ["uvicorn", "syncgen.main:app", "--host", "0.0.0.0", "--port", "8100"]
