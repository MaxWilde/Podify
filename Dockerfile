FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    autoconf \
    automake \
    build-essential \
    ca-certificates \
    ffmpeg \
    git \
    libavcodec-dev \
    libavfilter-dev \
    libavformat-dev \
    libavutil-dev \
    libglib2.0-dev \
    libgpod-dev \
    libjson-c-dev \
    libsqlite3-dev \
    libswresample-dev \
    libswscale-dev \
    libtool \
    pkg-config \
    && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 https://github.com/MaxWilde/gpod-utils /tmp/gpod-utils \
    && cd /tmp/gpod-utils \
    && autoreconf --install \
    && autoconf \
    && ./configure \
    && make -j"$(nproc)" \
    && make install \
    && command -v gpod-ls >/dev/null \
    && rm -rf /tmp/gpod-utils

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN set -eux; \
    GPOD_PC=""; \
    for candidate in gpod-1.0 libgpod libgpod-1.0 gpod; do \
      if pkg-config --exists "$candidate"; then GPOD_PC="$candidate"; break; fi; \
    done; \
    if [ -z "$GPOD_PC" ]; then \
      GPOD_PC="$(pkg-config --list-all | awk '{print $1}' | grep -Ei '(^|-)gpod' | head -n1 || true)"; \
    fi; \
    if [ -z "$GPOD_PC" ]; then \
      echo "No libgpod pkg-config entry found."; \
      pkg-config --list-all | grep -Ei 'gpod|glib' || true; \
      exit 1; \
    fi; \
    CFLAGS="$(pkg-config --cflags "$GPOD_PC" glib-2.0)"; \
    LIBS="$(pkg-config --libs "$GPOD_PC" glib-2.0)"; \
    gcc -O2 -Wall -Wextra -std=c11 $CFLAGS -o /usr/local/bin/gpod-playlistctl /app/tools/gpod-playlistctl.c $LIBS; \
    /usr/local/bin/gpod-playlistctl --help >/dev/null || true

EXPOSE 8080

CMD ["sh", "-c", "gunicorn --bind ${APP_HOST:-0.0.0.0}:${APP_PORT:-8080} --workers ${GUNICORN_WORKERS:-2} --timeout ${GUNICORN_TIMEOUT:-180} --graceful-timeout ${GUNICORN_GRACEFUL_TIMEOUT:-30} app:app"]
