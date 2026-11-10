# Research Hub server. The dashboard is prebuilt in research_hub/ui, so the image needs only Python.
FROM python:3.12-slim
RUN useradd --create-home --uid 10001 hub && mkdir /data && chown hub:hub /data
WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY research_hub ./research_hub
RUN pip install --no-cache-dir .
COPY deploy/docker-entrypoint.sh /usr/local/bin/
ENV HUB_HOME=/data HUB_HOST=0.0.0.0 HUB_PORT=6230 HOME=/tmp
VOLUME /data
EXPOSE 6230
HEALTHCHECK --interval=30s --timeout=3s --start-period=60s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:6230/api/health', timeout=2)"
# Starts as root only to find out who owns /data, then drops to that user (or to `hub`) before the server runs.
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["hub", "serve"]
