import importlib

modules = [
    "librosa",
    "numpy",
    "scipy",
    "pandas",
    "sklearn",
    "joblib",
    "sounddevice",
    "soundfile",
]

for m in modules:
    try:
        importlib.import_module(m)
        print(f"PASS: {m}")
    except Exception as e:
        print(f"FAIL: {m} -> {e}")
