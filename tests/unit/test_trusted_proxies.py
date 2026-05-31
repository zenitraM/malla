"""
Unit tests for trusted_proxies configuration and ProxyFix middleware.
"""

import tempfile

from malla.config import AppConfig
from src.malla.web_ui import create_app


class TestTrustedProxiesConfig:
    """Test trusted_proxies in AppConfig."""

    def test_default_trusted_proxies_is_none(self):
        cfg = AppConfig()
        assert cfg.trusted_proxies is None

    def test_trusted_proxies_from_string(self):
        cfg = AppConfig(trusted_proxies="10.0.0.0/8,172.16.0.0/12")
        assert cfg.trusted_proxies == "10.0.0.0/8,172.16.0.0/12"

    def test_trusted_proxies_env_override(self, monkeypatch):
        from malla.config import _clear_config_cache, load_config

        _clear_config_cache()
        monkeypatch.setenv("MALLA_TRUSTED_PROXIES", "192.168.1.0/24")
        cfg = load_config(config_path=None)
        assert cfg.trusted_proxies == "192.168.1.0/24"
        _clear_config_cache()


class TestProxyFixMiddleware:
    """Test that ProxyFix is applied when trusted_proxies is configured."""

    def _make_app(self, trusted_proxies=None):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        cfg = AppConfig(
            database_file=temp_db.name,
            trusted_proxies=trusted_proxies,
        )
        app = create_app(cfg)
        return app, temp_db.name

    def test_no_proxy_fix_when_not_configured(self):
        app, db_path = self._make_app(trusted_proxies=None)
        try:
            assert not hasattr(app.wsgi_app, "x_for")
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_applied_when_configured(self):
        app, db_path = self._make_app(trusted_proxies="10.0.0.0/8")
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix

            assert isinstance(app.wsgi_app, ProxyFix)
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_uses_default_proxy_count(self):
        app, db_path = self._make_app(trusted_proxies="10.0.0.0/8")
        try:
            assert app.wsgi_app.x_for == 1
            assert app.wsgi_app.x_proto == 1
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_respects_x_forwarded_for(self):
        app, db_path = self._make_app(trusted_proxies="10.0.0.0/8")
        try:

            @app.route("/__test_ip")
            def test_ip():
                from flask import request

                return {"remote_addr": request.remote_addr}

            with app.test_client() as client:
                response = client.get(
                    "/__test_ip",
                    headers={
                        "X-Forwarded-For": "1.2.3.4",
                    },
                )
                data = response.get_json()
                assert data["remote_addr"] == "1.2.3.4"
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_respects_x_forwarded_proto(self):
        app, db_path = self._make_app(trusted_proxies="10.0.0.0/8")
        try:

            @app.route("/__test_scheme")
            def test_scheme():
                from flask import request

                return {"scheme": request.scheme}

            with app.test_client() as client:
                response = client.get(
                    "/__test_scheme",
                    headers={
                        "X-Forwarded-Proto": "https",
                    },
                )
                data = response.get_json()
                assert data["scheme"] == "https"
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_without_headers_keeps_defaults(self):
        app, db_path = self._make_app(trusted_proxies=None)
        try:

            @app.route("/__test_ip_default")
            def test_ip_default():
                from flask import request

                return {"remote_addr": request.remote_addr}

            with app.test_client() as client:
                response = client.get(
                    "/__test_ip_default",
                    headers={
                        "X-Forwarded-For": "9.9.9.9",
                    },
                )
                data = response.get_json()
                assert data["remote_addr"] == "127.0.0.1"
        finally:
            import os

            os.unlink(db_path)
