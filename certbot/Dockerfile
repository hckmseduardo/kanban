FROM certbot/certbot:latest

# Install additional tools
RUN apk add --no-cache bash openssl curl

# Copy scripts
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

# Create directories
RUN mkdir -p /var/www/certbot /etc/letsencrypt

WORKDIR /

# Override entrypoint and keep container running
ENTRYPOINT []
CMD ["/bin/sh", "-c", "while true; do sleep 3600; done"]
