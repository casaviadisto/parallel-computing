import L from 'leaflet';
import axios from 'axios';

// const API_BASE = 'http://127.0.0.1:8000/api';
const API_BASE = '/api';
let map;
let userId = null;
let accessToken = null;

// Стан
let center = {lat: 50.448, lng: 30.525};
let widthDeg = 0.01, heightDeg = 0.01, rotation = 0;
let imageFile = null;
let normalizedContour = [];
let currentRouteCoords = [];

// Слої
let cornerMarkers = [];
let rotateMarker = null, boundingBoxRect = null;
let contourLayer = null, routeLayer = null;

// Інтерцептор для додавання токена
axios.interceptors.request.use(config => {
    if (accessToken) {
        config.headers.Authorization = `Bearer ${accessToken}`;
    }
    return config;
});

// Інтерцептор для обробки 401 (автоматичний выхід)
axios.interceptors.response.use(
    response => response,
    error => {
        if (error.response?.status === 401) {
            logout();
            document.getElementById('status').textContent = 'Сесія закінчилась, увійдіть знову';
        }
        return Promise.reject(error);
    }
);

// --- Утиліти (дистанція) ---
function haversineDistance(lat1, lon1, lat2, lon2) {
    const R = 6371;
    const dLat = (lat2 - lat1) * Math.PI / 180;
    const dLon = (lon2 - lon1) * Math.PI / 180;
    const a = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
        Math.cos(lat1 * Math.PI / 180) * Math.cos(lat2 * Math.PI / 180) *
        Math.sin(dLon / 2) * Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
}

function calculateTotalDistance(coords) {
    if (!coords || coords.length < 2) return 0;
    let total = 0;
    for (let i = 1; i < coords.length; i++) {
        total += haversineDistance(coords[i - 1][1], coords[i - 1][0], coords[i][1], coords[i][0]);
    }
    return total;
}

// --- Трансформація координат ---
function localToGlobal(u, v) {
    const cosR = Math.cos(rotation);
    const sinR = Math.sin(rotation);
    const localX = u * widthDeg;
    const localY = v * heightDeg;
    const resLng = center.lng + (localX * cosR - localY * sinR);
    const resLat = center.lat + (localX * sinR + localY * cosR);
    return [resLat, resLng];
}

function computeCorners() {
    return [
        localToGlobal(-0.5, 0.5),
        localToGlobal(0.5, 0.5),
        localToGlobal(0.5, -0.5),
        localToGlobal(-0.5, -0.5)
    ];
}

// --- Оновлення UI ---
function updateUI() {
    const corners = computeCorners();
    if (!boundingBoxRect) {
        boundingBoxRect = L.polygon(corners, {
            color: '#ff7800', weight: 2, fill: true, fillOpacity: 0.1, dashArray: '5, 5'
        }).addTo(map);
        boundingBoxRect.on('mousedown', onWholeDragStart);
    } else {
        boundingBoxRect.setLatLngs(corners);
    }

    if (normalizedContour.length > 0) {
        const transformedPoints = normalizedContour.map(p => localToGlobal(p.u, p.v));
        if (!contourLayer) {
            contourLayer = L.polyline(transformedPoints, {color: 'blue', weight: 2, interactive: false}).addTo(map);
        } else {
            contourLayer.setLatLngs(transformedPoints);
        }
    }

    updateControlMarkers(corners);
}

function updateControlMarkers(corners) {
    corners.forEach((latlng, i) => {
        if (!cornerMarkers[i]) {
            cornerMarkers[i] = L.marker(latlng, {draggable: true}).addTo(map);
            cornerMarkers[i].on('drag', (e) => onCornerDrag(e, i));
            cornerMarkers[i].on('dragend', updateBackendData);
        } else {
            cornerMarkers[i].setLatLng(latlng);
        }
    });

    const rotPos = localToGlobal(0, 0.5 + (0.003 / heightDeg));
    if (!rotateMarker) {
        rotateMarker = L.marker(rotPos, {
            draggable: true,
            icon: L.divIcon({className: 'rotate-marker', html: '↻', iconSize: [28, 28]})
        }).addTo(map);
        rotateMarker.on('dragstart', onRotateDragStart);
        rotateMarker.on('drag', onRotateDrag);
        rotateMarker.on('dragend', updateBackendData);
    } else {
        rotateMarker.setLatLng(rotPos);
    }
}

