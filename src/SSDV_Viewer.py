from pathlib import Path
import PySimpleGUI as sg
import matplotlib.image as mpimg
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
import time
import os
import subprocess
import numpy as np
import zlib
import socket

# Global variables
GUI_timeout = 0.01  # Delay between frames in seconds
socket_timeout = 0.05  # Timeout for the UDP socket in seconds
frame_count = 0  # Counter for the number of frames processed
frame_pos = 0  # Position of the next frame to read
buf_size = 1024  # Size of the buffer for receiving UDP packets

class ssdv_frame:
    def __init__(self, frame: bytes, source: str = "") -> None:
        self.frame = frame
        self.source = source
        self.size = len(self.frame)
        self.valid = False
        self.packet_type = 0
        self.callsign = ""
        self.image_id = 0
        self.packet_id = 0
        self.width = 0
        self.height = 0
        self.flags = 0
        self.mcu_offset = 0
        self.mcu_index = 0
        if self.frame[0] != 0x55:
            return

        self.packet_type = self.frame[1] - 0x66
        if self.packet_type == 0:
            payload_size = self.size - 15 - 4 - 32
        elif self.packet_type == 1:
            payload_size = self.size - 15 - 4
        else:
            return

        crc_data_size = 15 + payload_size - 1
        crc_start = 1 + crc_data_size
        expected_crc = int.from_bytes(self.frame[crc_start : crc_start + 4], "big")
        crc_valid = (
            zlib.crc32(self.frame[1:crc_start]) & 0xFFFFFFFF
        ) == expected_crc

        callsign_code = int.from_bytes(self.frame[2:6], "big")
        if callsign_code <= 0xF423FFFF:
            while callsign_code:
                character_code = callsign_code % 40
                if character_code == 0:
                    character = "-"
                elif character_code < 11:
                    character = str(character_code - 1)
                elif character_code < 14:
                    character = "-"
                else:
                    character = chr(ord("A") + character_code - 14)
                self.callsign += character
                callsign_code //= 40

        self.image_id = self.frame[6]
        self.packet_id = int.from_bytes(self.frame[7:9], "big")
        self.width = self.frame[9] << 4
        self.height = self.frame[10] << 4
        self.flags = self.frame[11]
        self.mcu_offset = self.frame[12]
        self.mcu_index = int.from_bytes(self.frame[13:15], "big")

        mcu_count = self.frame[9] * self.frame[10]
        mcu_mode = self.frame[11] & 0x03
        if mcu_mode in (1, 2):
            mcu_count *= 2
        elif mcu_mode == 3:
            mcu_count *= 4
        self.valid = True
        # self.valid = (
        #     crc_valid
        #     and self.width > 0
        #     and self.height > 0
        #     and (self.mcu_index == 0xFFFF or self.mcu_index < mcu_count)
        #     and (
        #         self.mcu_index == 0xFFFF
        #         or self.mcu_offset < payload_size
        #     )
        
