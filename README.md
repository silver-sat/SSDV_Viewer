# SSDV_Viewer
Python GUI for decoding and viewing SSDV images in real time from SSDV frames streamed over UDP/IP.

The viewer requires PySide6 and Matplotlib. Install both packages, then run it from
the repository root:

```shell
python src/SSDV_Viewer.py
```

The viewer listens for SSDV frames on UDP port 5030. The SSDV decoder executable
must be available at `src/ssdv-win.exe` on Windows or `src/ssdv` on other platforms.
Use the **Source** button to choose UDP, a `.bin` file from `data`, Demo, or Radio;
Demo and Radio are placeholders.

Run the UDP transmitter with an optional file or folder, destination IP, and port:

```shell
python src/SSDV_UDP_Tx.py [file-or-folder] [ip] [port]
```

With no file or folder argument, it repeatedly sends each `.bin` file in `data`
twice before moving to the next file. File mode repeats the file continuously.

To encode JPEGs in `data` as SSDV `.bin` files with 195-byte packets, run:

```shell
python src/SSDV_Generator.py
```

Each JPEG gets a sequential image ID, starting at 0.
