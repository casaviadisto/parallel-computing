#!/bin/bash
# ============================================================
# stop.sh — Зупинка кластера RunMap
# ============================================================

echo "🛑 Stopping RunMap Kubernetes cluster..."

# Видалити всі ресурси з k8s/ (крім PVC — дані залишаються!)
kubectl delete -f k8s/ --ignore-not-found

echo ""
echo "======================================================="
echo "✅ All pods and services deleted."
echo "💾 PVCs (database + OSRM data) are preserved:"
kubectl get pvc 2>/dev/null || echo "  (no PVCs found)"
echo ""
echo "ℹ️  To also delete ALL data (full reset), run:"
echo "   kubectl delete pvc --all"
echo "======================================================="
