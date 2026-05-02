import serial
import threading
import time
import queue
import subprocess

# ── Nicla devices: (port, display name, priority) ──
# Lower priority number = higher priority (NICLA_1 speaks first)
ports = [
    ("/dev/ttyACM0", "NICLA_1", 1),
    ("/dev/ttyACM1", "NICLA_2", 2),
    ("/dev/ttyACM2", "NICLA_3", 3),
]

BAUD = 115200
RECONNECT_DELAY = 3       # seconds to wait before retrying a lost connection
DEDUPE_WINDOW   = 3.0     # seconds to suppress duplicate label announcements

# ── Shared priority queue: items are (priority, label) ──
audio_queue = queue.PriorityQueue()

# ── Deduplication: track recently announced labels ──
recent_labels = {}
dedupe_lock   = threading.Lock()

def is_duplicate(label):
    """Returns True if this label was already announced within DEDUPE_WINDOW seconds."""
    now = time.time()
    with dedupe_lock:
        last_seen = recent_labels.get(label, 0)
        if now - last_seen < DEDUPE_WINDOW:
            return True
        recent_labels[label] = now
        return False

def audio_worker():
    """Pulls from the priority queue and speaks detections one at a time."""
    while True:
        try:
            priority, label = audio_queue.get(timeout=1)
            message = "Sign %s detected" % label
            print(f"[AUDIO] Speaking: '{message}'")
            subprocess.run(["espeak", message], check=True)
            audio_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            print(f"[ERROR] Audio error: {e}")

def read_serial(port, name, priority):
    while True:
        ser = None
        try:
            ser = serial.Serial(port, BAUD, timeout=1)
            print(f"[INFO] {name} connected on {port}")

            while True:
                try:
                    raw = ser.readline()
                    if not raw:
                        continue

                    line = raw.decode("utf-8", errors="ignore").strip()
                    if not line:
                        continue

                    parts = line.split(":")
                    if len(parts) == 3:
                        device, label, confidence = parts
                        try:
                            conf_val = float(confidence)
                            print(f"[DETECTION] {name} detected '{label}' (confidence: {conf_val:.2f})")

                            # Only queue audio if not a recent duplicate
                            if not is_duplicate(label):
                                audio_queue.put((priority, label))

                        except ValueError:
                            pass  # malformed confidence value, skip

                except UnicodeDecodeError:
                    continue  # skip garbled bytes

        except serial.SerialException as e:
            print(f"[WARN] {name} on {port} disconnected or unavailable: {e}")
        finally:
            if ser and ser.is_open:
                ser.close()

        print(f"[INFO] Retrying {name} on {port} in {RECONNECT_DELAY}s...")
        time.sleep(RECONNECT_DELAY)

# ── Start audio worker thread ──
audio_thread = threading.Thread(target=audio_worker, daemon=True)
audio_thread.start()

# ── Start one thread per Nicla ──
threads = []
for port, name, priority in ports:
    t = threading.Thread(target=read_serial, args=(port, name, priority), daemon=True)
    t.start()
    threads.append(t)

print("[INFO] Listening on all Nicla ports. Press Ctrl+C to stop.\n")
try:
    while True:
        time.sleep(1)
except KeyboardInterrupt:
    print("\n[INFO] Shutting down.")