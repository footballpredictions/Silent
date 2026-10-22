"""Read-only diagnosis of the physical DNS path while Silent VPN is connected."""
import json
import platform
import re
import socket
import struct
import subprocess


def physical_gateway():
    routes = subprocess.check_output(['netstat', '-rn', '-f', 'inet'], text=True)
    for line in routes.splitlines():
        fields = line.split()
        if len(fields) >= 4 and fields[0] == 'default':
            interfaces = [field for field in fields[3:] if re.fullmatch(r'(?:en|bridge|bond)[0-9]+', field)]
            if interfaces:
                return fields[1], interfaces[0]
    raise RuntimeError('Physical default route not found')


def probe(server, interface, local_address=None):
    query = struct.pack('!6H', 31415, 0x0100, 1, 0, 0, 0) + b'\x02ya\x02ru\x00\x00\x01\x00\x01'
    result = {'server': server, 'interface': interface, 'bind_local': bool(local_address)}
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
            client.settimeout(2)
            client.setsockopt(socket.IPPROTO_IP, getattr(socket, 'IP_BOUND_IF', 25), socket.if_nametoindex(interface))
            if local_address:
                client.bind((local_address, 0))
            client.connect((server, 53))
            result['source'] = client.getsockname()[0]
            client.send(query)
            answer = client.recv(4096)
            if len(answer) < 12 or struct.unpack('!H', answer[:2])[0] != 31415:
                raise RuntimeError('Unexpected DNS response')
            result['rcode'] = answer[3] & 15
            result['answers'] = struct.unpack('!H', answer[6:8])[0]
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
    return result


def main():
    if platform.system() != 'Darwin':
        raise SystemExit('Run this probe on the affected Mac with VPN and RU mode ON')
    gateway, interface = physical_gateway()
    local_address = subprocess.check_output(['ipconfig', 'getifaddr', interface], text=True).strip()
    socket.inet_aton(local_address)
    print(json.dumps({'physical_interface': interface, 'physical_address': local_address, 'gateway': gateway}), flush=True)
    for server in ['77.88.8.8', '77.88.8.1', gateway]:
        for bind_address in [None, local_address]:
            print(json.dumps(probe(server, interface, bind_address)), flush=True)


if __name__ == '__main__':
    main()
