"""Unit tests for trusted proxy configuration and middleware wiring."""

import tempfile

from werkzeug.middleware.proxy_fix import ProxyFix

from src.malla.config import AppConfig
from src.malla.web_ui import create_app
from src.malla.wsgi import _build_gunicorn_config


class TestTrustedProxyConfig:
    """Test trusted_proxy_ips in AppConfig."""

    def test_default_is_none(self):
        cfg = AppConfig()
        assert cfg.trusted_proxy_ips is None

    def test_from_string(self):
        cfg = AppConfig(trusted_proxy_ips="10.89.0.90")
        assert cfg.trusted_proxy_ips == "10.89.0.90"

    def test_env_override(self, monkeypatch):
        from src.malla.config import _clear_config_cache, load_config

        _clear_config_cache()
        monkeypatch.setenv("MALLA_TRUSTED_PROXY_IPS", "10.89.0.90,10.89.0.91")
        cfg = load_config(config_path=None)
        assert cfg.trusted_proxy_ips == "10.89.0.90,10.89.0.91"


class TestProxyFixMiddleware:
    """Test that ProxyFix is applied when trusted_proxy_ips is configured."""

    def _make_app(self, trusted_proxy_ips=None):
        temp_db = tempfile.NamedTemporaryFile(delete=False, suffix=".db")
        temp_db.close()
        cfg = AppConfig(
            database_file=temp_db.name,
            trusted_proxy_ips=trusted_proxy_ips,
        )
        app = create_app(cfg)
        return app, temp_db.name

    def test_no_proxy_fix_when_not_configured(self):
        app, db_path = self._make_app(trusted_proxy_ips=None)
        try:
            assert not isinstance(app.wsgi_app, ProxyFix)
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_applied_when_configured(self):
        app, db_path = self._make_app(trusted_proxy_ips="10.89.0.90")
        try:
            assert isinstance(app.wsgi_app, ProxyFix)
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_uses_single_hop(self):
        app, db_path = self._make_app(trusted_proxy_ips="10.89.0.90")
        try:
            assert isinstance(app.wsgi_app, ProxyFix)
            assert app.wsgi_app.x_for == 1
            assert app.wsgi_app.x_proto == 1
        finally:
            import os

            os.unlink(db_path)

    def test_proxy_fix_respects_x_forwarded_for(self):
        app, db_path = self._make_app(trusted_proxy_ips="10.89.0.90")
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
        app, db_path = self._make_app(trusted_proxy_ips="10.89.0.90")
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


def test_gunicorn_uses_trusted_proxy_ips():
    cfg = AppConfig(trusted_proxy_ips="10.89.0.90,10.89.0.91")
    gunicorn_config = _build_gunicorn_config(cfg)

    assert gunicorn_config["forwarded_allow_ips"] == "10.89.0.90,10.89.0.91"


def test_gunicorn_leaves_forwarded_allow_ips_unset_when_not_configured():
    cfg = AppConfig(trusted_proxy_ips=None)
    gunicorn_config = _build_gunicorn_config(cfg)

    assert "forwarded_allow_ips" not in gunicorn_config