class ssdv_image:
    def __init__(self, image_name) -> None:
        self.image_name = image_name
        self.bin_filename = f"{image_name}.bin"
        self.image_filename = f"{image_name}.jpg"
        self.frames = list()
        self.clear()

    def clear(self) -> None:
        self.frames.clear()
        self.image_id = 0
        self.frame_size = 0
        self.callsign = ""
        self.num_frames = 0
        self.width = 0
        self.height = 0
        self.flags = 0
        self.mcu_count = 0
        self.mcu_mode = 0
        if os.path.exists(self.bin_filename):
            os.remove(self.bin_filename)
        if os.path.exists(self.image_filename):
            os.remove(self.image_filename)

    def add_frame(self, frame: ssdv_frame) -> None:
       # Add an SSDV frame. If its the first frame, set image parameters. Otherwise, check that the frame is valid and matches the image parameters. 
       # TODO: Add error handling for invalid frames or mismatched parameters. 
        if len(self.frames) == 0:  # this is the first frame, so set the image parameters
            self.image_id = frame.image_id
            self.frame_size = frame.size
            self.callsign = frame.callsign
            self.width = frame.width
            self.height = frame.height
            self.flags = frame.flags
            self.mcu_count = frame.width * frame.height
            self.mcu_mode = frame.flags & 0x03
            if self.mcu_mode in (1, 2):
                self.mcu_count *= 2
            elif self.mcu_mode == 3:
                self.mcu_count *= 4
        self.frames.append(frame)
        self.num_frames += 1

    def sort_frames(self) -> None:
        # Sort the frames by packet_id
        self.frames.sort(key=lambda f: f.packet_id)

    def save_bin(self) -> None:
        # Save the frames to a binary file
        self.sort_frames()
        with open(self.bin_filename, "wb") as f:
            for frame in self.frames:
                if frame.valid:
                    f.write(frame.frame)

    def decode_image(self) -> None:
        # Decode the binary file to a JPEG image using the SSDV decoder
        result = subprocess.run(["./ssdv/ssdv", "-d", self.bin_filename, self.image_filename], capture_output=True)
        if result.returncode != 0:
            print(f"Error decoding SSDV: {result.stderr.decode()}") 


def format_frame_details(frame: ssdv_frame) -> str:
    return "\n".join(
        (
            f"Source: {frame.source}",
            f"Size:   {frame.size} bytes",
            f"Valid:  {frame.valid}",
            f"Packet type: {frame.packet_type}",
            f"Callsign: {frame.callsign}",
            f"Image ID: {frame.image_id}",
            f"Packet ID: {frame.packet_id}",
            f"Width:    {frame.width}",
            f"Height:   {frame.height}",
            f"Flags:     0x{frame.flags:02X}",
            f"MCU offset: {frame.mcu_offset}",
            f"MCU index:  {frame.mcu_index}",
        )
    )


def update_plot_image(
    jpeg_filename: str | Path,
    image_artist: AxesImage,
    canvas: FigureCanvasTkAgg,
) -> None:
    image = mpimg.imread(jpeg_filename)
    height, width = image.shape[:2]

    image_artist.set_data(image)
    image_artist.set_extent((-0.5, width - 0.5, height - 0.5, -0.5))
    image_artist.axes.set_xlim(-0.5, width - 0.5)
    image_artist.axes.set_ylim(height - 0.5, -0.5)
    canvas.draw()


def clear_plot_image(image_artist: AxesImage, canvas: FigureCanvasTkAgg) -> None:
    image_artist.set_data([[0.2]])
    image_artist.set_extent((-0.5, 0.5, 0.5, -0.5))
    image_artist.axes.set_xlim(-0.5, 0.5)
    image_artist.axes.set_ylim(0.5, -0.5)
    canvas.draw()