// --- функція для очищення мапи ---
function clearTransformationLayers() {
    // Видалити шар контуру
    if (contourLayer) {
        map.removeLayer(contourLayer);
        contourLayer = null;
    }
    // Видалити рамку (bounding box)
    if (boundingBoxRect) {
        map.removeLayer(boundingBoxRect);
        boundingBoxRect = null;
    }
    // Видалити маркери кутів
    cornerMarkers.forEach(marker => map.removeLayer(marker));
    cornerMarkers = [];
    // Видалити маркер обертання
    if (rotateMarker) {
        map.removeLayer(rotateMarker);
        rotateMarker = null;
    }
    // Скинути дані контуру
    normalizedContour = [];
}

// --- Запрос к бэкенду (только для авторизованных) ---
async function updateBackendData() {
    if (!imageFile) return;
    if (!accessToken) {
        document.getElementById('status').textContent = 'Будь ласка, увійдіть для побудови маршруту';
        return;
    }

    try {
        const corners = computeCorners();
        const formData = new FormData();
        formData.append('image', imageFile);
        formData.append('corners', JSON.stringify(corners));
        formData.append('profile', 'foot');

        const res = await axios.post(`${API_BASE}/routes/preview_route/`, formData);
        const rawCoords = res.data.contour.coordinates;
        const cosR = Math.cos(rotation);
        const sinR = Math.sin(rotation);

        normalizedContour = rawCoords.map(c => {
            const dx = c[0] - center.lng;
            const dy = c[1] - center.lat;
            return {
                u: (dx * cosR + dy * sinR) / widthDeg,
                v: (-dx * sinR + dy * cosR) / heightDeg
            };
        });

        const routeCoords = res.data.route.coordinates;
        currentRouteCoords = routeCoords;

        if (routeLayer) map.removeLayer(routeLayer);
        routeLayer = L.polyline(routeCoords.map(c => [c[1], c[0]]), {
            color: 'red', weight: 3, interactive: false
        }).addTo(map);

        const distance = calculateTotalDistance(routeCoords);
        document.getElementById('distance-display').textContent = `Дистанція: ${distance.toFixed(2)} км`;

        updateUI();
        document.getElementById('status').textContent = 'Маршрут оновлено';
    } catch (err) {
        console.error(err);
        document.getElementById('status').textContent = 'Помилка отримання маршруту';
    }
}

// --- Обробники перетягування ---
let startRot = 0, startMouseAngle = 0;

function onRotateDragStart(e) {
    const mouse = e.target.getLatLng();
    startMouseAngle = Math.atan2(mouse.lat - center.lat, mouse.lng - center.lng);
    startRot = rotation;
    map.dragging.disable();
}

function onRotateDrag(e) {
    const mouse = e.target.getLatLng();
    const currentAngle = Math.atan2(mouse.lat - center.lat, mouse.lng - center.lng);
    rotation = startRot + (currentAngle - startMouseAngle);
    updateUI();
}

function onCornerDrag(e, idx) {
    const mouse = e.target.getLatLng();
    const corners = computeCorners();
    const opp = {lat: corners[(idx + 2) % 4][0], lng: corners[(idx + 2) % 4][1]};

    center = {lat: (mouse.lat + opp.lat) / 2, lng: (mouse.lng + opp.lng) / 2};

    const dx = mouse.lng - opp.lng, dy = mouse.lat - opp.lat;
    const cosR = Math.cos(rotation), sinR = Math.sin(rotation);

    widthDeg = Math.abs(dx * cosR + dy * sinR);
    heightDeg = Math.abs(-dx * sinR + dy * cosR);

    updateUI();
}

