FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src

FROM base AS test
RUN pip install ".[dev]"
COPY tests ./tests
COPY evals ./evals
CMD ["sh", "-c", "ruff check src tests evals && ruff format --check src tests evals && pytest -v"]

FROM base AS evals
RUN pip install .
COPY evals ./evals
CMD ["python", "-m", "evals.run"]

FROM base AS runtime
RUN pip install . && useradd --create-home --uid 10001 app
USER app
EXPOSE 8000 8001
CMD ["uvicorn", "zapagent.entrypoints.api:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
