FROM certbot/certbot:latest

# Install additional tools
RUN apk add --no-cache bash openssl curl redis dcron jq

# Copy scripts
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.sh

# Create directories
RUN mkdir -p /var/www/certbot /etc/letsencrypt /var/log/certbot

# Copy entrypoint
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /

# Override default entrypoint
ENTRYPOINT ["/entrypoint.sh"]
CMD []