function onWholeDragStart(e) {
    map.dragging.disable();
    const startMouse = e.latlng, startCenter = {...center};
    const onMove = (me) => {
        center.lat = startCenter.lat + (me.latlng.lat - startMouse.lat);
        center.lng = startCenter.lng + (me.latlng.lng - startMouse.lng);
        updateUI();
    };
    const onUp = () => {
        map.dragging.enable();
        map.off('mousemove', onMove);
        map.off('mouseup', onUp);
        updateBackendData();
    };
    map.on('mousemove', onMove);
    map.on('mouseup', onUp);
    L.DomEvent.stopPropagation(e);
}

// --- Аутентифікация ---
let authMode = 'login';
const modal = document.getElementById('auth-modal');
const modalTitle = document.getElementById('modal-title');
const modalSubmit = document.getElementById('modal-submit');
const modalSwitch = document.getElementById('modal-switch');
const modalError = document.getElementById('modal-error');
const authUsername = document.getElementById('auth-username');
const authPassword = document.getElementById('auth-password');
const authEmail = document.getElementById('auth-email');
const closeModalBtn = document.querySelector('.close');

function showModal(mode) {
    authMode = mode;
    modalTitle.textContent = mode === 'login' ? 'Вхід' : 'Реєстрація';
    modalSubmit.textContent = mode === 'login' ? 'Увійти' : 'Зареєструватися';
    modalSwitch.textContent = mode === 'login' ? 'Немає облікового запису? Зареєструватися' : 'Вже є акаунт? Увійти';
    authEmail.style.display = mode === 'register' ? 'block' : 'none';
    modal.style.display = 'block';
    modalError.textContent = '';
}

function hideModal() {
    modal.style.display = 'none';
    authUsername.value = '';
    authPassword.value = '';
    authEmail.value = '';
}

async function handleAuth() {
    const username = authUsername.value.trim();
    const password = authPassword.value.trim();
    const email = authEmail.value.trim();

    if (!username || !password) {
        modalError.textContent = 'Будь ласка, заповніть усі поля';
        return;
    }
    if (authMode === 'register' && !email) {
        modalError.textContent = 'Email обов\'язковий для реєстрації';
        return;
    }

    try {
        if (authMode === 'register') {
            // Регистрация
            await axios.post(`${API_BASE}/users/`, {username, email, password});
        }
        // Вхід (отримуєм токен)
        // Після отримання токена:
        const tokenRes = await axios.post(`${API_BASE}/token/`, {username, password});
        accessToken = tokenRes.data.access;

        // Декодуємо payload (друга частина JWT)
        const payload = JSON.parse(atob(accessToken.split('.')[1]));
        userId = payload.user_id;   // у Simple JWT поле називається "user_id"

        localStorage.setItem('accessToken', accessToken);
        localStorage.setItem('userId', userId);
        localStorage.setItem('username', username);

        updateAuthUI(username);
        hideModal();

        if (imageFile) {
            updateBackendData();
        }
    } catch (err) {
        const errorMsg = err.response?.data?.detail || err.response?.data?.username?.[0] || err.message || 'Помилка аутентифікації';
        modalError.textContent = errorMsg;
        console.error(err);
    }
}

function updateAuthUI(username) {
    document.getElementById('user-info').style.display = 'flex';
    document.getElementById('auth-buttons').style.display = 'none';
    document.getElementById('display-username').textContent = username;
    document.getElementById('status').textContent = `Ви увійшли як ${username}`;
}

function logout() {
    userId = null;
    accessToken = null;
    localStorage.removeItem('accessToken');
    localStorage.removeItem('userId');
    localStorage.removeItem('username');
    document.getElementById('user-info').style.display = 'none';
    document.getElementById('auth-buttons').style.display = 'block';
    document.getElementById('status').textContent = 'Ви вийшли';

    // Очищуємо шари маршруту
    if (routeLayer) map.removeLayer(routeLayer);
    routeLayer = null;
    currentRouteCoords = [];

    // Очищуємо елементи трансформації
    clearTransformationLayers();

    // Скидаємо файл
    imageFile = null;
    document.getElementById('file-input').value = '';
    const fileNameDiv = document.getElementById('file-name');
    if (fileNameDiv) fileNameDiv.textContent = '';

    document.getElementById('distance-display').textContent = 'Дистанція: -- км';
}

