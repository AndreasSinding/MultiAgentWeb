
# Market Insights – Multi-Agent Crew API

## Local dev
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --host 127.0.0.1 --port 8765
