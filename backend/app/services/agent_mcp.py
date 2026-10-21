"""SDK Streamable HTTP on the web application's port; identity is per request."""

from contextvars import ContextVar

from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.services import agent_auth, agent_tools

connection: ContextVar[tuple] = ContextVar("agent_connection")


def build_manager(settings):
    server = Server("marketing-workbench", version=agent_auth.SERVER_VERSION,
                    instructions=agent_tools.INSTRUCTIONS)

    @server.list_tools()
    async def list_tools():
        return agent_tools.list_tools()

    # SDK schema errors quote input keys; our dispatcher never echoes validation inputs.
    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        factory, identity, origin, plugin_version = connection.get()
        return await run_in_threadpool(agent_tools.dispatch, factory, settings, identity,
                                       name, arguments, origin, plugin_version)

    backoffice = settings.backoffice_origin
    from urllib.parse import urlsplit

    return StreamableHTTPSessionManager(server, stateless=True, json_response=True,
        security_settings=TransportSecuritySettings(enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", urlsplit(backoffice).netloc],
            allowed_origins=["http://127.0.0.1:*", "http://localhost:*", backoffice]))


class MCPResponse(Response):
    def __init__(self, manager, factory, identity, origin, plugin_version=None):
        super().__init__()
        self.manager, self.factory, self.identity = manager, factory, identity
        self.origin = origin
        self.plugin_version = plugin_version

    async def __call__(self, scope, receive, send):
        context = connection.set((self.factory, self.identity, self.origin, self.plugin_version))
        try:
            await self.manager.handle_request(scope, receive, send)
        finally:
            connection.reset(context)
