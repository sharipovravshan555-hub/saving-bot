FROM node:24-bookworm-slim AS pot-builder

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY bgutil-localhost.patch .
RUN git clone --depth 1 --single-branch --branch 1.3.1 \
        https://github.com/Brainicism/bgutil-ytdlp-pot-provider.git provider \
    && git -C provider apply /build/bgutil-localhost.patch

WORKDIR /build/provider/server
RUN npm ci && npx tsc


FROM python:3.13-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR=/app/data
ENV YTDLP_NODE_EXECUTABLE=/usr/local/bin/node
ENV YTDLP_POT_SERVER_HOME=/app/vendor/bgutil-ytdlp-pot-provider/server

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        ffmpeg \
        libcairo2 \
        libgif7 \
        libjpeg62-turbo \
        libpango-1.0-0 \
        librsvg2-2 \
        libstdc++6 \
    && rm -rf /var/lib/apt/lists/*

COPY --from=pot-builder /usr/local/bin/node /usr/local/bin/node

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY --from=pot-builder /build/provider /app/vendor/bgutil-ytdlp-pot-provider
COPY . .

RUN useradd --create-home --uid 10001 botuser \
    && mkdir -p /app/data /app/tmp \
    && chown -R botuser:botuser /app

USER botuser

CMD ["python", "bot.py"]
