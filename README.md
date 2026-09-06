# ISL SignBridge

Indian Sign Language recognition for letters, numbers, greetings, and offline Windows speech.

## Run after cloning from GitHub

```powershell
cd ISL_Project
py -3.11 -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

Show one or two hands clearly in front of the webcam. Click the `CAMERA` or
`SPEECH TO SIGN` tab to switch views. Press `q` or `Esc` to exit.

## GitHub note

This is a desktop OpenCV application. GitHub Actions cannot access your webcam or play audio. Upload the repository to GitHub, then clone it and run `app.py` on a Windows computer with a webcam and speaker.

If `isl_FINAL.pkl` is not uploaded, rebuild it locally:

```powershell
python final_train.py
python app.py
```
