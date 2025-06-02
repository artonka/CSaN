const nameSelectionMenu = document.getElementById('name-selection-menu');
const playerNameInput = document.getElementById('playerNameInput');
const startGameButton = document.getElementById('startGameButton');
const connectionStatusEl = document.getElementById('connection-status');

const gameArea = document.getElementById('game-area');
const canvas = document.getElementById('gameCanvas');
const ctx = canvas.getContext('2d');
const playerHpEl = document.getElementById('playerHp');
const playerScoreEl = document.getElementById('playerScore');
const messagesEl = document.getElementById('messages');
const leaderboardListEl = document.getElementById('leaderboard-list');

let myPlayerId = null;
let players = {};
let bullets = {};
let enemies = {};
let obstacles = [];
let bonuses = {};
let scores = {};
let gameSettings = { width: 800, height: 600, playerSize: 50, bulletSize: 5, enemySize: 40 };

const WS_PORT = 8001;
const wsUrl = `ws://${window.location.hostname}:${WS_PORT}`;
let socket = null;
let connectionAttempts = 0;
const MAX_CONNECTION_ATTEMPTS = 5;
let gameStarted = false;

// --- Управление UI ---
function showMenu() {
    nameSelectionMenu.classList.add('active-view');
    gameArea.classList.remove('active-view');
    gameStarted = false;
}

function showGameArea() {
    nameSelectionMenu.classList.remove('active-view');
    gameArea.classList.add('active-view');
    gameStarted = true;
    
    if (gameSettings && gameSettings.width && gameSettings.height) {
        canvas.width = gameSettings.width;
        canvas.height = gameSettings.height;
    }
}

function updateConnectionStatus(message, statusClass) {
    connectionStatusEl.textContent = message;
    connectionStatusEl.className = '';
    connectionStatusEl.classList.add(statusClass);
}

// --- WebSocket соединение ---
function connectWebSocket() {
    if (socket && (socket.readyState === WebSocket.OPEN || socket.readyState === WebSocket.CONNECTING)) {
        console.log("WebSocket уже подключается или подключен.");
        return;
    }
    if (connectionAttempts >= MAX_CONNECTION_ATTEMPTS && !gameStarted) {
        updateConnectionStatus(`Не удалось подключиться. Попробуйте перезагрузить страницу.`, 'status-error');
        startGameButton.disabled = true;
        return;
    }
    connectionAttempts++;
    updateConnectionStatus(`Подключение... (попытка ${connectionAttempts})`, 'status-connecting');
    startGameButton.disabled = true;

    socket = new WebSocket(wsUrl);

    socket.onopen = () => {
        console.log("WebSocket подключен!");
        connectionAttempts = 0;
        updateConnectionStatus('Сервер доступен. Введите имя.', 'status-connected');
        startGameButton.disabled = false;
    };

    socket.onmessage = (event) => {
        try {
            const message = JSON.parse(event.data);
            if (!gameStarted && message.type !== 'initial_state') {
            }


            switch (message.type) {
                case 'initial_state':
                    handleInitialState(message.data);
                    if (!gameStarted) {
                        showGameArea();
                    }
                    break;
                case 'game_update':
                    if(gameStarted) handleGameUpdate(message.data);
                    break;
                case 'player_joined':
                    if(gameStarted) handlePlayerJoined(message.data);
                    break;
                case 'player_left':
                    if(gameStarted) handlePlayerLeft(message.data);
                    break;
                case 'message':
                    displayMessage(message.data.text, message.data.duration || 3000, message.data.msg_type || 'info');
                    break;
                default:
                    console.warn("Неизвестный тип сообщения от сервера:", message.type, message.data);
            }
        } catch (error) {
            console.error("Ошибка парсинга JSON или обработки сообщения:", error, event.data);
        }
    };

    socket.onclose = (event) => {
        console.log(`WebSocket соединение закрыто. Код: ${event.code}, причина: ${event.reason}`);
        myPlayerId = null;
        players = {}; bullets = {}; enemies = {}; bonuses = {}; scores = {};
        
        if (gameStarted) {
            displayMessage(`Соединение с сервером потеряно. Код: ${event.code}.`, 0, 'error');
        } else {
             updateConnectionStatus(`Соединение закрыто. Код: ${event.code}.`, 'status-error');
             if (!event.wasClean && connectionAttempts < MAX_CONNECTION_ATTEMPTS) {
                 setTimeout(connectWebSocket, 3000);
             } else if (!event.wasClean) {
                 updateConnectionStatus('Не удалось переподключиться.', 'status-error');
             }
        }
        startGameButton.disabled = true;
    };

    socket.onerror = (error) => {
        console.error("WebSocket ошибка:", error);
        if (!gameStarted) {
            updateConnectionStatus('Ошибка соединения с WebSocket.', 'status-error');
            startGameButton.disabled = true;
        }
    };
}

