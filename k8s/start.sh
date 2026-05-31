#!/bin/bash
# ============================================================
# start.sh — Запуск кластера RunMap у Minikube
# ============================================================

set -e  # Зупинитися при будь-якій помилці

echo "🚀 Starting RunMap Kubernetes cluster..."

# 1. Запустити Minikube якщо не запущено
if ! minikube status | grep -q "Running"; then
  echo "📦 Starting Minikube..."
  minikube start --driver=docker --memory=4096 --cpus=2
else
  echo "✅ Minikube is already running."
fi

# 2. Вказати Docker використовувати registry всередині Minikube
echo "🐳 Pointing Docker to Minikube's internal registry..."
eval $(minikube docker-env)

# 3. Скопіювати PBF-файл карти в майбутній PVC
# (через тимчасовий pod — стандартний спосіб для Minikube)
echo "🗺️  Uploading map data to cluster..."
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: osrm-data-pvc
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 2Gi
EOF

# Завантажуємо карту через тимчасовий pod
kubectl run map-uploader \
  --image=busybox \
  --restart=Never \
  --overrides='{"spec":{"volumes":[{"name":"data","persistentVolumeClaim":{"claimName":"osrm-data-pvc"}}],"containers":[{"name":"map-uploader","image":"busybox","command":["sleep","3600"],"volumeMounts":[{"mountPath":"/data","name":"data"}]}]}}' 2>/dev/null || true

# Чекаємо поки pod взагалі з'явиться в API (до 30 секунд)
echo "⏳ Waiting for uploader pod to appear..."
for i in $(seq 1 30); do
  if kubectl get pod map-uploader &>/dev/null; then
    echo "  Pod found after ${i}s"
    break
  fi
  sleep 1
done

echo "⏳ Waiting for uploader pod to be ready..."
kubectl wait --for=condition=ready pod/map-uploader --timeout=120s

echo "📤 Copying map file..."
kubectl cp map_data/kyiv_small.osm.pbf map-uploader:/data/kyiv_small.osm.pbf
kubectl delete pod map-uploader --wait=false
echo "✅ Map data uploaded."

# 4. Зібрати Docker-образи
echo "🔨 Building backend image..."
docker build -t runmap-backend:latest -f Dockerfile.backend .

echo "🎨 Building frontend image..."
docker build -t runmap-frontend:latest -f Dockerfile.frontend .

# 5. Розгорнути всі маніфести
echo "📜 Applying Kubernetes manifests..."
kubectl apply -f k8s/

# 6. Чекати на готовність БД
echo "⏳ Waiting for database..."
kubectl wait --for=condition=ready pod -l app=db --timeout=120s

# 7. Виконати міграції Django
echo "🔧 Running Django migrations..."
kubectl exec deployment/runmap-backend -- python manage.py migrate

# 8. Чекати на готовність бекенду
echo "⏳ Waiting for backend (2 replicas)..."
kubectl wait --for=condition=ready pod -l app=backend --timeout=120s

# 9. Показати статус
echo ""
echo "======================================================="
echo "🎉 RunMap cluster is ONLINE!"
echo ""
MINIKUBE_IP=$(minikube ip)
echo "🌐 Frontend:  http://${MINIKUBE_IP}:30080"
echo "🔌 API:       http://${MINIKUBE_IP}:30080/api/"
echo "⚙️  Admin:     http://${MINIKUBE_IP}:30080/admin/"
echo ""
echo "📊 Pod status:"
kubectl get pods
echo ""
echo "💾 Volumes:"
kubectl get pvc
echo "======================================================="