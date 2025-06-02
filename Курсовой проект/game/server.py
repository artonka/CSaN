import socket
import threading
import time
import hashlib
import base64
import struct
import json
import os

import game_logic

# --- Конфигурация сервера ---
HTTP_HOST = '0.0.0.0'
HTTP_PORT = 8000
WEBSOCKET_HOST = '0.0.0.0'
WEBSOCKET_PORT = 8001
WEB_DIR = os.path.join(os.path.dirname(__file__), 'client')
SERVER_TICK_RATE = 1 / 60

# --- WebSocket константы ---
WEBSOCKET_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
OPCODE_TEXT = 0x1
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA

# --- Управление WebSocket клиентами ---
ws_clients_lock = threading.Lock()
ws_clients = {}
ws_client_id_counter = 0

# ==============================================================================
# HTTP Сервер
# ==============================================================================
def handle_http_request(client_socket):
    try:
        request_data = client_socket.recv(1024).decode('utf-8', errors='ignore')
        if not request_data:
            client_socket.close()
            return

        request_lines = request_data.split('\r\n')
        if not request_lines:
            client_socket.close()
            return
            
        method, path, _ = request_lines[0].split(' ')

        if method == 'GET':
            if path == '/':
                path = '/index.html'
            
            requested_path = os.path.normpath(os.path.join(WEB_DIR, path.lstrip('/')))
            if not requested_path.startswith(os.path.abspath(WEB_DIR)):
                response = b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\n\r\nForbidden"
                client_socket.sendall(response)
                return

            file_path = requested_path
            
            if os.path.exists(file_path) and os.path.isfile(file_path):
                content_type = 'text/plain'
                if file_path.endswith('.html'): content_type = 'text/html; charset=utf-8'
                elif file_path.endswith('.css'): content_type = 'text/css; charset=utf-8'
                elif file_path.endswith('.js'): content_type = 'application/javascript; charset=utf-8'
                elif file_path.endswith('.ico'): content_type = 'image/x-icon'

                with open(file_path, 'rb') as f:
                    response_body = f.read()
                
                response_headers = (
                    f"HTTP/1.1 200 OK\r\n"
                    f"Content-Type: {content_type}\r\n"
                    f"Content-Length: {len(response_body)}\r\n"
                    f"Connection: close\r\n\r\n"
                )
                client_socket.sendall(response_headers.encode('utf-8') + response_body)
            else:
                response = b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n\r\nFile Not Found"
                client_socket.sendall(response)
        else:
            response = b"HTTP/1.1 405 Method Not Allowed\r\nContent-Type: text/plain\r\n\r\nMethod Not Allowed"
            client_socket.sendall(response)
            
    except Exception as e:
        print(f"HTTP Request Error: {e}")
    finally:
        client_socket.close()

def run_http_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((HTTP_HOST, HTTP_PORT))
        server_socket.listen(5)
        print(f"HTTP сервер запущен на http://{HTTP_HOST}:{HTTP_PORT}\n")
        print(f"Отдает файлы из: {os.path.abspath(WEB_DIR)}")

        while True:
            client_socket, addr = server_socket.accept()
            http_thread = threading.Thread(target=handle_http_request, args=(client_socket,))
            http_thread.daemon = True
            http_thread.start()
    except OSError as e:
        print(f"ОШИБКА HTTP СЕРВЕРА: Не удалось запустить сервер на {HTTP_HOST}:{HTTP_PORT}. {e}")
    except KeyboardInterrupt:
        print("HTTP сервер останавливается...")
    finally:
        server_socket.close()

# ==============================================================================
# WebSocket Сервер: Рукопожатие и Фрейминг
# ==============================================================================
def parse_http_headers(data_str):
    headers = {}
    lines = data_str.split("\r\n")
    for line in lines:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    return headers

def generate_websocket_accept_key(client_key):
    return base64.b64encode(hashlib.sha1((client_key + WEBSOCKET_GUID).encode()).digest()).decode()

def _send_ws_frame_to_conn(conn, payload, opcode=OPCODE_TEXT):
    if isinstance(payload, str):
        payload = payload.encode('utf-8')
    
    payload_len = len(payload)
    frame_header = bytearray()

    frame_header.append(0x80 | opcode) 

    mask_bit = 0x00

    if payload_len <= 125:
        frame_header.append(mask_bit | payload_len)
    elif payload_len <= 65535:
        frame_header.append(mask_bit | 126)
        frame_header.extend(struct.pack("!H", payload_len))
    else:
        frame_header.append(mask_bit | 127)
        frame_header.extend(struct.pack("!Q", payload_len))
    
    try:
        conn.sendall(bytes(frame_header) + payload)
        return True
    except (socket.error, BrokenPipeError):
        return False