def get_wlan_ip() -> str:
    hardware_ports = subprocess.run(
        ["networksetup", "-listallhardwareports"],
        capture_output=True,
        text=True,
        check=True,
    ).stdout

    for port in hardware_ports.split("\n\n"):
        lines = port.splitlines()
        if "Hardware Port: Wi-Fi" not in lines:
            continue

        device = next(
            (line.removeprefix("Device: ") for line in lines if line.startswith("Device: ")),
            None,
        )
        if device is None:
            return "unavailable"

        result = subprocess.run(
            ["ipconfig", "getifaddr", device],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "unavailable"

    return "unavailable"


def get_next_frame_UDP(sock: socket.socket) -> ssdv_frame | None:
    try:
        data, addr = sock.recvfrom(buf_size)
        if data:
            return ssdv_frame(data, source=f"{addr}")
    except socket.timeout:
        return None
    except Exception as e:
        print(f"Error receiving UDP frame: {e}")
        return None
    
def get_next_frame():
    global frame_pos
    filename = "ssdv_frames.bin"
    frame_size = 256  # Size of each SSDV frame in bytes
    with open(filename, "rb") as f: 
        f.seek(frame_pos)  # Move to the next frame position
        bytes = f.read(frame_size)
        frame_pos = f.tell()  # Update the position for the next read
    return ssdv_frame(bytes, source=filename) if bytes else None      
   
def main() -> None:
 ## The Main function for SSDV_Viewer

# set up the UDP socket
    UDP_IP = "0.0.0.0"
    UDP_PORT = 5030
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((UDP_IP, UDP_PORT))
    # set a timeout for the socket to allow periodic GUI updates
    sock.settimeout(socket_timeout)

# Set up the temp SSDV image
    ssdv_image_temp = ssdv_image("temp_image")

# set up the matplotlib figure and axes
    figure = Figure(figsize=(8, 5), tight_layout=True)
    axes = figure.add_subplot(111)
    image_artist = axes.imshow([[0.2]], cmap="gray", vmin=0, vmax=1)
    axes.axis("off")

# set up the PySimpleGUI layout
    layout = [
        [
            sg.Frame(
                "Received SSDV Image",
                [[sg.Canvas(key="-PLOT-", expand_x=True, expand_y=True)]],
                expand_x=True,
                expand_y=True,
            ),
            sg.Frame(
                "Latest SSDV frame",
                [
                    [
                        sg.Text(
                            "Total frames: 0",
                            key="-FRAME-COUNT-",
                            font=("Helvetica", 16, "bold"),
                            text_color="green",
                            background_color="black",
                            expand_x=True,
                        )
                    ],
                    [
                        sg.Multiline(
                            "Waiting for a frame...",
                            key="-FRAME-DETAILS-",
                            size=(34, 28),
                            font=("Helvetica", 14, "bold"),
                            text_color="green",
                            background_color="black",
                            disabled=True,
                            expand_x=True,
                            expand_y=True,
                        )
                    ],
                ],
                title_color="green",
                background_color="black",
                expand_y=True,
            ),
        ],
        [
            sg.Column(
                [
                    [
                        sg.Button("Print", size=(12, 2), font=("Helvetica", 14, "bold")),
                        sg.Button("Clear", size=(12, 2), font=("Helvetica", 14, "bold")),
                        sg.Button("Exit", size=(12, 2), font=("Helvetica", 14, "bold")),
                    ]
                ],
                justification="center",
                element_justification="center",
                expand_x=True,
            ),
        ],
        [sg.Text(f"WLAN IP address: {get_wlan_ip()}", justification="center", expand_x=True)],
    ]
    window = sg.Window(
        "SSDV Image Viewer",
        layout,
        size=(1200, 720),
        resizable=True,
        finalize=True,
    )

    canvas = FigureCanvasTkAgg(figure, master=window["-PLOT-"].TKCanvas)
    canvas.draw()
    canvas.get_tk_widget().pack(side="top", fill="both", expand=True)

    while True:  ### MAIN LOOP ###
        event, _ = window.read(timeout=int(GUI_timeout * 1000))
        if event in (sg.WIN_CLOSED, "Exit"):
            break
        if event == "Print":
            figure.savefig("ssdv_image.pdf", dpi=300)
            # print pdf to default printer
            subprocess.run(["lp", "ssdv_image.pdf"])

        elif event == "Clear":
            ssdv_image_temp.clear()
            clear_plot_image(image_artist, canvas)
            window["-FRAME-COUNT-"].update("Total frames: 0")
            window["-FRAME-DETAILS-"].update("")  
            continue

        frame = get_next_frame_UDP(sock)
        if frame is not None:
            ssdv_image_temp.add_frame(frame)
            window["-FRAME-COUNT-"].update(f"Total frames: {ssdv_image_temp.num_frames}")
            window["-FRAME-DETAILS-"].update(format_frame_details(frame))
            ssdv_image_temp.save_bin()
            ssdv_image_temp.decode_image()
            pic_path = ssdv_image_temp.image_filename if os.path.exists(ssdv_image_temp.image_filename) else None
            if pic_path is not None:
                update_plot_image(pic_path, image_artist, canvas)

    window.close()


if __name__ == "__main__":
    main()
