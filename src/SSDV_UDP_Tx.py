#!/usr/bin/env python3
# SSDV_UDP_Tx.py - read an SSDV file and transmit each frame over UDP
# using an IP address and port specified on the command line (default 
# values are localhost:5005).  The SSDV file is read in 256 byte blocks and each block is sent as a UDP packet.
# The program will loop through the file, and then repeat until the user presses Ctrl-C to exit.

import socket
import sys
import time
import os
delay_time = 1

if len(sys.argv) < 2:
    filename = "./data/FINAL_IMAGE.bin"
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

# Set up the UDP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
file_repeat = 1

while True:
    with open(filename, "rb") as f:
        print(f"Transmitting {filename} to {UDP_IP}:{UDP_PORT} (repeat {file_repeat})")
        while True:
            data = f.read(195)
            if not data:
                break
            sock.sendto(data, (UDP_IP, UDP_PORT))
            time.sleep(delay_time)  # small delay to avoid overwhelming the network
        file_repeat += 1