def _receive_ws_frame_from_conn(conn):
    try:
        header_byte1 = conn.recv(1)
        if not header_byte1: return None, None
        opcode = header_byte1[0] & 0b00001111

        header_byte2 = conn.recv(1)
        if not header_byte2: return None, None
        mask_bit = (header_byte2[0] & 0b10000000) >> 7
        payload_len_indicator = header_byte2[0] & 0b01111111

        payload_len = 0
        if payload_len_indicator <= 125:
            payload_len = payload_len_indicator
        elif payload_len_indicator == 126:
            len_bytes = conn.recv(2)
            if not len_bytes or len(len_bytes) < 2: return None, None
            payload_len = struct.unpack("!H", len_bytes)[0]
        elif payload_len_indicator == 127:
            len_bytes = conn.recv(8)
            if not len_bytes or len(len_bytes) < 8: return None, None
            payload_len = struct.unpack("!Q", len_bytes)[0]
        
        masking_key = None
        if mask_bit:
            masking_key = conn.recv(4)
            if not masking_key or len(masking_key) < 4: return None, None
        
        payload_data_bytes = b""
        remaining_payload_size = payload_len
        while remaining_payload_size > 0:
            chunk_size = min(remaining_payload_size, 4096)
            chunk = conn.recv(chunk_size)
            if not chunk: return None, None
            payload_data_bytes += chunk
            remaining_payload_size -= len(chunk)

        if len(payload_data_bytes) != payload_len: return None, None

        if mask_bit and masking_key:
            unmasked_payload = bytearray(payload_len)
            for i in range(payload_len):
                unmasked_payload[i] = payload_data_bytes[i] ^ masking_key[i % 4]
            payload_data_bytes = bytes(unmasked_payload)
        
        return opcode, payload_data_bytes

    except socket.timeout: return "timeout", None
    except (socket.error, struct.error, IndexError, BrokenPipeError, ConnectionResetError): return None, None

# ==============================================================================
# WebSocket Сервер: Управление клиентами и сообщениями
# ==============================================================================
def send_to_one_client_by_conn(conn, payload_obj):
    """Отправляет JSON объект одному клиенту по его сокету."""
    try:
        json_str = json.dumps(payload_obj)
        _send_ws_frame_to_conn(conn, json_str)
    except Exception as e:
        print(f"WS Core: Ошибка отправки клиенту: {e}")

def broadcast_to_all_ws_clients(payload_obj, exclude_conn=None):
    """Отправляет JSON объект всем подключенным WebSocket клиентам."""
    if not payload_obj: return
    try:
        json_str = json.dumps(payload_obj)
    except TypeError as e:
        print(f"WS Core: Ошибка сериализации JSON при broadcast: {e}, Payload: {payload_obj}")
        return

    with ws_clients_lock:
        current_client_conns = list(ws_clients.keys())
    
    for client_conn in current_client_conns:
        if client_conn != exclude_conn:
            if not _send_ws_frame_to_conn(client_conn, json_str):
                pass


