Incident Knowledge Copilot - ready architecture

1) Put incident CSV/XLSX files in data/csv.
2) Put Markdown/PDF knowledge in data/md and data/pdfs.
3) Run: python ingest.py
4) Start API: uvicorn api:app --host 0.0.0.0 --port 8000
5) Start UI: streamlit run ui.py

Dashboard:
- Top CI KPI is replaced by Average MTTR.
- MTTR is calculated by Python/Pandas from opened_at -> closed_at.
- MTTR trend and MTTR-by-priority charts are deterministic.
- Charts do not use Altair interactive() and have stable container sizing.
- Top 10 Route Causes remains deterministic.

AI:
- LLM is called ONLY by POST /api/proactive-analysis.
- Normal search, counts, route causes, MTTR, charts and incident lists do not call the LLM.
- Ollama must be running on port 11434.
- Set config.OLLAMA_MODEL to the Ollama model you have installed/imported from Hugging Face.

Python dependencies
        ↓
pip install -r requirements.txt

Local AI runtime
        ↓
Ollama
        ↓
llama3.2:1b

verify if packages are installed
python -c "import pandas, streamlit, fastapi, chromadb, sentence_transformers, pypdf, plotly; print('All Python dependencies OK')"

verify ollama in a seperate terminal
ollama list

run in sequence
step 1 - python ingest.py
step 2
Terminal 1 - python -m uvicorn api:app --host 0.0.0.0 --port 8000
Terminal 2 - streamlit run ui.py

Example Incident to test
------------------------
101483

Example Server/Ci to test
-------------------------
srv-web-prod-01