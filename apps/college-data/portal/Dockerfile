# Tech Drona college data portal — image for the Tech Drona LMS stack.
# The LMS (Next.js) serves it under /college-portal/ through an authenticated proxy (PORTAL_PROXY_SECRET, see README.md
# "Running inside the Tech Drona LMS"). Zero npm dependencies: Node 24 + node:sqlite. The database lives in the /data volume.
FROM node:24-slim
ENV NODE_ENV=production PORT=4173 HOST=0.0.0.0 DB_PATH=/data/techdrona.db TRUST_PROXY=1 LIVE_DISABLED=0
WORKDIR /app
COPY --chown=node:node package.json ./
COPY --chown=node:node server ./server
COPY --chown=node:node public ./public
RUN mkdir -p /data && chown node:node /data
VOLUME /data
USER node
EXPOSE 4173
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD ["node", "-e", "fetch('http://127.0.0.1:4173/api/health').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]
CMD ["node", "server/server.js"]
