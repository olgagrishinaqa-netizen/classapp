import pytest


@pytest.mark.parametrize("endpoint", ["/api/users", "/api/news", "/api/tasks", "/api/reports"])
def test_protected_collections_require_authentication(client, endpoint):
    response = client.get(endpoint)

    assert response.status_code == 401
    assert response.get_json() == {"error": "Требуется авторизация"}