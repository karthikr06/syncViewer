# ---- build ----
FROM node:20-alpine AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
# Public, build-time values (the anon key is public by design; the data API is locked server-side)
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ARG VITE_API_URL
ARG VITE_ENABLE_GOOGLE_AUTH=false
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY \
    VITE_API_URL=$VITE_API_URL \
    VITE_ENABLE_GOOGLE_AUTH=$VITE_ENABLE_GOOGLE_AUTH
RUN npm run build

# ---- serve ----
FROM nginx:1.27-alpine
# nginx renders /etc/nginx/templates/*.template with env vars at start-up
ENV CSP_CONNECT_SRC="'self'"
COPY nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