// відновлення сессії при загрузці
function restoreSession() {
    const savedToken = localStorage.getItem('accessToken');
    const savedUserId = localStorage.getItem('userId');
    const savedUsername = localStorage.getItem('username');
    if (savedToken && savedUserId && savedUsername) {
        accessToken = savedToken;
        userId = parseInt(savedUserId, 10);
        updateAuthUI(savedUsername);
    }
}

// --- Збереження маршруту ---
async function saveRoute() {
    if (!accessToken) {
        alert('Будь ласка, увійдіть, щоб зберегти маршрут');
        return;
    }
    if (!imageFile) {
        alert('Спочатку завантажте зображення');
        return;
    }
    const routeName = document.getElementById('route-name').value.trim() || 'Мій GPS-арт';
    const corners = computeCorners();
    const formData = new FormData();
    formData.append('name', routeName);
    formData.append('image', imageFile);
    formData.append('corners', JSON.stringify(corners));
    formData.append('profile', 'foot');

    try {
        const res = await axios.post(`${API_BASE}/routes/`, formData);
        document.getElementById('status').textContent = `Маршрут "${routeName}" збережено!`;
        console.log('Saved route:', res.data);
    } catch (err) {
        console.error(err);
        alert('Помилка збереження маршруту');
    }
}

// --- Експорт GPX ---
function exportGPX() {
    if (!accessToken) {
        alert('Будь ласка, увійдіть для експорту');
        return;
    }
    if (!currentRouteCoords || currentRouteCoords.length === 0) {
        alert('Спочатку завантажте зображення та отримайте маршрут');
        return;
    }
    downloadGPX(currentRouteCoords, 'route.gpx');
}

function downloadGPX(coords, filename) {
    let gpx = `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="RunMap">
  <trk>
    <name>GPS Art</name>
    <trkseg>`;
    coords.forEach(coord => {
        gpx += `<trkpt lat="${coord[1]}" lon="${coord[0]}"></trkpt>`;
    });
    gpx += `</trkseg></trk></gpx>`;

    const blob = new Blob([gpx], {type: 'application/gpx+xml'});
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
}

// --- Перегляд збережених маршрутів ---
const routesModal = document.getElementById('routes-modal');
const routesList = document.getElementById('routes-list');
const closeRoutesBtn = document.querySelector('.close-routes');

