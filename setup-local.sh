#!/bin/bash
# setup-local.sh — One-command setup for local testing

set -e

VENV=".venv"
DEPS_K8S="k8s_mcp/requirements.txt"
DEPS_AGENT="agent/requirements.txt"

echo "🚀 KubeSherlock Local Setup"
echo "───────────────────────────"

# Create venv if needed
if [ ! -d "$VENV" ]; then
    echo "📦 Creating Python venv..."
    python3 -m venv "$VENV"
fi

# Activate venv
source "$VENV/bin/activate"

# Install k8s_mcp deps
echo "📥 Installing k8s_mcp dependencies..."
pip install -q -r "$DEPS_K8S"

# Install agent deps
echo "📥 Installing agent dependencies..."
pip install -q -r "$DEPS_AGENT"

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo ""
echo "1. Start minikube (if not running):"
echo "   minikube start"
echo ""
echo "2. Edit config.env with your API keys:"
echo "   ANTHROPIC_API_KEY=sk-ant-..."
echo "   OPENAI_API_KEY=sk-proj-..."
echo ""
echo "3. Run unit tests:"
echo "   .venv/bin/pytest tests/ -v"
echo ""
echo "4. Start the k8s MCP server (in one terminal):"
echo "   python -m k8s_mcp.server --namespaces default kube-system"
echo ""
echo "5. In another terminal, test the agent:"
echo "   python -m agent 'Why is coredns crashing?' --namespaces kube-system"
echo ""
echo "6. Or start the watcher:"
echo "   python -m agent.watcher"
echo ""
