import os
import pickle
import time
from collections import Counter, deque
from queue import Queue
from threading import Thread

import cv2
import mediapipe as mp
import numpy as np
import pyttsx3
import pythoncom
import speech_recognition as sr

CAMERA_TITLE = 'SignBridge | Camera'
SPEECH_TITLE = 'SignBridge | Speech to Sign'
FONT = cv2.FONT_HERSHEY_SIMPLEX
speech_queue = Queue()
speech_request = None
speech_status = 'Say a greeting or letter'

with open('isl_FINAL.pkl', 'rb') as model_file:
    loaded_model = pickle.load(model_file)
model, max_len = loaded_model if isinstance(loaded_model, tuple) else (loaded_model, 84)

GREETING_VIDEOS = {
    'good morning': 'good morning',
    'good night': 'good night',
    'good afternoon': 'good afternoon',
    'good evening': 'good evening',
    'thanks': 'thanks',
    'thank you': 'thanks',
}
GREETING_ALIASES = {
    'goodmorning': 'good morning',
    'good mourning': 'good morning',
    'goodnight': 'good night',
    'goodafternoon': 'good afternoon',
    'goodevening': 'good evening',
}
SIGN_LABELS = set('ABCDEFGHIJKLMNOPQRSTUVWXYZ123456789') | set(GREETING_VIDEOS.values())
MIN_DETECTION_CONFIDENCE = 0.35
NUMBER_WORDS = {
    'zero': '0', 'one': '1', 'two': '2', 'three': '3', 'four': '4',
    'five': '5', 'six': '6', 'seven': '7', 'eight': '8', 'nine': '9',
}
LETTER_WORDS = {
    'ay': 'A', 'a': 'A', 'hey': 'A', 'bee': 'B', 'be': 'B', 'see': 'C', 'sea': 'C',
    'dee': 'D', 'd': 'D', 'ee': 'E',
    'eff': 'F', 'gee': 'G', 'aitch': 'H', 'eye': 'I', 'jay': 'J',
    'kay': 'K', 'el': 'L', 'em': 'M', 'en': 'N', 'oh': 'O',
    'pee': 'P', 'cue': 'Q', 'are': 'R', 'ess': 'S', 'tee': 'T',
    'you': 'U', 'vee': 'V', 'double you': 'W', 'ex': 'X',
    'why': 'Y', 'zee': 'Z', 'zed': 'Z',
}


def spoken_sign_label(spoken_text):
    words = spoken_text.lower().replace('-', ' ').split()
    if not words:
        return None
    for start in range(len(words)):
        phrase = ' '.join(words[start:])
        if phrase in LETTER_WORDS:
            return LETTER_WORDS[phrase]
        if phrase in NUMBER_WORDS:
            return NUMBER_WORDS[phrase]
        if len(words[start]) == 1 and (words[start].isalpha() or words[start].isdigit()):
            return words[start].upper()
        if words[start] in {'letter', 'letters', 'alphabet', 'number', 'numbers'}:
            if start + 1 < len(words):
                candidate = words[start + 1]
                if candidate in LETTER_WORDS:
                    return LETTER_WORDS[candidate]
                if candidate in NUMBER_WORDS or len(candidate) == 1 and candidate.isdigit():
                    return NUMBER_WORDS.get(candidate, candidate)
    return None


def speech_worker():
    pythoncom.CoInitialize()
    engine = pyttsx3.init('sapi5')
    voices = engine.getProperty('voices')
    if voices:
        engine.setProperty('voice', voices[0].id)
    engine.setProperty('rate', 145)
    try:
        while True:
            label = speech_queue.get()
            if label is None:
                speech_queue.task_done()
                break
            try:
                engine.say(str(label))
                engine.runAndWait()
            except Exception as error:
                print(f'Audio error: {error}')
            finally:
                speech_queue.task_done()
    finally:
        engine.stop()
        pythoncom.CoUninitialize()


