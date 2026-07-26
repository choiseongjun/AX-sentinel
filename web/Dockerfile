FROM node:22-alpine AS build

WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
ENV NGINX_ENVSUBST_OUTPUT_DIR=/usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY ax-config.js.template /etc/nginx/templates/ax-config.js.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
