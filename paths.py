from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / 'data'
ENGINE_DIR = ROOT / 'engines'
LOG_DIR = ROOT / 'logs'
OUTPUT_DIR = ROOT / 'outputs'
SAMPLE_DIR = ROOT / 'sample_inputs'
for p in [DATA_DIR, LOG_DIR, OUTPUT_DIR, SAMPLE_DIR]:
    p.mkdir(parents=True, exist_ok=True)