def speech_to_sign_worker():
    global speech_request, speech_status
    recognizer = sr.Recognizer()
    try:
        microphone_names = sr.Microphone.list_microphone_names()
        microphone_index = next(
            (
                index for index, name in enumerate(microphone_names)
                if 'stereo mix' not in name.lower()
                and ('microphone array' in name.lower() or 'microphone' in name.lower())
            ),
            None,
        )
        microphone = sr.Microphone(device_index=microphone_index)
        with microphone as microphone_source:
            recognizer.dynamic_energy_threshold = True
            recognizer.pause_threshold = 0.8
            recognizer.phrase_threshold = 0.2
            recognizer.non_speaking_duration = 0.3
            recognizer.adjust_for_ambient_noise(microphone_source, duration=1)
            speech_status = 'Listening... Speak now'
            while True:
                try:
                    audio = recognizer.listen(microphone_source, timeout=1, phrase_time_limit=4)
                    recognition = recognizer.recognize_google(
                        audio, language='en-IN', show_all=True
                    )
                    alternatives = [
                        item.get('transcript', '').lower().strip()
                        for item in recognition.get('alternative', [])
                        if item.get('transcript')
                    ] if isinstance(recognition, dict) else []
                    spoken_text = next(
                        (
                            text for text in alternatives
                            if any(phrase in text for phrase in GREETING_VIDEOS)
                            or spoken_sign_label(text)
                        ),
                        alternatives[0] if alternatives else '',
                    )
                    if not spoken_text:
                        raise sr.UnknownValueError()
                    for alias, greeting in GREETING_ALIASES.items():
                        spoken_text = spoken_text.replace(alias, greeting)
                    speech_status = f'Heard: {spoken_text}'
                    matched_folder = next(
                        (folder for phrase, folder in GREETING_VIDEOS.items() if phrase in spoken_text),
                        None,
                    )
                    if matched_folder:
                        video_files = [
                            name for name in os.listdir(matched_folder)
                            if name.lower().endswith(('.mp4', '.avi', '.mov'))
                        ]
                        if video_files:
                            speech_request = os.path.join(matched_folder, video_files[0])
                            speech_status = matched_folder.upper()
                            continue
                    spoken_label = spoken_sign_label(spoken_text)
                    if spoken_label:
                        image_folder = os.path.join('kaggle_dataset', 'Indian', spoken_label)
                        image_files = [
                            name for name in os.listdir(image_folder)
                            if name.lower().endswith(('.jpg', '.jpeg', '.png'))
                        ] if os.path.isdir(image_folder) else []
                        if image_files:
                            speech_request = os.path.join(image_folder, image_files[0])
                            speech_status = spoken_label
                        else:
                            speech_status = f'No sign found for: {spoken_text}'
                    elif not matched_folder:
                        speech_status = f'No sign found for: {spoken_text}'
                except sr.WaitTimeoutError:
                    continue
                except sr.UnknownValueError:
                    speech_status = 'Could not understand. Speak clearly'
                except sr.RequestError:
                    speech_status = 'Speech service unavailable. Check internet'
    except Exception as error:
        speech_status = 'Microphone unavailable'
        print(f'Microphone unavailable: {error}')


def normalize_landmarks(data, feature_count):
    if len(data) >= 84:
        hand_data = [data[start:start + 42] for start in range(0, 84, 42)]
        present_hands = [hand for hand in hand_data if not np.allclose(hand, 0)]
        empty_hands = [hand for hand in hand_data if np.allclose(hand, 0)]
        present_hands.sort(key=lambda hand: hand[0])
        data = np.concatenate(present_hands + empty_hands).tolist()
    normalized = np.zeros(feature_count, dtype=np.float32)
    for start in range(0, feature_count, 42):
        hand = np.asarray(data[start:start + 42], dtype=np.float32)
        if hand.size < 42 or np.allclose(hand, 0):
            continue
        points = hand.reshape(21, 2)
        points -= points[0]
        scale = np.max(np.linalg.norm(points, axis=1))
        normalized[start:start + 42] = (points / scale if scale else points).reshape(-1)
    return normalized


def draw_sign_text(frame, label):
    if not label:
        return frame
    height, width = frame.shape[:2]
    text_size, _ = cv2.getTextSize(label, FONT, 1.5, 3)
    text_x = max(20, (width - text_size[0]) // 2)
    text_y = max(70, height - 55)
    cv2.putText(frame, label, (text_x + 2, text_y + 2), FONT, 1.5, (0, 0, 0), 5)
    cv2.putText(frame, label, (text_x, text_y), FONT, 1.5, (255, 255, 255), 3)
    return frame


Thread(target=speech_worker, daemon=True).start()
speech_queue.put('SignBridge ready')
Thread(target=speech_to_sign_worker, daemon=True).start()

mp_hands = mp.solutions.hands
hands = mp_hands.Hands(max_num_hands=2, min_detection_confidence=0.5, min_tracking_confidence=0.5)
mp_draw = mp.solutions.drawing_utils

cap = None
for camera_index in range(4):
    for backend in (cv2.CAP_ANY, cv2.CAP_DSHOW):
        camera = cv2.VideoCapture(camera_index, backend)
        if camera.isOpened() and camera.read()[0]:
            cap = camera
            print(f'Camera opened: index={camera_index}, backend={backend}')
            break
        camera.release()
    if cap is not None:
        break
if cap is None:
    raise RuntimeError('Camera not found. Close other camera apps and reconnect the webcam.')
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 960)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 540)

