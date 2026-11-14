# College Data Portal on Cloud Run (project billing-f4fe3, service "college-portal", asia-south1).
# The unchanged Node server (proxy mode: PORTAL_PROXY_SECRET) + Litestream 0.3.13 replicating the SQLite DB to
# gs://$LITESTREAM_BUCKET/db. Reached only through the LMS function lmsApi (Hosting /college-portal/**), which checks the
# LMS admin session and adds x-td-proxy-secret / -user / -role. Build: deploy/cloudbuild.yaml (Cloud Build, never local).
# The VM stack keeps using ../Dockerfile.
FROM litestream/litestream:0.3.13 AS litestream

FROM node:24-slim
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*
COPY --from=litestream /usr/local/bin/litestream /usr/local/bin/litestream
WORKDIR /app
COPY package.json ./
COPY server ./server
COPY public ./public
COPY deploy/litestream.yml /etc/litestream.yml
COPY deploy/entrypoint.sh /app/entrypoint.sh
COPY deploy/fetch_seed.mjs /app/fetch_seed.mjs
RUN chmod +x /app/entrypoint.sh && mkdir -p /data && chown node:node /data
ENV NODE_ENV=production PORT=8080 HOST=0.0.0.0 DB_PATH=/data/techdrona.db TRUST_PROXY=1 TZ=Asia/Kolkata
USER node
EXPOSE 8080
CMD ["/app/entrypoint.sh"]
