BASE = "/api/candidate-profile"


def test_latest_is_null_when_empty(client):
    res = client.get(f"{BASE}/latest")
    assert res.status_code == 200
    assert res.json() is None