def handle_websocket_client_connection(conn, addr):
    global ws_client_id_counter
    client_session_data = None

    try:
        request_data = conn.recv(2048).decode('utf-8', errors='ignore')
        if not request_data: return
        headers = parse_http_headers(request_data)
        if 'sec-websocket-key' not in headers or \
           headers.get('upgrade', '').lower() != 'websocket' or \
           not headers.get('connection', '').lower().count('upgrade'):
            conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n"); return
        accept_key = generate_websocket_accept_key(headers['sec-websocket-key'])
        response_handshake = (
            "HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
            f"Sec-WebSocket-Accept: {accept_key}\r\n\r\n"
        )
        conn.sendall(response_handshake.encode('utf-8'))
        
        with ws_clients_lock:
            session_id = f"session_{ws_client_id_counter}" 
            ws_client_id_counter += 1
            client_session_data = {'id': session_id, 'addr': addr, 'status': 'connected', 'name': None, 'game_id': None}
            ws_clients[conn] = client_session_data
        
        print(f"WS Core: Сессия {client_session_data['id']} ({addr}) подключена, ожидает входа в игру.")

        conn.settimeout(1.0)
        while True:
            opcode, payload_bytes = _receive_ws_frame_from_conn(conn)

            if opcode is None and payload_bytes is None: break
            if opcode == "timeout": continue

            if opcode == OPCODE_TEXT:
                try:
                    message_str = payload_bytes.decode('utf-8')
                    message = json.loads(message_str)
                    msg_type = message.get('type')
                    msg_data = message.get('data', {})

                    current_client_status = client_session_data.get('status')

                    if msg_type == 'join_game' and current_client_status == 'connected':
                        player_name_from_client = msg_data.get('name', f"Player_{client_session_data['id'][-4:]}")
                        
                        client_session_data['name'] = player_name_from_client
                        client_session_data['status'] = 'ingame'
                        client_session_data['game_id'] = client_session_data['id'] 
                        
                        print(f"WS Core: Клиент {client_session_data['game_id']} (был {client_session_data['id']}) входит в игру как '{player_name_from_client}'.")

                        initial_state_data, new_player_data = game_logic.handle_player_connect(
                            client_session_data['game_id'],
                            player_name_from_client
                        )
                        if initial_state_data:
                            send_to_one_client_by_conn(conn, {'type': 'initial_state', 'data': initial_state_data})
                        if new_player_data:
                            broadcast_to_all_ws_clients({'type': 'player_joined', 'data': new_player_data}, exclude_conn=conn)
                    
                    elif msg_type == 'player_input' and current_client_status == 'ingame':
                        if client_session_data.get('game_id'):
                            game_logic.handle_player_input(client_session_data['game_id'], msg_data)

                except (json.JSONDecodeError, UnicodeDecodeError) as e:
                    print(f"WS Core: Некорректные данные от {client_session_data['id']}: {e}")
                except Exception as e_inner:
                     print(f"WS Core: Ошибка обработки сообщения от {client_session_data['id']}: {e_inner}")
            
            elif opcode == OPCODE_CLOSE:
                print(f"WS Core: Клиент {client_session_data['id']} запросил закрытие.")
                break
            elif opcode == OPCODE_PING:
                _send_ws_frame_to_conn(conn, payload_bytes, opcode=OPCODE_PONG)
            
    except socket.error: pass
    except Exception as e_outer:
        session_id_for_log = client_session_data.get('id', addr) if client_session_data else addr
        print(f"WS Core: Общая ошибка с клиентом {session_id_for_log}: {e_outer}")
    finally:
        if client_session_data:
            print(f"WS Core: Сессия {client_session_data['id']} отключается.")
            if client_session_data.get('status') == 'ingame' and client_session_data.get('game_id'):
                game_id_on_disconnect = client_session_data['game_id']
                _, disconnected_player_name = game_logic.handle_player_disconnect(game_id_on_disconnect)
                if game_id_on_disconnect:
                     broadcast_to_all_ws_clients({'type': 'player_left', 'data': game_id_on_disconnect})
                     broadcast_to_all_ws_clients({'type': 'message', 'data': {'text': f'{disconnected_player_name or game_id_on_disconnect} покинул игру.', 'msg_type': 'info'}})
        else:
            print(f"WS Core: Клиент с {addr} отключается (рукопожатие не завершено или сессия не создана).")
        
        with ws_clients_lock:
            if conn in ws_clients:
                del ws_clients[conn]
        conn.close()

def run_websocket_server():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        server_socket.bind((WEBSOCKET_HOST, WEBSOCKET_PORT))
        server_socket.listen(5)
        print(f"WebSocket сервер запущен на ws://{WEBSOCKET_HOST}:{WEBSOCKET_PORT}\n")

        while True:
            conn, addr = server_socket.accept()
            ws_client_thread = threading.Thread(target=handle_websocket_client_connection, args=(conn, addr))
            ws_client_thread.daemon = True
            ws_client_thread.start()
    except OSError as e:
        print(f"ОШИБКА WEBSOCKET СЕРВЕРА: Не удалось запустить сервер на {WEBSOCKET_HOST}:{WEBSOCKET_PORT}. {e}")
    except KeyboardInterrupt:
        print("WebSocket сервер останавливается...")
    finally:
        server_socket.close()

# ==============================================================================
# Основной цикл сервера (интеграция с game_logic)
# ==============================================================================
def server_main_loop():
    print("Основной цикл сервера запущен.")
    last_tick_time = time.perf_counter()

    game_logic.set_broadcast_callback(broadcast_to_all_ws_clients)

    while True:
        current_time = time.perf_counter()
        delta_time_sec = current_time - last_tick_time
        
        if delta_time_sec < SERVER_TICK_RATE:
            sleep_duration = SERVER_TICK_RATE - delta_time_sec
            time.sleep(sleep_duration)
            delta_time_sec = time.perf_counter() - last_tick_time 
        
        last_tick_time = time.perf_counter()

        game_snapshot_data = game_logic.update_game_state(delta_time_sec)

        if game_snapshot_data:
            payload_to_send = {'type': 'game_update', 'data': game_snapshot_data}
            broadcast_to_all_ws_clients(payload_to_send)

# ==============================================================================
# Запуск Сервера
# ==============================================================================
if __name__ == "__main__":
    print("Запуск серверных компонентов...")
    http_server_thread = threading.Thread(target=run_http_server, name="HTTPServerThread", daemon=True)
    http_server_thread.start()
    websocket_server_thread = threading.Thread(target=run_websocket_server, name="WebSocketServerThread", daemon=True)
    websocket_server_thread.start()
    try:
        server_main_loop()
    except KeyboardInterrupt:
        print("Сервер останавливается по KeyboardInterrupt (в основном потоке)...")
    except Exception as e_main:
        print(f"Критическая ошибка в server_main_loop: {e_main}")
        import traceback
        traceback.print_exc()
    finally:
        print("Завершение работы сервера (основной поток)...")