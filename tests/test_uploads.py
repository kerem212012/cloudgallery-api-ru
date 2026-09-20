from pathlib import Path

import app.main as main
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    required = ("LocalStorage", "files", "get_storage")
    missing = [name for name in required if not hasattr(main, name)]
    if missing:
        pytest.fail(f"Implement the storage contract first; missing: {', '.join(missing)}")
    main.files.clear()
    main.app.dependency_overrides[main.get_storage] = lambda: main.LocalStorage(tmp_path)
    with TestClient(main.app) as test_client:
        yield test_client
    main.app.dependency_overrides.clear()


def test_upload_list_and_delete_image(client: TestClient, tmp_path: Path) -> None:
    png = b"\x89PNG\r\n\x1a\ncourse-image"
    uploaded = client.post("/images", files={"image": ("pixel.png", png, "image/png")})
    assert uploaded.status_code == 201
    key = uploaded.json()["key"]
    assert "/" not in key and "\\" not in key and ".." not in key
    assert (tmp_path / key).read_bytes() == png
    assert client.get("/images").json()[0]["key"] == key
    assert client.delete(f"/images/{key}").status_code == 204
    assert client.delete(f"/images/{key}").status_code == 404


def test_rejects_wrong_type_and_large_file(client: TestClient) -> None:
    assert (
        client.post("/images", files={"image": ("notes.txt", b"text", "text/plain")}).status_code
        == 415
    )
    assert (
        client.post(
            "/images", files={"image": ("pretend.png", b"not-an-image", "image/png")}
        ).status_code
        == 415
    )
    too_large = b"\x89PNG\r\n\x1a\n" + b"x" * (5 * 1024 * 1024)
    assert (
        client.post("/images", files={"image": ("large.png", too_large, "image/png")}).status_code
        == 413
    )
