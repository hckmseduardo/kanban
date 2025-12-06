# Build stage
FROM node:20-alpine AS builder

WORKDIR /app

# Build arguments for Vite environment variables
ARG VITE_API_URL=https://localhost/api
ARG VITE_DOMAIN=localhost
ARG VITE_PORT=443

# Set environment variables for build
ENV VITE_API_URL=$VITE_API_URL
ENV VITE_DOMAIN=$VITE_DOMAIN
ENV VITE_PORT=$VITE_PORT

# Install dependencies
COPY package*.json ./
RUN npm install

# Copy source and build
COPY . .
RUN npm run build

# Production stage
FROM nginx:alpine

# Copy built assets
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Expose port
EXPOSE 80

# Health check (use 127.0.0.1 instead of localhost for IPv4)
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD wget --no-verbose --tries=1 --spider http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]
