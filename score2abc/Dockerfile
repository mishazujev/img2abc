# Score2ABC — runs on Hugging Face Spaces (Docker SDK) or any Docker host.
FROM ubuntu:24.04

ARG AUDIVERIS_VERSION=5.11.0
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    TESSDATA_PREFIX=/usr/share/tesseract-ocr/5/tessdata \
    JAVA_TOOL_OPTIONS="-Djava.awt.headless=true" \
    GDK_SCALE=1 \
    AUDIVERIS_BIN=/opt/audiveris/bin/Audiveris \
    PORT=7860

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl python3 python3-venv \
        tesseract-ocr-eng tesseract-ocr-deu tesseract-ocr-fra tesseract-ocr-ita \
        fontconfig fonts-dejavu-core \
        libgtk-3-0t64 xvfb xauth \
    && rm -rf /var/lib/apt/lists/* \
    && ln -sf "$(find /usr/lib -name 'libgtk-3.so.0' | head -n1)" /usr/lib/x86_64-linux-gnu/libgtk-3.so \
    && ln -sf "$(find /usr/lib -name 'libgdk-3.so.0' | head -n1)" /usr/lib/x86_64-linux-gnu/libgdk-3.so

# Audiveris ships a .deb with its own Java runtime. Fall back to the newest
# release if the pinned version's asset is not found. Its post-install script
# registers a desktop menu entry, which fails in a container without menu
# folders, so create them first and, if it still fails, skip that script.
RUN set -eux; \
    url="https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb"; \
    if ! curl -fsSL -o /tmp/audiveris.deb "$url"; then \
        url=$(curl -fsSL https://api.github.com/repos/Audiveris/audiveris/releases/latest \
              | grep -o 'https://[^"]*ubuntu24\.04-x86_64\.deb' | head -n1); \
        curl -fsSL -o /tmp/audiveris.deb "$url"; \
    fi; \
    mkdir -p /etc/xdg/menus /usr/share/applications /usr/share/desktop-directories \
             /usr/share/icons/hicolor /usr/share/mime/packages; \
    apt-get update; \
    if ! apt-get install -y --no-install-recommends /tmp/audiveris.deb; then \
        rm -f /var/lib/dpkg/info/audiveris.postinst; \
        dpkg --configure -a; \
        apt-get install -y -f --no-install-recommends; \
    fi; \
    rm -rf /tmp/audiveris.deb /var/lib/apt/lists/*; \
    test -x "$AUDIVERIS_BIN"

# Hugging Face runs containers as uid 1000
RUN (userdel -r ubuntu 2>/dev/null || true) && useradd -m -u 1000 user
WORKDIR /home/user/app

COPY requirements.txt .
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir -r requirements.txt
ENV PATH=/opt/venv/bin:$PATH

COPY --chown=1000:1000 app ./app
COPY --chown=1000:1000 static ./static

USER 1000
ENV HOME=/home/user JOB_DIR=/home/user/jobs
EXPOSE 7860
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --proxy-headers --forwarded-allow-ips='*'"]
