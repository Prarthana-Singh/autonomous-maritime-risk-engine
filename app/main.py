from fastapi import FastAPI

app = FastAPI(title="Autonomous Maritime Risk Assessment Engine")


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
