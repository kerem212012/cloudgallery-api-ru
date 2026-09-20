from fastapi import FastAPI

app = FastAPI(title="CloudGallery API")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Add validated uploads and interchangeable local/S3 storage adapters.
