# One image for the API, the worker and the UI; docker-compose.yml picks the command.
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app

# install dependencies first, so code changes don't reinstall them
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY ui ./ui
COPY web ./web
COPY templates ./templates
COPY samples ./samples
COPY evaluation ./evaluation
COPY .streamlit ./.streamlit
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000 8501
CMD ["uvicorn", "sensedoc.api:app", "--host", "0.0.0.0", "--port", "8000"]
