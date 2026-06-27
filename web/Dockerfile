# Build the static SPA, then serve it with nginx. nginx also reverse-proxies the
# API paths to the client service, so the browser only ever talks to this origin
# (no CORS, no backend changes) — the same shape as the Vite dev-server proxy.
#
# Built with context ./web (see docker-compose.yml), so COPY paths are relative
# to the web/ directory.

# --- build the production bundle ---
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

# --- serve it ---
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
