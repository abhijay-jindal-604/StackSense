# Optional: the engine needs only Python 3.10+; Docker is a convenience path (README "Run with Docker").
FROM python:3.12-slim
WORKDIR /app
COPY stacksense ./stacksense
COPY scenarios ./scenarios
COPY tools ./tools
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8765
CMD ["python", "-m", "stacksense", "serve", "--host", "0.0.0.0", "--port", "8765"]
