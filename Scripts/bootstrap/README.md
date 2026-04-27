# AI Coaching System

A self-hosted endurance training optimization engine.

## Vision
A system that handles cross-sport load accounting (Swim, Bike, Run), predicts HRV trends, and authors custom workouts from scratch using RAG and a 70B LLM (Ollama).

## Technical Stack
- **Data Ingestion**: Garmindb, garth, trainerroad-export
- **Analysis**: Python (Jupyter), Pandas, Numpy, Scipy (CTL/ATL/TSB, CSS extraction)
- **Time-Series Storage**: InfluxDB
- **Vector Storage**: Chroma / Qdrant
- **Inference**: Ollama (llama3 70B Q4)
- **Orchestration**: Python daily 3am loop
- **Output**: Garmin Connect (.fit) & Zwift (.zwo)

## Project Structure
- `backend/data_ingestion/`: API wrappers and sync logic.
- `backend/analysis/`: Core physiological model logic (Jupyter compatible).
- `backend/orchestration/`: Pipeline management and LLM context assembly.
- `backend/rag/`: Vector database indexing and retrieval.
- `backend/schemas/`: Pydantic models for structured JSON exchange.
- `frontend/grafana/`: Dashboards for fitness/fatigue visualization.
- `docs/`: Planning and architecture references.
