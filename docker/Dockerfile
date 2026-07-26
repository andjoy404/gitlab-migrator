FROM python:3.13-slim

ARG USER_ID=1000
ARG GROUP_ID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    GITLAB_MIGRATOR_OUTPUT_DIR=/data/reports \
    GITLAB_MIGRATOR_WORKSPACE_DIR=/data/repositories

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates git git-lfs openssh-client skopeo tini \
    && rm -rf /var/lib/apt/lists/* \
    && git lfs install --system

RUN groupadd --gid "${GROUP_ID}" migrator \
    && useradd --uid "${USER_ID}" --gid "${GROUP_ID}" --create-home migrator \
    && mkdir -p /data/reports /data/repositories /data/keys \
    && chown -R migrator:migrator /data

WORKDIR /opt/gitlab-migrator
COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir .

COPY docker/entrypoint.sh /usr/local/bin/gitlab-migrator-entrypoint
RUN chmod 0755 /usr/local/bin/gitlab-migrator-entrypoint

USER migrator
WORKDIR /data

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/gitlab-migrator-entrypoint"]
CMD ["--help"]
