import socket
import threading
import time

from ads1278_client.models import CommandOpcode, MessageType
from ads1278_client.protocol import (
    CAPABILITY_LINE,
    build_message,
    pack_set_enable,
    unpack_command,
)
from ads1278_client.transport import TransportClient


def test_transport_connects_reads_messages_and_sends_commands() -> None:
    received_commands = []
    sample = build_message(
        MessageType.SAMPLE,
        1,
        0,
        0,
        0x00010001,
        0x00000000,
        625,
        [1, 2, 3, 4, 5, 6, 7, 8],
    )
    ack = build_message(
        MessageType.ACK,
        2,
        CommandOpcode.SET_ENABLE,
        1,
        0x00020001,
        0x00000002,
        625,
        [11, 12, 13, 14, 15, 16, 17, 18],
    )

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind(("127.0.0.1", 0))
    server.listen(1)
    host, port = server.getsockname()

    def server_main() -> None:
        conn, _ = server.accept()
        with conn:
            conn.sendall(f"{CAPABILITY_LINE}\n".encode("ascii") + sample[:9])
            time.sleep(0.02)
            conn.sendall(sample[9:])
            command_payload = conn.recv(8)
            received_commands.append(unpack_command(command_payload))
            conn.sendall(ack[:13])
            time.sleep(0.02)
            conn.sendall(ack[13:])
            time.sleep(0.05)
        server.close()

    server_thread = threading.Thread(target=server_main, daemon=True)
    server_thread.start()

    messages = []
    connected_event = threading.Event()
    ack_event = threading.Event()

    transport = TransportClient(
        on_message=lambda message: (
            messages.append(message),
            ack_event.set() if message.msg_type == MessageType.ACK else None,
        ),
        on_connected=lambda capability: connected_event.set()
        if capability == CAPABILITY_LINE
        else None,
        on_disconnected=lambda reason: None,
        on_error=lambda reason: (_ for _ in ()).throw(AssertionError(reason)),
    )

    transport.connect(host, port, timeout_s=1.0)
    assert connected_event.wait(1.0)

    transport.send_command(pack_set_enable(True))
    assert ack_event.wait(1.0)

    transport.disconnect()
    server_thread.join(timeout=1.0)

    assert received_commands == [(CommandOpcode.SET_ENABLE, 1)]
    assert [message.msg_type for message in messages] == [
        MessageType.SAMPLE,
        MessageType.ACK,
    ]
