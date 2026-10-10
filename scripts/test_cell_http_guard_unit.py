"""Real TCP regression: headerless/partial HTTP must not exhaust an agent's sockets."""
import asyncio
import sys
from pathlib import Path

import uvicorn
from uvicorn.protocols.http.h11_impl import H11Protocol
from uvicorn.server import ServerState

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'cell-agent'))
try:
    from agent_http import HeaderDeadlineProtocol
except ImportError:
    HeaderDeadlineProtocol=H11Protocol # Baseline must reproduce the current leak.


async def app(scope,receive,send):
    if scope['path']=='/slow': await asyncio.sleep(.12)
    if scope['path']=='/upload':
        while True:
            message=await receive()
            if not message.get('more_body'): break
    await send({'type':'http.response.start','status':200,'headers':[(b'content-length',b'2')]})
    await send({'type':'http.response.body','body':b'OK'})


async def main():
    config=uvicorn.Config(app,lifespan='off',access_log=False,log_level='critical')
    config.load()
    config.header_deadline=.06
    config.max_pending_headers=12
    state=ServerState()
    loop=asyncio.get_running_loop()
    server=await loop.create_server(lambda:HeaderDeadlineProtocol(config,state,{},_loop=loop),'127.0.0.1',0)
    port=server.sockets[0].getsockname()[1]
    connections=[]
    failures=[]
    try:
        for _ in range(24):
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            connections.append((reader,writer))
        await asyncio.sleep(.01)
        if len(state.connections)>12: failures.append('pending connection cap not enforced')
        await asyncio.sleep(.1)
        live=len(state.connections)
        if live: failures.append(f'headerless connections never expire: {live}')
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        connections.append((reader,writer))
        writer.write(b'GET / HTTP/1.1\r\nHost:');await writer.drain()
        await asyncio.sleep(.1)
        if not reader.at_eof(): failures.append('partial headers never expire')
        for path in ('/health','/api/vpn/theme','/slow','/upload'):
            reader,writer=await asyncio.open_connection('127.0.0.1',port)
            connections.append((reader,writer))
            if path=='/upload':
                writer.write(b'POST /upload HTTP/1.1\r\nHost: local\r\nContent-Length: 2\r\nConnection: close\r\n\r\nA')
                await writer.drain();await asyncio.sleep(.12);writer.write(b'B')
            else: writer.write(f'GET {path} HTTP/1.1\r\nHost: local\r\nConnection: close\r\n\r\n'.encode())
            await writer.drain()
            body=await asyncio.wait_for(reader.read(),1)
            if b'200 OK' not in body or not body.endswith(b'OK'): failures.append(f'normal request interrupted: {path}')
        reader,writer=await asyncio.open_connection('127.0.0.1',port)
        connections.append((reader,writer))
        writer.write(b'GET /health HTTP/1.1\r\nHost: local\r\n\r\n');await writer.drain()
        await reader.readuntil(b'\r\n\r\n');await reader.readexactly(2)
        writer.write(b'GET / HTTP/1.1\r\nHost:');await writer.drain()
        await asyncio.sleep(.1)
        if not reader.at_eof(): failures.append('partial reused connection never expires')
        await asyncio.sleep(.02)
        if getattr(state,'pending_headers',0): failures.append('pending header budget leaked')
    finally:
        for reader,writer in connections: writer.close()
        await asyncio.gather(*(writer.wait_closed() for reader,writer in connections),return_exceptions=True)
        server.close();await server.wait_closed()
    for failure in failures:print('FAIL',failure)
    if not failures: print('PASS headerless/partial/reused TCP expires; health/API/slow response/streaming upload preserved')
    return bool(failures)


if __name__=='__main__':raise SystemExit(asyncio.run(main()))