// --- Обработчики данных от сервера ---
function handleInitialState(data) {
    myPlayerId = data.playerId;
    players = data.players || {};
    bullets = data.bullets || {};
    enemies = data.enemies || {};
    obstacles = data.obstacles || [];
    bonuses = data.bonuses || {};
    scores = data.scores || {};
    if (data.gameSettings) {
        gameSettings = data.gameSettings;
        if (gameStarted && canvas.width !== gameSettings.width) canvas.width = gameSettings.width;
        if (gameStarted && canvas.height !== gameSettings.height) canvas.height = gameSettings.height;
    }
    console.log("Начальное состояние получено, мой ID:", myPlayerId);
    updateUI();
}

function handleGameUpdate(data) {
    if (data.players !== undefined) players = data.players;
    if (data.bullets !== undefined) bullets = data.bullets;
    if (data.enemies !== undefined) enemies = data.enemies;
    if (data.bonuses !== undefined) bonuses = data.bonuses;
    if (data.scores !== undefined) scores = data.scores;
    updateUI();
}

function handlePlayerJoined(playerData) {
    if (playerData && playerData.id) {
        players[playerData.id] = playerData;
        if (!scores[playerData.id]) scores[playerData.id] = 0;
        displayMessage(`${playerData.name || playerData.id} присоединился!`, 3000, 'info');
        updateUI();
    }
}

function handlePlayerLeft(playerId) {
    const PName = players[playerId]?.name || playerId;
    if (players[playerId]) delete players[playerId];
    if (scores[playerId]) delete scores[playerId];
    displayMessage(`${PName} покинул игру.`, 3000, 'info');
    updateUI();
}


// --- Отправка ввода на сервер ---
const keysPressed = {};
window.addEventListener('keydown', (e) => { 
    if (!gameStarted) return;
    keysPressed[e.key.toLowerCase()] = true; 
});
window.addEventListener('keyup', (e) => { 
    if (!gameStarted) return;
    keysPressed[e.key.toLowerCase()] = false; 
});

canvas.addEventListener('mousedown', (e) => {
    if (!gameStarted || !socket || socket.readyState !== WebSocket.OPEN) return;
    if (e.button === 0 ) {
        if (myPlayerId && players[myPlayerId] && players[myPlayerId].hp > 0 && !players[myPlayerId].is_dead) {
            const rect = canvas.getBoundingClientRect();
            const mouseX = e.clientX - rect.left;
            const mouseY = e.clientY - rect.top;
            socket.send(JSON.stringify({
                type: 'player_input',
                data: { shoot: true, target: { x: mouseX, y: mouseY }, keys: keysPressed }
            }));
        }
    }
});

setInterval(() => {
    if (!gameStarted || !socket || socket.readyState !== WebSocket.OPEN) return;
    if (myPlayerId && players[myPlayerId] && players[myPlayerId].hp > 0 && !players[myPlayerId].is_dead) {
        if (Object.values(keysPressed).some(pressed => pressed)) {
            socket.send(JSON.stringify({ type: 'player_input', data: { keys: keysPressed } }));
        }
    }
}, 1000 / 20);

const COLORS = { };
function displayMessage(text, duration = 3000, type = 'info') {
    const messageItem = document.createElement('div');
    messageItem.classList.add('message-item', type);
    messageItem.textContent = text;
    messagesEl.appendChild(messageItem);
    messagesEl.scrollTop = messagesEl.scrollHeight;
    if (duration > 0) {
        setTimeout(() => {
            if (messagesEl.contains(messageItem)) {
                 messagesEl.removeChild(messageItem);
            }
        }, duration);
    }
}

function updateUI() {
    if (!gameStarted) return;

    if (myPlayerId && players[myPlayerId]) {
        const myPlayerData = players[myPlayerId];

        playerHpEl.textContent = players[myPlayerId].hp;
        playerScoreEl.textContent = scores[myPlayerId] || 0;

        if (myPlayerData.is_dead || (myPlayerData.hp !== undefined && myPlayerData.hp <= 0)) {
            playerHpEl.style.color = "#808080";
            playerHpEl.textContent = "ПОГИБ";
        } else if (myPlayerData.hp !== undefined) {
            playerHpEl.style.color = myPlayerData.hp > 50 ? "lightgreen" : 
                                     myPlayerData.hp > 20 ? "orange" : "red";
        } else {
        playerHpEl.textContent = "---";
        playerScoreEl.textContent = "---";
        }
    }

    leaderboardListEl.innerHTML = '';
    const sortedScores = Object.entries(scores || {}).sort(([,a],[,b]) => b-a).slice(0,10);
    for (const [pid, scoreVal] of sortedScores) {
        const playerName = players[pid]?.name || `Игрок ${pid.substring(0,4)}`;
        const listItem = document.createElement('li');
        listItem.textContent = `${playerName}: ${scoreVal}`;
        if (pid === myPlayerId) { listItem.style.fontWeight = 'bold'; listItem.style.color = '#77ccff';}
        leaderboardListEl.appendChild(listItem);
    }
}

