#!/bin/bash

# Script: diagnose-patroni.sh
# Purpose: Quick diagnostic check for Patroni HA cluster health
# Usage: ./scripts/diagnose-patroni.sh

set -e

NAMESPACE=${1:-default}
TIMEOUT=30

echo "=== Patroni HA Cluster Diagnostic Report ==="
echo "Namespace: $NAMESPACE"
echo "Time: $(date -u +'%Y-%m-%d %H:%M:%S UTC')"
echo ""

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo "❌ kubectl not found in PATH"
    exit 1
fi

# 1. Check Patroni pods status
echo "1️⃣  Patroni StatefulSet Status:"
if kubectl get statefulset classapp-patroni -n "$NAMESPACE" &>/dev/null; then
    kubectl get statefulset classapp-patroni -n "$NAMESPACE"
    echo ""
else
    echo "❌ StatefulSet classapp-patroni not found"
fi

# 2. Check Patroni pod status and labels
echo "2️⃣  Patroni Pods (with labels):"
if kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=patroni --show-labels 2>/dev/null | grep -q patroni; then
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=patroni --show-labels
    echo ""
else
    echo "❌ No Patroni pods found"
fi

# 3. Check etcd availability
echo "3️⃣  etcd Status:"
if kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=etcd 2>/dev/null | grep -q etcd; then
    kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=etcd
    echo ""
else
    echo "❌ etcd pod not found"
fi

# 4. Check PATRONI_SCOPE/PATRONI_NAMESPACE consistency across pods (etcd config)
echo "4️⃣  Patroni scope/namespace consistency (etcd DCS identity):"
echo "Pod: scope / namespace / etcd hosts"
kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=patroni -o jsonpath='{range .items[*]}{.metadata.name}{": "}{.spec.containers[?(@.name=="patroni")].env[?(@.name=="PATRONI_SCOPE")].value}{" / "}{.spec.containers[?(@.name=="patroni")].env[?(@.name=="PATRONI_NAMESPACE")].value}{" / "}{.spec.containers[?(@.name=="patroni")].env[?(@.name=="ETCD_HOSTS")].value}{"\n"}{end}' 2>/dev/null || echo "⚠️  Could not read env vars (pods may not exist yet)"
echo ""
echo "⚠️  scope и namespace ДОЛЖНЫ совпадать на всех подах, иначе split-brain в etcd"
echo ""

# 5. Check Secrets
echo "5️⃣  Database Secrets:"
if kubectl get secret classapp-secrets -n "$NAMESPACE" 2>/dev/null; then
    echo "✓ Secret classapp-secrets exists"
    echo "Keys: $(kubectl get secret classapp-secrets -n "$NAMESPACE" -o jsonpath='{.data}' | grep -o '"[^"]*":' | sed 's/"//g; s/:$//' | tr '\n' ', ' | sed 's/,$//')"
    echo ""
else
    echo "❌ Secret classapp-secrets not found"
fi

# 6. Check Service endpoints
echo "6️⃣  Database Service Endpoints:"
echo ""
echo "Master endpoint (classapp-db-master):"
MASTER_ENDPOINTS=$(kubectl get endpoints classapp-db-master -n "$NAMESPACE" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)
if [ -n "$MASTER_ENDPOINTS" ]; then
    echo "✓ Available: $MASTER_ENDPOINTS"
else
    echo "❌ No endpoints (master may not be elected yet)"
fi
echo ""

echo "Replica endpoints (classapp-db-replica):"
REPLICA_ENDPOINTS=$(kubectl get endpoints classapp-db-replica -n "$NAMESPACE" -o jsonpath='{.subsets[*].addresses[*].ip}' 2>/dev/null)
if [ -n "$REPLICA_ENDPOINTS" ]; then
    echo "✓ Available: $REPLICA_ENDPOINTS"
else
    echo "❌ No endpoints"
fi
echo ""

# 7. Check web pod connectivity
echo "7️⃣  Web Pod Database Connectivity:"
WEB_POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=web -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$WEB_POD" ]; then
    echo "Testing pod: $WEB_POD"
    echo ""
    echo "DNS resolution (classapp-db-master):"
    if kubectl exec "$WEB_POD" -n "$NAMESPACE" -- nslookup classapp-db-master &>/dev/null; then
        echo "✓ DNS resolves"
    else
        echo "❌ DNS resolution failed"
    fi
    echo ""
    echo "Port connectivity (5432):"
    if kubectl exec "$WEB_POD" -n "$NAMESPACE" -- timeout 3 bash -c 'echo > /dev/tcp/classapp-db-master/5432' 2>/dev/null; then
        echo "✓ Port 5432 accessible"
    else
        echo "❌ Port 5432 not accessible"
    fi
else
    echo "⚠️  No web pods running"
fi
echo ""

# 8. Check recent pod events
echo "8️⃣  Recent Pod Events:"
kubectl get events -n "$NAMESPACE" --sort-by='.lastTimestamp' | tail -10
echo ""

# 9. Patroni API check
echo "9️⃣  Patroni API Status (if pod is ready):"
PATRONI_POD=$(kubectl get pods -n "$NAMESPACE" -l app.kubernetes.io/name=patroni -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
if [ -n "$PATRONI_POD" ]; then
    if kubectl exec "$PATRONI_POD" -n "$NAMESPACE" -c patroni -- timeout 3 wget -qO- http://127.0.0.1:8008/health &>/dev/null; then
        echo "✓ Patroni API responding"
        echo ""
        ROLE=$(kubectl exec "$PATRONI_POD" -n "$NAMESPACE" -c patroni -- timeout 3 wget -qO- http://127.0.0.1:8008 2>/dev/null | grep -o '"role":"[^"]*"' | sed 's/"//g; s/role://' || echo "unknown")
        echo "Role: $ROLE"
    else
        echo "⚠️  Patroni API not responding yet (pod may still be initializing)"
    fi
else
    echo "⚠️  No Patroni pods to check"
fi
echo ""

# 10. Summary
echo "🔍 Summary:"
echo ""
if [ -n "$MASTER_ENDPOINTS" ]; then
    echo "✅ Cluster appears healthy - master endpoint is available"
else
    echo "⚠️  Master endpoint not available - cluster may be initializing"
    echo ""
    echo "Possible causes:"
    echo "  - Patroni pods still initializing (first startup takes 1-2 minutes)"
    echo "  - etcd not responding to Patroni"
    echo "  - role-labeler sidecar unable to query Patroni API"
    echo ""
    echo "Next steps:"
    echo "  1. Wait 2-3 minutes for full initialization"
    echo "  2. Check pod logs: kubectl logs classapp-patroni-0 -c patroni"
    echo "  3. Check role-labeler: kubectl logs classapp-patroni-0 -c role-labeler"
    echo "  4. See docs/PATRONI_TROUBLESHOOTING.md for detailed troubleshooting"
fi
echo ""