async function loadMyRoutes() {
    if (!accessToken) {
        alert('Увійдіть для перегляду маршрутів');
        return;
    }
    if (!userId) {
        alert('Неможливо визначити ID користувача');
        return;
    }

    routesModal.style.display = 'block';
    routesList.innerHTML = 'Завантаження...';

    try {
        const res = await axios.get(`${API_BASE}/routes/?user=${userId}`);
        const data = res.data;

        // Витягуємо масив маршрутів з урахуванням пагінації та GeoJSON
        let routeItems = [];

        if (data.results) {
            if (Array.isArray(data.results)) {
                // Якщо results - це масив
                routeItems = data.results;
            } else if (data.results.features && Array.isArray(data.results.features)) {
                // Якщо results - це FeatureCollection (як у вашому прикладі)
                routeItems = data.results.features;
            } else {
                console.error('Невідомий формат results', data.results);
                routesList.innerHTML = '<p>Помилка формату даних.</p>';
                return;
            }
        } else if (data.features && Array.isArray(data.features)) {
            routeItems = data.features;
        } else if (Array.isArray(data)) {
            routeItems = data;
        } else {
            console.error('Неочікуваний формат даних', data);
            routesList.innerHTML = '<p>Помилка формату даних.</p>';
            return;
        }

        if (routeItems.length === 0) {
            routesList.innerHTML = '<p>У вас ще немає збережених маршрутів.</p>';
            return;
        }

        let html = '';
        routeItems.forEach(feature => {
            const props = feature.properties || feature;
            const id = props.id || feature.id;
            const name = props.name || 'Без назви';
            const date = props.created_at ? new Date(props.created_at).toLocaleDateString('uk-UA') : '—';
            // Відстань можна додати пізніше, якщо зберігається
            const distance = props.distance_km ? props.distance_km.toFixed(2) : '—';

            html += `
        <div class="route-item">
          <h4>${name}</h4>
          <p>${date} | ${distance} км</p>
          <div class="route-actions">
            <button class="load-route-btn" data-id="${id}">Показати</button>
            <button class="download-route-btn" data-id="${id}">GPX</button>
          </div>
        </div>
      `;
        });
        routesList.innerHTML = html;

        document.querySelectorAll('.load-route-btn').forEach(btn => {
            btn.addEventListener('click', () => loadRouteToMap(btn.dataset.id));
        });
        document.querySelectorAll('.download-route-btn').forEach(btn => {
            btn.addEventListener('click', () => downloadRouteGPX(btn.dataset.id));
        });
    } catch (err) {
        console.error(err);
        routesList.innerHTML = '<p>Помилка завантаження списку.</p>';
    }
}

async function loadRouteToMap(routeId) {
    try {
        const res = await axios.get(`${API_BASE}/routes/${routeId}/`);
        const routeData = res.data;
        let coords = null;

        // Отримуємо координати з різних можливих структур
        if (routeData.geometry && routeData.geometry.coordinates) {
            coords = routeData.geometry.coordinates;
        } else if (routeData.path && routeData.path.coordinates) {
            coords = routeData.path.coordinates;
        } else if (routeData.coordinates) {
            coords = routeData.coordinates;
        }

        if (!coords || coords.length === 0) {
            alert('Немає координат маршруту');
            return;
        }

        // --- ОЧИЩЕННЯ СТАРИХ ЕЛЕМЕНТІВ ТРАНСФОРМАЦІЇ ---
        clearTransformationLayers();

        // Також скидаємо файл зображення та його відображення
        imageFile = null;
        document.getElementById('file-input').value = '';
        const fileNameDiv = document.getElementById('file-name');
        if (fileNameDiv) fileNameDiv.textContent = '';

        // Оновлюємо шар маршруту
        if (routeLayer) {
            map.removeLayer(routeLayer);
        }
        routeLayer = L.polyline(coords.map(c => [c[1], c[0]]), {
            color: 'red',
            weight: 4,
            interactive: false
        }).addTo(map);

        // Зберігаємо поточний маршрут для експорту
        currentRouteCoords = coords;

        // Підганяємо вигляд карти під маршрут
        const bounds = L.latLngBounds(coords.map(c => [c[1], c[0]]));
        map.fitBounds(bounds, { padding: [50, 50] });

        // Оновлюємо дистанцію
        const distance = calculateTotalDistance(coords);
        document.getElementById('distance-display').textContent = `Дистанція: ${distance.toFixed(2)} км`;

        // Закриваємо модальне вікно
        routesModal.style.display = 'none';

        const routeName = routeData.properties?.name || routeData.name || 'Маршрут';
        document.getElementById('status').textContent = `Завантажено маршрут: ${routeName}`;
    } catch (err) {
        console.error(err);
        alert('Помилка завантаження маршруту');
    }
}

async function downloadRouteGPX(routeId) {
    try {
        const res = await axios.get(`${API_BASE}/routes/${routeId}/`);
        const routeData = res.data;
        let coords = null;
        if (routeData.geometry && routeData.geometry.coordinates) {
            coords = routeData.geometry.coordinates;
        } else if (routeData.path && routeData.path.coordinates) {
            coords = routeData.path.coordinates;
        } else if (routeData.coordinates) {
            coords = routeData.coordinates;
        }

        if (!coords) {
            alert('Немає координат для експорту');
            return;
        }
        downloadGPX(coords, `route_${routeId}.gpx`);
    } catch (err) {
        console.error(err);
        alert('Помилка завантаження GPX');
    }
}

