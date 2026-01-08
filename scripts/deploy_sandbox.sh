#!/bin/bash
# Sandbox Deployment Script
# Deploys code changes to sandbox containers

SANDBOX_SLUG="$1"

if [ -z "$SANDBOX_SLUG" ]; then
    echo "Usage: $0 <sandbox-slug>"
    echo "Example: $0 accountability-initial-implementation"
    exit 1
fi

echo "🚀 Deploying sandbox: $SANDBOX_SLUG"

# Extract workspace from sandbox slug (everything before last hyphen + word)
WORKSPACE=$(echo "$SANDBOX_SLUG" | sed 's/-[^-]*-[^-]*$//')

echo "  Workspace: $WORKSPACE"
echo "  Sandbox: $SANDBOX_SLUG"

# Check if containers exist
if ! docker ps -a --format '{{.Names}}' | grep -q "^${SANDBOX_SLUG}-api$"; then
    echo "❌ Error: Sandbox containers not found"
    exit 1
fi

# Pull latest code in the mounted volume
echo "📥 Pulling latest code..."
cd "/Volumes/dados/projects/kanban/data/workspaces/$WORKSPACE/app" || exit 1

# Checkout sandbox branch
git fetch --all
git checkout "sandbox/$SANDBOX_SLUG"
git pull origin "sandbox/$SANDBOX_SLUG" || echo "  (Branch may not be on remote yet)"

# Restart API container (this will reload the code)
echo "🔄 Restarting API container..."
docker restart "${SANDBOX_SLUG}-api"

# Check if web needs rebuild or just restart
echo "🔄 Restarting web container..."
docker restart "${SANDBOX_SLUG}-web"

# Wait for containers to be healthy
echo "⏳ Waiting for containers to be ready..."
sleep 5

# Check health
API_STATUS=$(docker inspect "${SANDBOX_SLUG}-api" --format='{{.State.Status}}')
WEB_STATUS=$(docker inspect "${SANDBOX_SLUG}-web" --format='{{.State.Status}}')

if [ "$API_STATUS" = "running" ] && [ "$WEB_STATUS" = "running" ]; then
    echo "✅ Deployment successful!"
    echo "   API: $API_STATUS"
    echo "   Web: $WEB_STATUS"
    echo ""
    echo "🌐 Sandbox URL: https://$SANDBOX_SLUG.sandbox.amazing-ai.tools"
else
    echo "⚠️  Deployment completed but containers may need attention"
    echo "   API: $API_STATUS"
    echo "   Web: $WEB_STATUS"
fi
