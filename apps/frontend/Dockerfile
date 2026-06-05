# Frontend (web) image: build the React/Vite SPA, serve it with nginx, and
# reverse-proxy /api and /ws to the `api` service (see nginx.conf). Built from the
# apps/frontend context (see deploy/docker-compose.yml).
FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/templates/default.conf.template
EXPOSE 80
