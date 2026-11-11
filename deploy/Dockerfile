FROM python:3.11-bookworm

ARG GIT_COMMIT
ARG RELEASE_ID
ARG BUILD_TIME
LABEL org.opencontainers.image.revision=$GIT_COMMIT \
      org.opencontainers.image.version=$RELEASE_ID \
      org.opencontainers.image.created=$BUILD_TIME

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TMPDIR=/var/lib/clinagent/tmp \
    CLINAGENT_BUILD_GIT_COMMIT=$GIT_COMMIT \
    CLINAGENT_RELEASE_ID=$RELEASE_ID \
    CLINAGENT_BUILD_TIME=$BUILD_TIME \
    PATH=/opt/venv/bin:$PATH \
    HOME=/tmp

COPY dist/*.whl /tmp/wheels/
COPY deploy/entrypoint.sh /opt/entrypoint.sh
RUN test -n "$GIT_COMMIT" && test -n "$RELEASE_ID" && test -n "$BUILD_TIME" \
    && python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir /tmp/wheels/*.whl 'SimpleITK>=2.3.0' \
    && /opt/venv/bin/pip check \
    && /opt/venv/bin/python -c "import clinagent, pathlib, shutil; shutil.copytree(pathlib.Path(clinagent.__file__).parent, '/opt/model-code/clinagent')" \
    && rm -rf /tmp/wheels

WORKDIR /var/lib/clinagent
USER 10001:10001
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=45s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4)"
CMD ["python", "-m", "clinagent", "--serve", "--port", "8000"]
ENTRYPOINT ["sh", "/opt/entrypoint.sh"]
