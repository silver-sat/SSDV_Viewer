#!/usr/bin/env python3
# SSDV_UDP_Tx.py - read an SSDV file and transmit each frame over UDP
# using an IP address and port specified on the command line (default 
# values are localhost:5005).  The SSDV file is read in 256 byte blocks and each block is sent as a UDP packet.
# The program will loop through the file, and then repeat until the user presses Ctrl-C to exit.

import socket
import sys
import time
from collections import Counter
from pathlib import Path

delay_time = 1
frame_size = 256

def estimate_frame_size(filename: Path) -> int | None:
    with filename.open("rb") as ssdv_file:
        data = ssdv_file.read()

    frame_starts = [
        offset
        for offset in range(len(data) - 1)
        if data[offset] == 0x55 and data[offset + 1] in (0x66, 0x67)
    ]
    if not frame_starts or frame_starts[0] != 0:
        return None
    if len(frame_starts) == 1:
        return len(data)

    frame_lengths = Counter(
        next_start - start
        for start, next_start in zip(frame_starts, frame_starts[1:])
    )
    return frame_lengths.most_common(1)[0][0]


def send_file(
    sock: socket.socket,
    filename: Path,
    packet_size: int,
    destination: tuple[str, int],
) -> None:
    # print(f"Transmitting {filename} to {destination[0]}:{destination[1]} (repeat {repeat})")
    with filename.open("rb") as ssdv_file:
        while True:
            data = ssdv_file.read(packet_size)
            if not data:
                break
            sock.sendto(data, destination)
            time.sleep(delay_time)  # small delay to avoid overwhelming the network


def main() -> None:
    if len(sys.argv) < 2:
        source = Path(__file__).resolve().parent.parent / "data"
    else:
        source = Path(sys.argv[1])

    udp_ip = sys.argv[2] if len(sys.argv) > 2 else "localhost"
    udp_port = int(sys.argv[3]) if len(sys.argv) > 3 else 5030
    destination = (udp_ip, udp_port)

    if source.is_dir():
        filenames = sorted(source.glob("*.bin"))
        if not filenames:
            # print(f"No .bin files found in {source}", file=sys.stderr)
            sys.exit(1)

        estimated_frame_sizes = {
            filename: estimate_frame_size(filename) for filename in filenames
        }
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            while True:
                for filename in filenames:
                    estimated_size = estimated_frame_sizes[filename]
                    packet_size = estimated_size or frame_size
                    for file_repeat in (1, 2):
                        send_file(sock, filename, packet_size, destination)
    elif source.is_file():
        estimated_frame_size = estimate_frame_size(source)
        packet_size = estimated_frame_size or frame_size

        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            file_repeat = 1
            while True:
                send_file(sock, source, packet_size, destination)
                file_repeat += 1
    else:
        # print(f"Input path does not exist: {source}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()