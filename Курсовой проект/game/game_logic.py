import random
import math
import uuid
import threading

# --- Игровые константы ---
WIDTH, HEIGHT = 800, 600
PLAYER_SIZE = 50
BULLET_SIZE = 5
ENEMY_SIZE = 40
OBSTACLE_WIDTH, OBSTACLE_HEIGHT = 110, 60
DIFFICULTY = {"enemy_speed": (2.2, 3.0), "spawn_rate": 1500, "max_enemies": 20}
GAME_TICK_RATE = 1 / 60

# --- Глобальное состояние игры ---
game_state_lock = threading.Lock()
game_players = {}
game_bullets = {}
game_enemies = {}
game_obstacles = []
game_bonuses = {}
game_scores = {}

# Таймеры спавна (управляются из game_loop)
ENEMY_SPAWN_TIMER_MS = 0
BONUS_SPAWN_TIMER_MS = 0
BONUS_SPAWN_RATE_MS = 10000
MAX_BONUSES = 3

# --- Вспомогательные игровые функции ---
def check_rect_collision(rect1, rect2):
    return (rect1['x'] < rect2['x'] + rect2['width'] and
            rect1['x'] + rect1['width'] > rect2['x'] and
            rect1['y'] < rect2['y'] + rect2['height'] and
            rect1['y'] + rect1['height'] > rect2['y'])

def get_random_color(): return f"#{random.randint(0, 0xFFFFFF):06x}"

