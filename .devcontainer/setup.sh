#!/bin/bash

# uv installation
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.cargo/bin:$PATH"

# Wait for MySQL to be ready
echo "Waiting for MySQL to be ready..."
until mysql -h mysql -u crypto_user -pcrypto_pass -e "SELECT 1" >/dev/null 2>&1; do
    echo "MySQL is unavailable - sleeping"
    sleep 2
done
echo "MySQL is up and running!"

# Install Python dependencies using uv
uv sync --dev

# Install pre-commit hooks
uv run pre-commit install

# Create basic project structure
mkdir -p src/crypto_spot_collector
mkdir -p tests
mkdir -p docs
mkdir -p config

# Create __init__.py files
touch src/__init__.py
touch src/crypto_spot_collector/__init__.py
touch tests/__init__.py

echo "✅ Development environment setup complete!"
echo "🐍 Python environment configured with uv"
echo "🗄️  MySQL database ready at mysql:3306"
echo "🔧 Pre-commit hooks installed"
echo "📁 Basic project structure created"
echo ""
echo "Database connection info:"
echo "  Host: mysql"
echo "  Port: 3306"
echo "  Database: crypto_pachinko"
echo "  User: crypto_user"
echo "  Password: crypto_pass"