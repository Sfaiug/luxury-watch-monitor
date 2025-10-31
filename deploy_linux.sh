#!/bin/bash

# Luxury Watch Monitor - Linux Server Deployment Script
# This script will clone the repository and set up the application

set -e

echo "🚀 Luxury Watch Monitor - Linux Server Deployment"
echo "================================================="

# Check if git is installed
if ! command -v git &> /dev/null; then
    echo "❌ Git is not installed. Please install git first:"
    echo "   Ubuntu/Debian: sudo apt-get install git"
    echo "   CentOS/RHEL: sudo yum install git"
    exit 1
fi

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first:"
    echo "   Visit: https://docs.docker.com/engine/install/"
    exit 1
fi

# Check if docker-compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "❌ docker-compose is not installed. Please install docker-compose first:"
    echo "   Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Get repository URL
read -p "Enter the Git repository URL: " REPO_URL
if [ -z "$REPO_URL" ]; then
    echo "❌ Repository URL is required"
    exit 1
fi

# Get deployment directory
read -p "Enter deployment directory (default: ./luxury-watch-monitor): " DEPLOY_DIR
DEPLOY_DIR=${DEPLOY_DIR:-./luxury-watch-monitor}

# Clone repository
if [ -d "$DEPLOY_DIR" ]; then
    echo "⚠️  Directory $DEPLOY_DIR already exists."
    read -p "Do you want to remove it and start fresh? (y/N): " REMOVE_DIR
    if [ "$REMOVE_DIR" = "y" ] || [ "$REMOVE_DIR" = "Y" ]; then
        rm -rf "$DEPLOY_DIR"
    else
        echo "Exiting..."
        exit 1
    fi
fi

echo "📦 Cloning repository..."
git clone "$REPO_URL" "$DEPLOY_DIR"
cd "$DEPLOY_DIR"

# Create necessary files
echo "📝 Creating configuration files..."

# Create empty data files
echo '{}' > seen_watches.json
echo '[]' > session_history.json

# Create logs directory
mkdir -p logs

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cat > .env << 'EOF'
# Discord Webhook URLs for each dealer
# Replace these with your actual Discord webhook URLs
# Format: https://discord.com/api/webhooks/YOUR_WEBHOOK_ID/YOUR_WEBHOOK_TOKEN

WORLDOFTIME_WEBHOOK_URL=
GRIMMEISSEN_WEBHOOK_URL=
TROPICALWATCH_WEBHOOK_URL=
JUWELIER_EXCHANGE_WEBHOOK_URL=
WATCH_OUT_WEBHOOK_URL=
RUESCHENBECK_WEBHOOK_URL=

# Optional: General webhook for all notifications
# DISCORD_WEBHOOK_URL=

# Optional: Telegram Configuration
# TELEGRAM_BOT_TOKEN=your_bot_token_here
# TELEGRAM_CHAT_ID=your_chat_id_here

# Optional: Email Configuration
# EMAIL_SENDER=your_email@gmail.com
# EMAIL_PASSWORD=your_app_password_here
# EMAIL_RECIPIENT=recipient@email.com
# SMTP_SERVER=smtp.gmail.com
# SMTP_PORT=587
EOF
    
    echo ""
    echo "⚠️  IMPORTANT: Edit the .env file and add your Discord webhook URLs!"
    echo "   You need to set webhook URLs for each dealer you want to monitor."
    echo ""
fi

# Build and run with Docker Compose
echo "🐳 Building Docker image..."
docker-compose build

echo ""
echo "✅ Deployment preparation complete!"
echo ""
echo "📋 Next steps:"
echo "1. Edit the .env file and add your Discord webhook URLs:"
echo "   nano $DEPLOY_DIR/.env"
echo ""
echo "2. Start the monitor:"
echo "   cd $DEPLOY_DIR"
echo "   docker-compose up -d"
echo ""
echo "3. Check logs:"
echo "   docker-compose logs -f"
echo ""
echo "4. Stop the monitor:"
echo "   docker-compose down"
echo ""
echo "5. Update to latest version:"
echo "   git pull"
echo "   docker-compose build"
echo "   docker-compose up -d"
echo ""
echo "📚 For more information, see README.md"