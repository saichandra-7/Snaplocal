"""
SnapLocal Server Runner.
Launches the Flask web application with auto-port detection and configuration.
"""

import socket
import os
from app import app


def is_port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0


def find_available_port(start_port: int = 5000, max_tries: int = 20) -> int:
    port = start_port
    while is_port_in_use(port) and max_tries > 0:
        port += 1
        max_tries -= 1
    return port


if __name__ == '__main__':
    port = find_available_port(5000)
    print("\n" + "=" * 60)
    print(" [SNAPLOCAL] HYPERLOCAL PHOTOGRAPHY MARKETPLACE")
    print("=" * 60)
    print(f" Web Interface: http://127.0.0.1:{port}")
    print(f" Customer Dashboard: http://127.0.0.1:{port}/customer")
    print(f" Provider Hub & Earnings: http://127.0.0.1:{port}/provider")
    print(f" Admin Dashboard: http://127.0.0.1:{port}/admin")
    print("=" * 60 + "\n")
    app.run(host='0.0.0.0', port=port, debug=False)