selected_tab = 0


def select_tab(event, x, y, flags, param):
    global selected_tab
    if event == cv2.EVENT_LBUTTONDOWN and y < 72:
        selected_tab = 0 if x < 480 else 1


for old_window in (CAMERA_TITLE, SPEECH_TITLE):
    try:
        cv2.destroyWindow(old_window)
    except cv2.error:
        pass
cv2.namedWindow('SignBridge', cv2.WINDOW_NORMAL)
cv2.resizeWindow('SignBridge', 960, 612)
cv2.moveWindow('SignBridge', 40, 40)
cv2.setMouseCallback('SignBridge', select_tab)
cv2.setWindowProperty('SignBridge', cv2.WND_PROP_TOPMOST, 1)

speech_capture = None
speech_image = None
last_spoken_label = None
last_speech_time = 0.0
last_frame_time = time.perf_counter()
fps = 0.0
detected_history = deque(maxlen=6)

while True:
    ret, frame = cap.read()
    if not ret:
        break
    current_time = time.perf_counter()
    elapsed = current_time - last_frame_time
    fps = 0.9 * fps + 0.1 / elapsed if elapsed > 0 else fps
    last_frame_time = current_time
    frame = cv2.flip(frame, 1)

    if speech_request:
        if speech_capture is not None:
            speech_capture.release()
        if speech_request.lower().endswith(('.jpg', '.jpeg', '.png')):
            speech_image = cv2.imread(speech_request)
            speech_capture = None
        else:
            speech_image = None
            speech_capture = cv2.VideoCapture(speech_request)
            if not speech_capture.isOpened():
                speech_status = 'Could not open sign video'
                speech_capture.release()
                speech_capture = None
        speech_request = None

    if speech_capture is not None:
        video_ok, speech_frame = speech_capture.read()
        if video_ok:
            speech_image = speech_frame
        else:
            speech_capture.release()
            speech_capture = None

    result = hands.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
    if result.multi_hand_landmarks:
        all_data = []
        for hand_landmarks in result.multi_hand_landmarks:
            all_data.extend(value for landmark in hand_landmarks.landmark for value in (landmark.x, landmark.y))
            mp_draw.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)
        features = (all_data[:max_len] + [0] * max(0, max_len - len(all_data)))[:max_len]
        probabilities = model.predict_proba([normalize_landmarks(features, max_len)])[0]
        sign_indices = [
            index for index, label in enumerate(model.classes_)
            if str(label) in SIGN_LABELS
        ]
        best_index = sign_indices[int(np.argmax(probabilities[sign_indices]))]
        best_label = str(model.classes_[best_index])
        best_probability = float(probabilities[best_index])
        detected_history.append(best_label)
        stable_label, stable_count = Counter(detected_history).most_common(1)[0]
        if stable_count >= 3:
            best_label = stable_label
        confident_detection = best_probability >= MIN_DETECTION_CONFIDENCE and stable_count >= 3
        if current_time - last_speech_time >= 2.5 and confident_detection:
            speech_queue.put(best_label)
            last_spoken_label = best_label
            last_speech_time = current_time
        frame = draw_sign_text(frame, best_label if confident_detection else 'HOLD SIGN STEADY')
    else:
        detected_history.clear()
        last_spoken_label = None
        last_speech_time = 0.0

    speech_panel = np.full((540, 430, 3), (20, 31, 45), dtype=np.uint8)
    cv2.rectangle(speech_panel, (0, 0), (429, 539), (58, 78, 96), 2)
    cv2.putText(speech_panel, 'SPEECH TO SIGN', (24, 42), FONT, 0.75, (235, 245, 248), 2)
    speech_active = 'unavailable' not in speech_status.lower()
    cv2.circle(speech_panel, (388, 34), 7, (72, 211, 160) if speech_active else (70, 80, 92), -1)
    cv2.putText(speech_panel, speech_status[:42], (24, 76), FONT, 0.43, (104, 211, 222), 1)
    if speech_image is not None:
        cv2.rectangle(speech_panel, (23, 107), (407, 431), (104, 211, 222), 1)
        speech_panel[108:428, 24:424] = cv2.resize(speech_image, (400, 320))
    else:
        cv2.rectangle(speech_panel, (24, 108), (406, 427), (42, 61, 78), -1)
        cv2.circle(speech_panel, (215, 244), 42, (35, 55, 72), -1)
        cv2.circle(speech_panel, (215, 244), 42, (104, 211, 222), 2)
        cv2.putText(speech_panel, 'MIC', (190, 254), FONT, 0.65, (235, 245, 248), 2)
        cv2.putText(speech_panel, 'Speak now', (156, 390), FONT, 0.6, (150, 174, 188), 1)
    cv2.putText(speech_panel, 'LIVE TRANSLATION', (24, 480), FONT, 0.42, (150, 174, 188), 1)
    cv2.putText(speech_panel, 'Listening for signs and phrases', (24, 508), FONT, 0.43, (210, 220, 225), 1)
    cv2.putText(speech_panel, 'LETTERS A-Z  |  NUMBERS 1-9', (24, 532), FONT, 0.38, (104, 211, 222), 1)

    tabbed_view = np.full((612, 960, 3), (11, 19, 29), dtype=np.uint8)
    if selected_tab == 0:
        camera_view = cv2.resize(frame, (960, 540))
        cv2.rectangle(camera_view, (12, 12), (947, 527), (104, 211, 222), 2)
        cv2.rectangle(camera_view, (28, 28), (250, 78), (11, 19, 29), -1)
        cv2.putText(camera_view, 'LIVE CAMERA', (44, 53), FONT, 0.55, (235, 245, 248), 2)
        cv2.circle(camera_view, (222, 51), 7, (72, 211, 160), -1)
        cv2.rectangle(camera_view, (712, 28), (932, 78), (11, 19, 29), -1)
        cv2.putText(camera_view, f'{fps:04.1f} FPS', (746, 59), FONT, 0.58, (104, 211, 222), 2)
        if result.multi_hand_landmarks and confident_detection:
            cv2.rectangle(camera_view, (28, 460), (340, 512), (11, 19, 29), -1)
            cv2.putText(camera_view, f'DETECTED  {best_label}', (45, 493), FONT, 0.58, (235, 245, 248), 2)
        else:
            cv2.rectangle(camera_view, (28, 460), (340, 512), (11, 19, 29), -1)
            cv2.putText(camera_view, 'PLACE HAND IN FRAME', (45, 493), FONT, 0.48, (150, 174, 188), 1)
        tabbed_view[72:612] = camera_view
    else:
        tabbed_view[72:612, 265:695] = speech_panel
    tab_width = tabbed_view.shape[1] // 2
    cv2.rectangle(tabbed_view, (0, 0), (959, 71), (20, 31, 45), -1)
    cv2.line(tabbed_view, (0, 71), (959, 71), (58, 78, 96), 1)
    active_x = 0 if selected_tab == 0 else tab_width
    cv2.rectangle(tabbed_view, (active_x + 18, 62), (active_x + tab_width - 18, 66), (104, 211, 222), -1)
    cv2.putText(tabbed_view, 'SIGNBRIDGE', (26, 31), FONT, 0.58, (235, 245, 248), 2)
    cv2.putText(tabbed_view, 'ISL', (26, 54), FONT, 0.34, (104, 211, 222), 1)
    cv2.putText(tabbed_view, 'CAMERA', (190, 43), FONT, 0.65, (235, 245, 248), 2)
    cv2.putText(tabbed_view, 'SPEECH TO SIGN', (605, 43), FONT, 0.65, (235, 245, 248), 2)
    cv2.putText(tabbed_view, 'Q / ESC  EXIT', (820, 22), FONT, 0.34, (150, 174, 188), 1)
    cv2.putText(tabbed_view, 'SIGN RECOGNITION SYSTEM', (820, 51), FONT, 0.28, (104, 211, 222), 1)
    cv2.imshow('SignBridge', tabbed_view)
    key = cv2.waitKey(1) & 0xFF
    if key == ord('q') or key == 27:
        break

cap.release()
hands.close()
if speech_capture is not None:
    speech_capture.release()
cv2.destroyAllWindows()
