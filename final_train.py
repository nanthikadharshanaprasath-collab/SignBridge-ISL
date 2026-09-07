import os, pickle
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import cv2
import mediapipe as mp
import numpy as np

FEATURE_COUNT = 84
X, y = [], []


def pad_features(data):
    data = np.asarray(data, dtype=np.float32).reshape(-1)[:FEATURE_COUNT]
    if data.size >= 84:
        hands = [data[start:start + 42] for start in range(0, 84, 42)]
        present_hands = [hand for hand in hands if not np.allclose(hand, 0)]
        empty_hands = [hand for hand in hands if np.allclose(hand, 0)]
        present_hands.sort(key=lambda hand: hand[0])
        hands = present_hands + empty_hands
        data = np.concatenate(hands)
    normalized = np.zeros(FEATURE_COUNT, dtype=np.float32)
    for start in range(0, FEATURE_COUNT, 42):
        hand = data[start:start + 42]
        if hand.size < 42 or np.allclose(hand, 0):
            continue
        points = hand.reshape(21, 2)
        points = points - points[0]
        scale = np.max(np.linalg.norm(points, axis=1))
        if scale > 0:
            points = points / scale
        normalized[start:start + 42] = points.reshape(-1)
    data = normalized
    return np.pad(data, (0, FEATURE_COUNT - data.size))


def add_landmark_file(path, label):
    values = np.asarray(np.load(path), dtype=np.float32)
    frames = values if values.ndim == 2 else values.reshape(1, -1)

    for frame in frames:
        if frame.size >= 126:
            points = frame[:126].reshape(42, 3)[:, :2]
            features = points.reshape(-1)
        else:
            features = frame
        if features.size >= 42:
            X.append(pad_features(features))
            y.append(label)


def load_landmarks(root):
    for folder, _, files in os.walk(root):
        label = os.path.basename(folder)
        for name in files:
            if name.endswith('.npy'):
                try:
                    add_landmark_file(os.path.join(folder, name), label)
                except (OSError, ValueError):
                    pass


hands = mp.solutions.hands.Hands(
    static_image_mode=True,
    max_num_hands=2,
    min_detection_confidence=0.5,
)


def add_image_file(path, label):
    image = cv2.imread(path)
    if image is None:
        return
    result = hands.process(cv2.cvtColor(image, cv2.COLOR_BGR2RGB))
    if not result.multi_hand_landmarks:
        return
    features = []
    for hand in result.multi_hand_landmarks:
        for landmark in hand.landmark:
            features.extend((landmark.x, landmark.y))
    X.append(pad_features(features))
    y.append(label)


def load_images(root):
    for folder, _, files in os.walk(root):
        label = os.path.basename(folder)
        if label in {'kaggle_dataset', 'Indian'}:
            continue
        if label and label[0].isdigit():
            label = label[0]
        image_files = [
            name for name in files
            if name.lower().endswith(('.jpg', '.jpeg', '.png'))
        ][:150]
        for name in image_files:
            add_image_file(os.path.join(folder, name), label)


if os.path.exists('landmark_data'):
    print('Loading landmark videos...')
    load_landmarks('landmark_data')

if os.path.exists('kaggle_dataset'):
    print('Loading alphabet and number images...')
    load_images('kaggle_dataset')

hands.close()
print(f'Total samples: {len(X)} - Classes: {sorted(set(y))}')

if X:
    model = RandomForestClassifier(
        n_estimators=40,
        class_weight='balanced_subsample',
        n_jobs=-1,
        random_state=42,
    )
    model.fit(X, y)
    with open('isl_FINAL.pkl', 'wb') as file:
        pickle.dump((model, FEATURE_COUNT), file)
    print('SUCCESS! isl_FINAL.pkl created!')
else:
    print('No training data found.')

import joblib
joblib.dump(model, 'isl_FINAL_SMALL.pkl', compress=9)
print("Compressed model saved!")