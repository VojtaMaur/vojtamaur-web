# Build explicitly after reviewing this file. Runtime never pulls an image.
# Pin this base to an approved digest for deployments needing reproducibility.
FROM python:3.11-slim
RUN test -x /usr/bin/timeout
WORKDIR /workspace
# Experiments use stdlib by default. Add reviewed tools/dependencies here rather
# than giving a running agent package-install network access.
USER 65534:65534
CMD ["python", "--version"]