// --- Ініціалізація ---
function initMap() {
    map = L.map('map').setView([50.448, 30.525], 13);
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; OpenStreetMap'
    }).addTo(map);

    restoreSession();

    const fileInput = document.getElementById('file-input');
    const browseBtn = document.getElementById('browse-btn');
    const dropzoneEl = document.getElementById('dropzone');
    const fileNameDiv = document.getElementById('file-name');

// Відкриття діалогу через кнопку
    browseBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        fileInput.click();
    });

// Клік по всій дропзоні також відкриває діалог
    dropzoneEl.addEventListener('click', (e) => {
        // Ігноруємо, якщо клікнули безпосередньо по кнопці
        if (e.target !== browseBtn && !browseBtn.contains(e.target)) {
            fileInput.click();
        }
    });

// Відображення назви файлу при виборі
    fileInput.addEventListener('change', async (e) => {
        if (!e.target.files[0]) return;
        imageFile = e.target.files[0];
        fileNameDiv.textContent = `📄 ${imageFile.name}`;

        const img = new Image();
        img.src = URL.createObjectURL(imageFile);
        await img.decode();
        heightDeg = 0.01 * (img.height / img.width);
        widthDeg = 0.01;
        rotation = 0;
        if (accessToken) {
            updateBackendData();
        } else {
            document.getElementById('status').textContent = 'Увійдіть для побудови маршруту';
        }
    });

// Drag & drop підсвічування
    dropzoneEl.addEventListener('dragover', (e) => {
        e.preventDefault();
        dropzoneEl.classList.add('dragover');
    });

    dropzoneEl.addEventListener('dragleave', () => {
        dropzoneEl.classList.remove('dragover');
    });

    dropzoneEl.addEventListener('drop', (e) => {
        e.preventDefault();
        dropzoneEl.classList.remove('dragover');
        const file = e.dataTransfer.files[0];
        if (file && file.type.startsWith('image/')) {
            imageFile = file;
            fileNameDiv.textContent = `📄 ${imageFile.name}`;
            const img = new Image();
            img.src = URL.createObjectURL(file);
            img.onload = async () => {
                await img.decode();
                heightDeg = 0.01 * (img.height / img.width);
                widthDeg = 0.01;
                rotation = 0;
                if (accessToken) {
                    updateBackendData();
                } else {
                    document.getElementById('status').textContent = 'Увійдіть для побудови маршруту';
                }
            };
        }
    });

    // Аутентифікация
    document.getElementById('login-btn').addEventListener('click', () => showModal('login'));
    document.getElementById('register-btn').addEventListener('click', () => showModal('register'));
    document.getElementById('logout-btn').addEventListener('click', logout);
    modalSubmit.addEventListener('click', handleAuth);
    modalSwitch.addEventListener('click', () => {
        const newMode = authMode === 'login' ? 'register' : 'login';
        showModal(newMode);
    });
    closeModalBtn.addEventListener('click', hideModal);
    window.addEventListener('click', (e) => {
        if (e.target === modal) hideModal();
    });

    // Експорт, збереження і мої маршрути
    document.getElementById('export-gpx-btn').addEventListener('click', exportGPX);
    document.getElementById('save-route-btn').addEventListener('click', saveRoute);
    document.getElementById('my-routes-btn').addEventListener('click', loadMyRoutes);

    // Модальне вікно списку маршрутів
    closeRoutesBtn.addEventListener('click', () => routesModal.style.display = 'none');
    window.addEventListener('click', (e) => {
        if (e.target === routesModal) routesModal.style.display = 'none';
    });

    document.getElementById('status').textContent = 'Готово до роботи';
}

window.addEventListener('load', initMap);