def generate_initial_obstacles():
    global game_obstacles
    with game_state_lock:
        game_obstacles = []
        for _ in range(5):
            while True:
                x = random.randint(0, WIDTH - OBSTACLE_WIDTH)
                y = random.randint(0, HEIGHT - OBSTACLE_HEIGHT)
                new_obs_rect = {'x': x, 'y': y, 'width': OBSTACLE_WIDTH, 'height': OBSTACLE_HEIGHT}
                player_spawn_area = {'x': WIDTH//2 - 100, 'y': HEIGHT//2 - 100, 'width': 200, 'height': 200}
                if check_rect_collision(new_obs_rect, player_spawn_area): continue
                if any(check_rect_collision(new_obs_rect, obs) for obs in game_obstacles): continue
                game_obstacles.append(new_obs_rect); break
    print(f"Игра: Сгенерировано {len(game_obstacles)} препятствий.")

# --- Функции обратного вызова для сервера ---
broadcast_callback_func = None

def reset_simple_game_over_state():
    global game_players, game_bullets, game_enemies, game_bonuses, game_scores, is_game_over
    global ENEMY_SPAWN_TIMER_MS, BONUS_SPAWN_TIMER_MS
    with game_state_lock:
        game_players.clear()
        game_bullets.clear()
        game_enemies.clear()
        game_bonuses.clear()
        game_scores.clear()
        is_game_over = False
        ENEMY_SPAWN_TIMER_MS = 0
        BONUS_SPAWN_TIMER_MS = 0
    print("Игра: Состояние Game Over сброшено (основные игровые объекты очищены).")

def set_broadcast_callback(callback_func):
    global broadcast_callback_func
    broadcast_callback_func = callback_func

def _broadcast_message(payload_obj):
    if broadcast_callback_func:
        broadcast_callback_func(payload_obj)
    else:
        print("ПРЕДУПРЕЖДЕНИЕ (Игра): broadcast_callback не установлен!")

# --- Функции для управления состоянием игры, вызываемые из server_core ---
def handle_player_connect(client_id, player_name):
    with game_state_lock:
        game_players[client_id] = {
            'id': client_id, 'name': player_name,
            'x': WIDTH // 2 - PLAYER_SIZE // 2, 'y': HEIGHT // 2 - PLAYER_SIZE // 2,
            'width': PLAYER_SIZE, 'height': PLAYER_SIZE,
            'hp': 100, 
            'color': get_random_color(),
            'is_dead': False
        }
        game_scores[client_id] = 0
    
    initial_data_for_new_player = {
        'playerId': client_id, 'players': game_players, 'bullets': game_bullets,
        'enemies': game_enemies, 'obstacles': game_obstacles, 'bonuses': game_bonuses,
        'scores': game_scores,
        'gameSettings': { 'width': WIDTH, 'height': HEIGHT, 'playerSize': PLAYER_SIZE, 'bulletSize': BULLET_SIZE, 'enemySize': ENEMY_SIZE}
    }
    
    new_player_join_data = game_players[client_id].copy()

    return initial_data_for_new_player, new_player_join_data


def handle_player_disconnect(client_id):
    with game_state_lock:
        player_name = game_players.get(client_id, {}).get('name', client_id)
        if client_id in game_players: del game_players[client_id]
        if client_id in game_scores: del game_scores[client_id]
    return client_id, player_name


def handle_player_input(client_id, input_data):
    with game_state_lock:
        if client_id not in game_players or game_players[client_id]['hp'] <= 0: return None

        player = game_players[client_id]
        if player.get('is_dead', False) or player['hp'] <= 0 :
            return None
        speed = 5 
        keys = input_data.get('keys', {})
        
        dx, dy = 0, 0
        if keys.get('a') or keys.get('ф'): dx -= speed
        if keys.get('d') or keys.get('в'): dx += speed
        if keys.get('w') or keys.get('ц'): dy -= speed
        if keys.get('s') or keys.get('ы'): dy += speed
        
        if dx != 0 and dy != 0:
            norm = math.sqrt(dx*dx + dy*dy); dx = (dx / norm) * speed; dy = (dy / norm) * speed
        
        next_x_rect = {'x': player['x'] + dx, 'y': player['y'], 'width': player['width'], 'height': player['height']}
        if not any(check_rect_collision(next_x_rect, obs) for obs in game_obstacles):
            player['x'] += dx
        
        next_y_rect = {'x': player['x'], 'y': player['y'] + dy, 'width': player['width'], 'height': player['height']}
        if not any(check_rect_collision(next_y_rect, obs) for obs in game_obstacles):
            player['y'] += dy

        player['x'] = max(0, min(player['x'], WIDTH - player['width']))
        player['y'] = max(0, min(player['y'], HEIGHT - player['height']))

        if input_data.get('shoot') and input_data.get('target'):
            target = input_data['target']
            bullet_id = str(uuid.uuid4())
            start_x = player['x'] + player['width'] / 2; start_y = player['y'] + player['height'] / 2
            angle_dx = target['x'] - start_x; angle_dy = target['y'] - start_y
            dist = math.hypot(angle_dx, angle_dy)
            vel_x, vel_y = (0, -10) if dist == 0 else ((angle_dx/dist)*10, (angle_dy/dist)*10)

            game_bullets[bullet_id] = {
                'id': bullet_id, 'owner_sid': client_id,
                'x': start_x - BULLET_SIZE/2, 'y': start_y - BULLET_SIZE/2,
                'width': BULLET_SIZE, 'height': BULLET_SIZE, 'vx': vel_x, 'vy': vel_y
            }
    return None

def _spawn_bonus_at_location(x, y):
    bonus_id = str(uuid.uuid4())
    bonus_type = random.choice(["health", "score_boost"])
    game_bonuses[bonus_id] = {
        'id': bonus_id, 'x': x - 10, 'y': y - 10, 'width': 20, 'height': 20, 'type': bonus_type
    }

def _apply_bonus_effect_to_player(player_id, bonus_type):
    if player_id not in game_players: return
    player = game_players[player_id]
    if player.get('is_dead', False) or player['hp'] <= 0:
        return
    message_text = ""
    if bonus_type == "health":
        player['hp'] = min(player['hp'] + 30, 100)
        message_text = f"{player.get('name', player_id)} подобрал аптечку!"
    elif bonus_type == "score_boost":
        if player_id in game_scores: game_scores[player_id] += 50
        message_text = f"{player.get('name', player_id)} получил бонусные очки!"
    
    if message_text:
        _broadcast_message({'type': 'message', 'data': {'text': message_text, 'msg_type': 'success'}})


def update_game_state(delta_time_sec):
    global ENEMY_SPAWN_TIMER_MS, BONUS_SPAWN_TIMER_MS
    
    dt_ms = delta_time_sec * 1000

    events_for_broadcast = []

    with game_state_lock:
        if not game_players:
            ENEMY_SPAWN_TIMER_MS = 0; BONUS_SPAWN_TIMER_MS = 0
            game_enemies.clear(); game_bonuses.clear(); game_bullets.clear()

        # 1. Обновление пуль
        bullets_to_remove = []
        for bid, bullet in list(game_bullets.items()):
            bullet['x'] += bullet['vx']
            bullet['y'] += bullet['vy']
            if not (0 < bullet['x'] < WIDTH and 0 < bullet['y'] < HEIGHT) or \
               any(check_rect_collision(bullet, obs) for obs in game_obstacles):
                bullets_to_remove.append(bid)
        for bid in bullets_to_remove:
            if bid in game_bullets: del game_bullets[bid]

        # 2. Спавн врагов
        ENEMY_SPAWN_TIMER_MS += dt_ms
        if ENEMY_SPAWN_TIMER_MS >= DIFFICULTY["spawn_rate"] and len(game_enemies) < DIFFICULTY["max_enemies"]:
            ENEMY_SPAWN_TIMER_MS = 0; enemy_id = str(uuid.uuid4())
            side = random.choice(['top', 'bottom', 'left', 'right'])
            ex, ey = (0,0)
            if side == 'top': ex, ey = random.randint(0, WIDTH-ENEMY_SIZE), -ENEMY_SIZE
            elif side == 'bottom': ex, ey = random.randint(0, WIDTH-ENEMY_SIZE), HEIGHT
            elif side == 'left': ex, ey = -ENEMY_SIZE, random.randint(0, HEIGHT-ENEMY_SIZE)
            else: ex, ey = WIDTH, random.randint(0, HEIGHT-ENEMY_SIZE)
            game_enemies[enemy_id] = {
                'id': enemy_id, 'x': ex, 'y': ey, 'width': ENEMY_SIZE, 'height': ENEMY_SIZE,
                'speed': random.uniform(*DIFFICULTY["enemy_speed"]), 'hp': 30
            }

        # 3. Движение врагов и коллизии
        enemies_to_remove = []
        for eid, enemy in list(game_enemies.items()):
            target_player = None; min_dist = float('inf')
            for pid_loop, p_data_loop in game_players.items():
                if not p_data_loop.get('is_dead', False) and p_data_loop['hp'] > 0:
                    dist = math.hypot(p_data_loop['x'] - enemy['x'], p_data_loop['y'] - enemy['y'])
                    if dist < min_dist: min_dist = dist; target_player = p_data_loop
            
            if target_player:
                edx = target_player['x'] + PLAYER_SIZE/2 - (enemy['x'] + ENEMY_SIZE/2)
                edy = target_player['y'] + PLAYER_SIZE/2 - (enemy['y'] + ENEMY_SIZE/2)
                dist_to_target = math.hypot(edx, edy)
                if dist_to_target > 0:
                    move_dist = enemy['speed'] * delta_time_sec * 20
                    e_vx = (edx / dist_to_target) * move_dist
                    e_vy = (edy / dist_to_target) * move_dist
                    next_enemy_rect = {'x': enemy['x'] + e_vx, 'y': enemy['y'] + e_vy, 'width': ENEMY_SIZE, 'height': ENEMY_SIZE}
                    if not any(check_rect_collision(next_enemy_rect, obs) for obs in game_obstacles):
                        enemy['x'] += e_vx; enemy['y'] += e_vy
            
            for pid, player_data in list(game_players.items()):
                if player_data.get('is_dead', False) or player_data['hp'] <= 0: continue
                if check_rect_collision(enemy, player_data):
                    player_data['hp'] = max(0, player_data['hp'] - 20)
                    if player_data['hp'] <= 0:
                        player_data['is_dead'] = True
                        player_data['color'] = "#808080"
                        print(f"Игра: Игрок {pid} ({player_data.get('name', pid)}) погиб.")
                        events_for_broadcast.append({'type': 'message', 'data': {'text': f"{player_data.get('name', pid)} был повержен!", 'msg_type': 'warning'}})
                    enemies_to_remove.append(eid); break 
            
            if eid in enemies_to_remove: continue

            for bid, bullet in list(game_bullets.items()):
                if check_rect_collision(enemy, bullet):
                    if bullet['owner_sid'] in game_scores: game_scores[bullet['owner_sid']] += 10
                    enemies_to_remove.append(eid)
                    if bid in game_bullets: del game_bullets[bid]
                    if random.random() < 0.20: _spawn_bonus_at_location(enemy['x'], enemy['y'])
                    break 
        
        for eid in set(enemies_to_remove):
            if eid in game_enemies: del game_enemies[eid]
        
        
        # 5. Коллизия игрока с бонусом
        bonuses_to_remove = []
        for bonus_id, bonus_data in list(game_bonuses.items()):
            for pid, player_data in list(game_players.items()):
                if player_data.get('is_dead', False) or player_data['hp'] <=0: continue
                player_rect = {'x':player_data['x'],'y':player_data['y'],'width':player_data['width'],'height':player_data['height']}
                if check_rect_collision(player_rect, bonus_data):
                    _apply_bonus_effect_to_player(pid, bonus_data['type'])
                    bonuses_to_remove.append(bonus_id); break 
            if bonus_id in bonuses_to_remove: continue
        for b_id in bonuses_to_remove:
            if b_id in game_bonuses: del game_bonuses[b_id]

        # 6. Формирование текущего состояния для отправки
        current_snapshot = {
            'players': game_players, 'bullets': game_bullets, 'enemies': game_enemies,
            'bonuses': game_bonuses, 'scores': game_scores
        }
    
    for event_payload in events_for_broadcast:
        _broadcast_message(event_payload)

    return current_snapshot

generate_initial_obstacles()
print("Модуль game_logic инициализирован.")