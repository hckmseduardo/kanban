FROM mcr.microsoft.com/playwright:v1.40.0-jammy

WORKDIR /app

# Copy package files
COPY package.json ./

# Install dependencies
RUN npm install

# Install Playwright browsers
RUN npx playwright install chromium

# Copy test files
COPY . .

# Create results directory
RUN mkdir -p /app/results

# Set environment variables
ENV PORTAL_URL=https://app.localhost:4443
ENV PORTAL_API_URL=https://api.localhost:4443
ENV NODE_TLS_REJECT_UNAUTHORIZED=0

# Run tests
CMD ["npx", "playwright", "test", "--reporter=list"]
