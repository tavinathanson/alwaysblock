.PHONY: install start stop restart uninstall status help

# Colors for output
GREEN=\033[0;32m
YELLOW=\033[1;33m
NC=\033[0m # No Color

help:
	@echo "AlwaysBlock Management Commands"
	@echo "================================"
	@echo ""
	@echo "  make install    - Install and start everything (first time setup)"
	@echo "  make start      - Start/restart all services after changes"
	@echo "  make stop       - Stop all services"
	@echo "  make restart    - Stop and start all services"
	@echo "  make uninstall  - Completely uninstall and stop everything"
	@echo "  make status     - Show current status"
	@echo ""

install:
	@echo "$(GREEN)Installing AlwaysBlock...$(NC)"
	@./install.sh
	@echo ""
	@echo "$(GREEN)Starting services...$(NC)"
	@sudo alwaysblock start-proxy
	@sudo alwaysblock enable-proxy
	@echo ""
	@echo "$(GREEN)✅ Installation complete! Services are running.$(NC)"
	@echo ""
	@alwaysblock status

start:
	@echo "$(GREEN)Starting AlwaysBlock services...$(NC)"
	@# Stop any existing processes first
	@sudo alwaysblock stop-proxy 2>/dev/null || true
	@# Kill any lingering processes on port 8905
	@-lsof -ti :8905 | xargs kill -9 2>/dev/null || true
	@sleep 0.5
	@# Start proxy daemon
	@sudo alwaysblock start-proxy
	@# Enable system proxy
	@sudo alwaysblock enable-proxy
	@echo ""
	@echo "$(GREEN)✅ All services started$(NC)"
	@echo ""
	@alwaysblock status

stop:
	@echo "$(YELLOW)Stopping AlwaysBlock services...$(NC)"
	@# Disable system proxy first
	@sudo alwaysblock disable-proxy 2>/dev/null || true
	@# Stop proxy daemon
	@sudo alwaysblock stop-proxy 2>/dev/null || true
	@# Kill any lingering processes
	@-lsof -ti :8905 | xargs kill -9 2>/dev/null || true
	@# Clean up PID files
	@rm -f /tmp/alwaysblock_proxy.pid 2>/dev/null || true
	@rm -f /tmp/alwaysblock_session_manager.pid 2>/dev/null || true
	@echo ""
	@echo "$(GREEN)✅ All services stopped$(NC)"
	@echo ""

restart: stop
	@sleep 1
	@$(MAKE) start

uninstall:
	@echo "$(YELLOW)Uninstalling AlwaysBlock...$(NC)"
	@./uninstall.sh

status:
	@alwaysblock status
