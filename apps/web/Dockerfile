# Imagen de producción de la interfaz: construye la SPA y la sirve con Caddy, que además termina
# TLS y hace de proxy hacia la API (ver deploy/Caddyfile, montado en tiempo de ejecución).

FROM node:22-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .

# Las variables VITE_* se hornean en el JavaScript al construir: no se pueden cambiar después
# sin reconstruir. `vite.config.ts` cancela la build si falta alguna obligatoria (sin
# VITE_API_BASE_URL la app arrancaría en modo demo, con datos inventados).
ARG VITE_API_BASE_URL
ARG VITE_FIREBASE_API_KEY
ARG VITE_FIREBASE_AUTH_DOMAIN
ARG VITE_FIREBASE_PROJECT_ID
ARG VITE_FIREBASE_APP_ID
ARG VITE_FIREBASE_MESSAGING_SENDER_ID
ARG VITE_FIREBASE_STORAGE_BUCKET
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL \
    VITE_FIREBASE_API_KEY=$VITE_FIREBASE_API_KEY \
    VITE_FIREBASE_AUTH_DOMAIN=$VITE_FIREBASE_AUTH_DOMAIN \
    VITE_FIREBASE_PROJECT_ID=$VITE_FIREBASE_PROJECT_ID \
    VITE_FIREBASE_APP_ID=$VITE_FIREBASE_APP_ID \
    VITE_FIREBASE_MESSAGING_SENDER_ID=$VITE_FIREBASE_MESSAGING_SENDER_ID \
    VITE_FIREBASE_STORAGE_BUCKET=$VITE_FIREBASE_STORAGE_BUCKET \
    VITE_DEMO_CONTROLS=false
RUN npm run build

FROM caddy:2-alpine
COPY --from=build /app/dist /srv/web
