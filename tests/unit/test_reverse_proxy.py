"""
Unit tests for reverse_proxy_xff_count configuration and ProxyFix middleware.
"""

import tempfile

from malla.config import AppConfig
from src.malla.web_ui import create_app


class TestReverseProxyConfig:
    """Test reverse_proxy_xff_count in AppConfig."""

    def test_default_is_none(self):
        cfg = AppConfig()
        assert cfg.reverse_proxy_xff_count is None

    def test_from_int(self):
        cfg = AppConfig(reverse_proxy_xff_count=2)
        assert cfg.reverse_proxy_xff_count == 2

    def test_env_override(self, monkeypatch):
        from malla.config import _clear_config_cache, load_config

        _clear_config_cache()
        monkeypatch.setenv("MALLA_REVERSE_PROXY_XFF_COUNT", "1")
        cfg = load_config(config_path=None)
        assert cfg.reverse_proxy_xff_count == 1
        _clear_config_cache()


class TestProxyFixMiddleware:
    """Test that ProxyFix is applied when reverse_proxy_xff_count is configured."""

    def _make_app(self, xff_count=None):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        cfg = AppConfig(
            database_file=temp_db.name,
            reverse_proxy_xff_count=xff_count,
        )
        app = create_app(cfg)
        return app, temp_db.name

    def test_no_proxy_fix_when_not_configured(self):
        app, db_path = self._make_app(xff_count=None)
        try:
            assert not hasattr(app.wsgi_app, "x_for")
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_applied_when_configured(self):
        app, db_path = self._make_app(xff_count=1)
        try:
            from werkzeug.middleware.proxy_fix import ProxyFix

            assert isinstance(app.wsgi_app, ProxyFix)
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_uses_configured_count(self):
        app, db_path = self._make_app(xff_count=3)
        try:
            assert app.wsgi_app.x_for == 3
            assert app.wsgi_app.x_proto == 3
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_respects_x_forwarded_for(self):
        app, db_path = self._make_app(xff_count=1)
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

    def test_proxy_fix_chains_multiple_proxies(self):
        app, db_path = self._make_app(xff_count=2)
        try:

            @app.route("/__test_multi")
            def test_multi():
                from flask import request

                return {"remote_addr": request.remote_addr}

            with app.test_client() as client:
                response = client.get(
                    "/__test_multi",
                    headers={
                        "X-Forwarded-For": "1.2.3.4, 10.0.0.1",
                    },
                )
                data = response.get_json()
                assert data["remote_addr"] == "1.2.3.4"
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_respects_x_forwarded_proto(self):
        app, db_path = self._make_app(xff_count=1)
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
        app, db_path = self._make_app(xff_count=None)
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
