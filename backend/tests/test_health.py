def test_health_check(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["code"] == 200
    assert payload["data"]["status"] == "healthy"
