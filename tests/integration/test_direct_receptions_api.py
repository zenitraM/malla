import pytest


class TestDirectReceptionsAPI:
    @pytest.mark.integration
    def test_direct_receptions_endpoint(self, client):
        """Ensure the endpoint returns expected JSON keys and HTTP 200."""
        # The fixture database contains example node 1128074276
        response = client.get("/api/node/1128074276/direct-receptions?limit=10")
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data
        assert "total_count" in data

        # direct_receptions should be a list
        assert isinstance(data["direct_receptions"], list)

    @pytest.mark.integration
    def test_direct_receptions_received_direction(self, client):
        """Test the received direction parameter."""
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=received&limit=10"
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data
        assert "total_count" in data
        assert "direction" in data
        assert data["direction"] == "received"

        # direct_receptions should be a list
        assert isinstance(data["direct_receptions"], list)

    @pytest.mark.integration
    def test_direct_receptions_transmitted_direction(self, client):
        """Test the transmitted direction parameter."""
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=transmitted&limit=10"
        )
        assert response.status_code == 200

        data = response.get_json()
        assert "direct_receptions" in data
        assert "total_count" in data
        assert "direction" in data
        assert data["direction"] == "transmitted"

        # direct_receptions should be a list
        assert isinstance(data["direct_receptions"], list)

    @pytest.mark.integration
    def test_direct_receptions_invalid_direction(self, client):
        """Test that invalid direction parameter returns 400."""
        response = client.get(
            "/api/node/1128074276/direct-receptions?direction=invalid"
        )
        assert response.status_code == 400

        data = response.get_json()
        assert "error" in data
        assert "Invalid direction" in data["error"]
