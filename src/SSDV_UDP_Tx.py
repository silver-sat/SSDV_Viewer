#!/usr/bin/env python3
# SSDV_UDP_Tx.py - read an SSDV file and transmit each frame over UDP
# using an IP address and port specified on the command line (default 
# values are localhost:5005).  The SSDV file is read in 256 byte blocks and each block is sent as a UDP packet.
# The program will loop through the file, and then repeat until the user presses Ctrl-C to exit.

import socket
import sys
import time
import os
from collections import Counter

delay_time = 1
frame_size = 256

if len(sys.argv) < 2:
    filename = "./data/testpic.bin"
else:
    filename = sys.argv[1]

if len(sys.argv) > 2:
    UDP_IP = sys.argv[2]
else:
    UDP_IP = "localhost"

if len(sys.argv) > 3:
    UDP_PORT = int(sys.argv[3])
else:
    UDP_PORT = 5030


def estimate_frame_size(filename: str) -> int | None:
    with open(filename, "rb") as ssdv_file:
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


estimated_frame_size = estimate_frame_size(filename)
if estimated_frame_size is not None:
    frame_size = estimated_frame_size
    print(f" Now transmitting {filename} to {UDP_IP}:{UDP_PORT}. Estimated frame size: {frame_size}")

# Set up the UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
file_repeat = 1

while True:
    with open(filename, "rb") as f:
        print(f"Transmitting {filename} to {UDP_IP}:{UDP_PORT} (repeat {file_repeat})")
        while True:
            data = f.read(frame_size)
            if not data:
                break
            sock.sendto(data, (UDP_IP, UDP_PORT))
            time.sleep(delay_time)  # small delay to avoid overwhelming the network
        file_repeat += 1