# Use uv package manager, ARM64 compatible architecture
FROM --platform=linux/arm64 ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app

# Install build tools for compiling dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements.txt
COPY requirements.txt .

# Use uv pip to install dependencies
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --no-cache -r requirements.txt

# Install AWS OpenTelemetry and boto3 (needed for observability + AWS SDK access)
RUN pip install --no-cache-dir "aws-opentelemetry-distro>=0.10.1" boto3

# Copy only triage runtime source
COPY src/agents/triage_agent/app.py ./src/agents/triage_agent/app.py

# OpenTelemetry Configuration for AgentCore observability
ENV OTEL_SERVICE_NAME=support_triage_agent
ENV OTEL_TRACES_EXPORTER=otlp
ENV OTEL_METRICS_EXPORTER=otlp

# AWS OpenTelemetry Distribution
ENV OTEL_PYTHON_DISTRO=aws_distro
ENV OTEL_PYTHON_CONFIGURATOR=aws_configurator

# Export Protocol
ENV OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf

# Enable Agent Observability
ENV AGENT_OBSERVABILITY_ENABLED=true

# Service Identification
ENV OTEL_TRACES_SAMPLER=always_on
ENV OTEL_RESOURCE_ATTRIBUTES=service.namespace=AgentCore,service.version=1.0

# Expose port
EXPOSE 8080

# Run with OpenTelemetry auto-instrumentation
CMD ["opentelemetry-instrument", "python", "src/agents/triage_agent/app.py"]