function drawGame() {
    requestAnimationFrame(drawGame);
    if (!gameStarted || !ctx) return;

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = "#303030";
    ctx.fillRect(0,0, canvas.width, canvas.height);

    // 1. Препятствия
    ctx.fillStyle = COLORS.obstacle || "#808080";
    (obstacles || []).forEach(obs => { ctx.fillRect(obs.x, obs.y, obs.width, obs.height); });

    // 2. Игроки
    for (const id in players) {
        const p = players[id];
        if (!p) continue;

        if (p.is_dead || p.hp <= 0) {
            ctx.fillStyle = p.color || "#808080";
        } else {
            ctx.fillStyle = p.color || COLORS.player_default || "#00FF00";
        }

        ctx.fillRect(p.x, p.y, p.width, p.height);
        ctx.fillStyle = "white"; ctx.font = "12px Arial"; ctx.textAlign = "center";
        ctx.fillText(p.name || `P-${id.substring(0,4)}`, p.x + p.width/2, p.y - 5);
        if (id !== myPlayerId && p.hp !== undefined) {
            if (!p.is_dead) {
                const hpBarWidth = p.width; const hpBarHeight = 5;
                const hpFillWidth = Math.max(0, (p.hp / 100)) * hpBarWidth;
                ctx.fillStyle = "grey"; ctx.fillRect(p.x, p.y - hpBarHeight - 12, hpBarWidth, hpBarHeight);
                ctx.fillStyle = p.hp > 50 ? "green" : (p.hp > 20 ? "orange" : "red");
                ctx.fillRect(p.x, p.y - hpBarHeight - 12, hpFillWidth, hpBarHeight);
            }
        }
    }
    // 3. Пули
    ctx.fillStyle = COLORS.bullet || "#FFFFFF";
    for (const id in bullets) {
        const b = bullets[id];
        if (!b) continue;
        ctx.fillRect(b.x, b.y, b.width, b.height);
    }

    // 4. Враги
    ctx.fillStyle = COLORS.enemy || "#FF0000";
    for (const id in enemies) {
        const en = enemies[id];
        if (!en) continue;
        ctx.fillRect(en.x, en.y, en.width, en.height);
    }

    // 5. Бонусы
    for (const id in bonuses) {
        const bonus = bonuses[id];
        if (!bonus) continue;
        if (bonus.type === "health") ctx.fillStyle = COLORS.bonus_health || "rgba(0, 255, 0, 0.9)";
        else if (bonus.type === "score_boost") ctx.fillStyle = COLORS.bonus_score_boost || "rgba(255, 255, 0, 0.9)";
        else ctx.fillStyle = "purple";
        ctx.beginPath();
        ctx.arc(bonus.x + bonus.width/2, bonus.y + bonus.height/2, bonus.width/2, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = "black"; ctx.font = "bold 10px Arial"; ctx.textAlign = "center"; ctx.textBaseline = "middle";
        let letter = bonus.type.substring(0,1).toUpperCase();
        if (bonus.type === "score_boost") letter = "$";
        ctx.fillText(letter, bonus.x + bonus.width/2, bonus.y + bonus.height/2);
    }
}


// --- Инициализация ---
document.addEventListener('DOMContentLoaded', () => {
    nameSelectionMenu.classList.add('active-view');
    gameArea.classList.remove('active-view');
    gameStarted = false;

    connectWebSocket();

    startGameButton.addEventListener('click', () => {
        const playerName = playerNameInput.value.trim() || `Player${Math.floor(Math.random()*1000)}`;
        if (socket && socket.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({
                type: 'join_game',
                data: { name: playerName }
            }));
            updateConnectionStatus('Ожидание ответа от сервера...', 'status-connecting');
            startGameButton.disabled = true;
        } else {
            updateConnectionStatus('Нет соединения с сервером. Попробуйте позже.', 'status-error');
        }
    });
    
    drawGame();
});