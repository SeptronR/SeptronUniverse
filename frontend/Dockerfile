# SeptronUniverse web (SPA) image — Prompts/44 §44.6 docker 2. The public site is server-rendered by the API
# (Phase 40 decision), so there is no separate Node SSR service; nginx serves dist/ and proxies /api, /ws, /site.
# Build: docker build --build-arg MODE=production --build-arg VITE_API_URL=/api/v1 -t ghcr.io/septronr/universe-web:<tag> frontend/

FROM node:20-alpine AS build
ARG MODE=production
ARG VITE_API_URL=/api/v1
ENV VITE_API_URL=${VITE_API_URL}
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts
COPY . .
RUN npm run build -- --mode ${MODE}

FROM nginx:1.27-alpine
COPY --from=build /src/dist /usr/share/nginx/html
COPY docker/nginx-spa.conf /etc/nginx/conf.d/default.conf
HEALTHCHECK --interval=30s --timeout=3s CMD wget -qO- http://localhost/healthz || exit 1
EXPOSE 80
