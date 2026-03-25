# Замість класів Django Model використовуємо звичайні словники.
# Це аналог HashMap<Integer, Route> у Java.

# Лічильники для автоінкременту ID (аналог SERIAL у SQL)
_user_id_counter = 1
_route_id_counter = 1

# Сховища даних — словники {id: {...дані...}}
USERS_DB = {}    # { 1: {"id": 1, "username": "anton", "email": "..."} }
ROUTES_DB = {}   # { 1: {"id": 1, "name": "...", "user_id": 1, ...} }


# ── Операції з користувачами ─────────────────────────────────────────────────

def get_all_users():
    return list(USERS_DB.values())

def get_user_by_id(user_id: int):
    return USERS_DB.get(user_id)

def create_user(username: str, email: str = ""):
    global _user_id_counter
    user = {
        "id": _user_id_counter,
        "username": username,
        "email": email,
    }
    USERS_DB[_user_id_counter] = user
    _user_id_counter += 1
    return user

def update_user(user_id: int, data: dict):
    if user_id not in USERS_DB:
        return None
    USERS_DB[user_id].update(data)
    return USERS_DB[user_id]

def delete_user(user_id: int):
    if user_id not in USERS_DB:
        return False
    del USERS_DB[user_id]
    # Видаляємо всі маршрути цього користувача (аналог CASCADE)
    to_delete = [rid for rid, r in ROUTES_DB.items() if r["user_id"] == user_id]
    for rid in to_delete:
        del ROUTES_DB[rid]
    return True


# ── Операції з маршрутами ─────────────────────────────────────────────────────

def get_all_routes():
    return list(ROUTES_DB.values())

def get_route_by_id(route_id: int):
    return ROUTES_DB.get(route_id)

def create_route(name: str, user_id: int, start_lat: float,
                 start_lon: float, radius: float, image_path: str = None):
    global _route_id_counter
    route = {
        "id": _route_id_counter,
        "name": name,
        "user_id": user_id,
        "start_lat": start_lat,
        "start_lon": start_lon,
        "radius": radius,
        "image": image_path,
        "path": None,        # заповниться після генерації
        "created_at": __import__('datetime').datetime.now().isoformat(),
    }
    ROUTES_DB[_route_id_counter] = route
    _route_id_counter += 1
    return route

def update_route_path(route_id: int, coordinates: list):
    if route_id not in ROUTES_DB:
        return None
    ROUTES_DB[route_id]["path"] = coordinates
    return ROUTES_DB[route_id]

def delete_route(route_id: int):
    if route_id not in ROUTES_DB:
        return False
    del ROUTES_DB[route_id]
    return True