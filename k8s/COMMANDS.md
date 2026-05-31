# ============================================================
# COMMANDS.md — Команди для виконання лабораторної роботи
# ============================================================

## 1. Запуск кластера
```bash
chmod +x k8s/start.sh k8s/stop.sh
./k8s/start.sh
```

---

## 2. Перевірка доступності сервісів

```bash
# Переглянути всі поди
kubectl get pods

# Переглянути всі сервіси (IP та порти)
kubectl get services

# Перевірити що frontend відповідає
curl http://$(minikube ip):30080

# Перевірити що API відповідає
curl http://$(minikube ip):30080/api/
```

---

## 3. Перевірка міжсервісної взаємодії

```bash
# Зайти в под бекенду і перевірити зв'язок з БД
kubectl exec -it deployment/runmap-backend -- python manage.py dbshell

# Перевірити зв'язок з OSRM із середини бекенду
kubectl exec -it deployment/runmap-backend -- \
  curl http://osrm:5000/route/v1/foot/30.52,50.45;30.53,50.46

# Переглянути логи бекенду
kubectl logs -l app=backend --tail=50

# Переглянути логи БД
kubectl logs -l app=db --tail=30
```

---

## 4. Масштабування (потрібно мінімум 2 репліки)

```bash
# Збільшити кількість реплік бекенду до 3
kubectl scale deployment runmap-backend --replicas=3

# Перевірити що з'явилися нові поди
kubectl get pods -l app=backend

# Переглянути як розподіляється навантаження (балансування)
# Відкрити 3 термінали і в кожному запустити:
kubectl logs -f <pod-name-1>
kubectl logs -f <pod-name-2>
kubectl logs -f <pod-name-3>
# Потім зробити кілька запитів до API і побачити що логи пишуться
# в різні поди — це і є балансування навантаження.

# Зменшити назад до 2
kubectl scale deployment runmap-backend --replicas=2
```

---

## 5. Поведінка при видаленні пода (самовідновлення)

```bash
# Подивитися список подів бекенду
kubectl get pods -l app=backend

# Видалити один под (замінити <pod-name> на реальне ім'я)
kubectl delete pod <pod-name>

# Одразу подивитися — k8s автоматично створить новий!
kubectl get pods -l app=backend -w
# Прапор -w = watch, оновлюється в реальному часі. Ctrl+C щоб вийти.
```

---

## 6. Rolling update (оновлення без downtime)

```bash
# Зібрати нову версію образу
eval $(minikube docker-env)
docker build -t runmap-backend:v2 -f Dockerfile.backend .

# Оновити deployment на нову версію
kubectl set image deployment/runmap-backend backend=runmap-backend:v2

# Спостерігати за rolling update в реальному часі
kubectl rollout status deployment/runmap-backend

# Переглянути історію оновлень
kubectl rollout history deployment/runmap-backend

# Відкотитися назад якщо щось пішло не так
kubectl rollout undo deployment/runmap-backend
```

---

## 7. Зупинка кластера

```bash
./k8s/stop.sh

# Повне видалення всіх даних (скидання до нуля)
kubectl delete pvc --all
```

---

## Корисні команди для дебагу

```bash
# Опис пода (помилки, події)
kubectl describe pod <pod-name>

# Всі ресурси в кластері
kubectl get all

# Переглянути змінні оточення в поді
kubectl exec deployment/runmap-backend -- env | grep -E "DB|OSRM|SECRET"

# Зайти в bash поду
kubectl exec -it deployment/runmap-backend -- bash
```
