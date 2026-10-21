"""Fixed OAuth HTTP substitute used exclusively by isolated browser acceptance."""

import httpx


def install_oauth_mock():
    from app.services import oauth

    original = httpx.Client

    def handler(request):
        path = request.url.path
        if path.endswith("/me/permissions"):
            data = {"data": [{"permission": s, "status": "granted"} for s in oauth.META_SCOPES]}
        elif path.endswith("/me/accounts"):
            data = {"data": [{"id": str(100 + i), "name": f"隔離粉專 {i + 1}",
                "access_token": f"isolated-page-token-{i}"} for i in range(2)]}
        elif path.endswith("/oauth/access_token") or path == "/access_token":
            data = {"access_token": "isolated-oauth-token", "expires_in": 60 * 86400,
                "scope": ",".join(oauth.THREADS_SCOPES)}
        elif path.endswith("/me"):
            data = {"id": "300", "username": "isolated_threads"}
        else:
            data = {"instagram_business_account": {"id": "200", "username": "isolated_ig"}}
        return httpx.Response(200, json=data)

    class MockClient:
        def __init__(self, **kwargs):
            self.client = original(transport=httpx.MockTransport(handler), **kwargs)

        def __enter__(self):
            return self.client

        def __exit__(self, *args):
            self.client.close()

    # Substitute only OAuth's httpx reference, leaving other HTTP substitutes intact.
    from types import SimpleNamespace

    oauth.httpx = SimpleNamespace(Client=MockClient)
