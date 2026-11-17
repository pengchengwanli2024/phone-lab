"""Verification subprocess guard: only loopback ports opened by this run."""
import ipaddress
import json
import os
from pathlib import Path
import socket

_ports = os.environ.get('VERIFY_PORTS_FILE')
_denials = os.environ.get('VERIFY_DENIALS_FILE')


def _loopback(host):
    if host == 'localhost':
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _record(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    try:
        os.write(fd, (json.dumps(value) + '\n').encode())
    finally:
        os.close(fd)


def _deny():
    _record(_denials, {'runtime': 'python', 'reason': 'unregistered fixture connection or external DNS'})
    raise PermissionError('verification_network_denied')


def _allowed(address):
    if not isinstance(address, tuple) or len(address) < 2 or not _loopback(address[0]):
        return False
    try:
        return int(address[1]) in {json.loads(line)['port'] for line in Path(_ports).read_text().splitlines()}
    except (OSError, ValueError, KeyError):
        return False


if _ports and _denials:
    _bind = socket.socket.bind
    _connect = socket.socket.connect
    _connect_ex = socket.socket.connect_ex
    _getaddrinfo = socket.getaddrinfo

    def bind(self, address):
        if self.family not in (socket.AF_INET, socket.AF_INET6) or not _loopback(address[0]):
            _deny()
        result = _bind(self, address)
        _record(_ports, {'port': self.getsockname()[1]})
        return result

    def connect(self, address):
        if not _allowed(address):
            _deny()
        return _connect(self, address)

    def connect_ex(self, address):
        if not _allowed(address):
            _deny()
        return _connect_ex(self, address)

    def getaddrinfo(host, *args, **kwargs):
        if host is not None and not _loopback(host):
            _deny()
        return _getaddrinfo(host, *args, **kwargs)

    socket.socket.bind = bind
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    socket.getaddrinfo = getaddrinfo
    os.environ['VERIFY_NETWORK_GUARD_ACTIVE'] = '1'
