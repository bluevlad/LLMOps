# --- Stage 1: build ---
FROM node:20-alpine AS build

WORKDIR /app

COPY package.json ./
RUN npm install

COPY . .

# Vite 는 빌드 타임에 import.meta.env.VITE_* 를 치환한다.
# build context 가 ./frontend 라 루트 .env 가 들어오지 않으므로
# compose 에서 build arg 로 넘겨 process.env 로 주입한다.
ARG VITE_GOOGLE_CLIENT_ID
ARG VITE_API_BASE_URL
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm run build

# --- Stage 2: runtime ---
FROM nginx:1.27-alpine AS runtime

COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 4110

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD wget -q --spider http://localhost:4110/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
