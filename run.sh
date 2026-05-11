#!/bin/bash
# Apolo Monitor - Inicio Rapido
# Dashboard: http://localhost:9999/
# Token: apolo-monitor-2026-token

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==========================================="
echo "  Apolo Monitor v1.0"
echo "==========================================="
echo ""
echo "Iniciando servidor de monitoreo..."
echo "Dashboard: http://localhost:9999/"
echo "Token: apolo-monitor-2026-token"
echo ""
echo "Presione Ctrl+C para detener"
echo "==========================================="
echo ""

python3 server.py "$@"
