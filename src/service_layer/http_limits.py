"""Bound request bodies before JSON parsing and job admission."""
import asyncio


class BodyLimitMiddleware:
    def __init__(self, app, limit=70000, timeout_seconds=15):
        self.app, self.limit, self.timeout = app, limit, timeout_seconds

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()

        async def collect():
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return False
                body.extend(message.get("body", b""))
                if len(body) > self.limit:
                    raise OverflowError
                if not message.get("more_body", False):
                    return True

        try:
            complete = await asyncio.wait_for(collect(), timeout=self.timeout)
        except (OverflowError, asyncio.TimeoutError) as error:
            # 为什么要有它：请求尚未入队前就限制内存和读取时间，分块上传不能绕过Content-Length检查。
            status = 413 if isinstance(error, OverflowError) else 408
            await send({"type": "http.response.start", "status": status,
                        "headers": [(b"content-type", b"application/json")]})
            await send({"type": "http.response.body", "body": b'{"detail":"Request body limit exceeded"}'})
            return
        if not complete:
            return
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)
