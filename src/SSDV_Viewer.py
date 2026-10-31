# SSDV_Viewer.py - PySide6 application to display SSDV images streamed over UDP
# The application listens for SSDV frames on a specified UDP port, decodes the frames,
#  and displays the resulting image in a GUI window. It also provides options to 
# print the image or clear the display. 
#
# Last update: 2026-10-29 DJC
#
# Revision history: 2026-10-26 DJC - Initial release
#                   2026-10-29 DJC - Switched to PySide6 and updated GUI layout

from pathlib import Path
import sys
import matplotlib.image as mpimg
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure
from matplotlib.image import AxesImage
import os
import subprocess
import zlib
import socket
from collections import Counter
from PySide6.QtCore import QRectF, Qt, QTimer
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetricsF,
    QImage,
    QPageLayout,
    QPageSize,
    QPainter,
    QPixmap,
)
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrinterInfo
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QDialog,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

# Global variables
GUI_timeout = 0.01  # Delay between frames in seconds
UDP_PORT = 5030
WINDOW_BACKGROUND_COLOR = "#1c1c1c"
BANNER_TEXT_COLOR = "#FF4500"
BUTTON_STYLE = (
    "QPushButton { background-color: #2563eb; color: white; "
    "border: none; border-radius: 8px; }"
    "QPushButton:hover { background-color: #3b82f6; }"
    "QPushButton:pressed { background-color: #1d4ed8; }"
)
frame_count = 0  # Counter for the number of frames processed
frame_pos = 0  # Position of the next frame to read
buf_size = 1024  # Size of the buffer for receiving UDP packets
SSDV_APP_WIN = "./src/ssdv-win.exe"
SSDV_APP_UNIX = "./src/ssdv"
SSDV_APP = SSDV_APP_WIN if os.name == "nt" else SSDV_APP_UNIX

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

       # if the image_id of the new frame doesn't match the current image, clear the image and use the new frame to start over
        if self.frames and frame.image_id != self.image_id:
            self.clear()

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
        result = subprocess.run([SSDV_APP, "-d", "-l", str(self.frame_size), self.bin_filename, self.image_filename], capture_output=True)
        if result.returncode != 0:
            error_details = [
                f"{stream_name}: {output.decode(errors='replace').strip()}"
                for stream_name, output in (
                    ("stderr", result.stderr),
                    ("stdout", result.stdout),
                )
                if output.strip()
            ]
            if not error_details:
                error_details.append("no diagnostic output")
            print(
                f"Error decoding SSDV (exit code {result.returncode}): "
                f"{' | '.join(error_details)}"
            )


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
    canvas: FigureCanvasQTAgg,
) -> None:
    image = mpimg.imread(jpeg_filename)
    height, width = image.shape[:2]

    image_artist.set_data(image)
    image_artist.set_extent((-0.5, width - 0.5, height - 0.5, -0.5))
    image_artist.axes.set_xlim(-0.5, width - 0.5)
    image_artist.axes.set_ylim(height - 0.5, -0.5)
    canvas.draw()


def clear_plot_image(image_artist: AxesImage, canvas: FigureCanvasQTAgg) -> None:
    image_artist.set_data([[0.2]])
    image_artist.set_extent((-0.5, 0.5, 0.5, -0.5))
    image_artist.axes.set_xlim(-0.5, 0.5)
    image_artist.axes.set_ylim(0.5, -0.5)
    canvas.draw()


def average_image_luminance(
    image: QImage,
    sample_rect: QRectF,
    displayed_image_rect: QRectF,
) -> float:
    luminance_total = 0.0
    sample_count = 0
    for row in range(3):
        y = sample_rect.top() + sample_rect.height() * (row + 0.5) / 3
        image_y = min(
            image.height() - 1,
            max(
                0,
                int(
                    (y - displayed_image_rect.top())
                    * image.height()
                    / displayed_image_rect.height()
                ),
            ),
        )
        for column in range(9):
            x = sample_rect.left() + sample_rect.width() * (column + 0.5) / 9
            image_x = min(
                image.width() - 1,
                max(
                    0,
                    int(
                        (x - displayed_image_rect.left())
                        * image.width()
                        / displayed_image_rect.width()
                    ),
                ),
            )
            color = image.pixelColor(image_x, image_y)
            luminance_total += (
                0.2126 * color.red()
                + 0.7152 * color.green()
                + 0.0722 * color.blue()
            )
            sample_count += 1
    return luminance_total / sample_count


def contrasting_text_color(
    image: QImage,
    sample_rect: QRectF,
    displayed_image_rect: QRectF,
) -> QColor:
    return QColor(
        Qt.GlobalColor.black
        if average_image_luminance(image, sample_rect, displayed_image_rect) >= 128
        else Qt.GlobalColor.white
    )


def draw_print_logo(
    painter: QPainter,
    image: QImage,
    displayed_image_rect: QRectF,
    logo: QImage,
    dpi: int,
) -> QColor:
    margin = dpi * 0.08
    text_height = dpi * 0.18
    text_gap = dpi * 0.01
    logo_height = max(
        1,
        min(
            dpi * 0.75 * 0.85,
            displayed_image_rect.height() - margin - text_height - text_gap,
        ),
    )
    logo_size = logo.size().scaled(
        min(
            int(displayed_image_rect.width() * 0.45),
            int(logo_height * logo.width() / logo.height()),
        ),
        int(logo_height),
        Qt.AspectRatioMode.KeepAspectRatio,
    )
    text_rect = QRectF(
        displayed_image_rect.right() - margin - logo_size.width(),
        displayed_image_rect.bottom() - margin - text_height,
        logo_size.width(),
        text_height,
    )
    logo_rect = QRectF(
        text_rect.left(),
        text_rect.top() - text_gap - logo_size.height(),
        logo_size.width(),
        logo_size.height(),
    )
    painter.drawImage(logo_rect, logo)

    text_color = contrasting_text_color(image, text_rect, displayed_image_rect)
    painter.setPen(text_color)
    painter.setFont(QFont("Helvetica", 8, QFont.Weight.Bold))
    painter.drawText(
        text_rect,
        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
        "www.silversat.org",
    )
    return text_color


def draw_print_banner(
    painter: QPainter,
    displayed_image_rect: QRectF,
    text: str,
    dpi: int,
) -> None:
    margin = dpi * 0.08
    banner_rect = QRectF(
        displayed_image_rect.left() + margin,
        displayed_image_rect.top() + margin,
        displayed_image_rect.width() - 2 * margin,
        dpi * 0.5,
    )
    font = QFont("Footlight MT Light")
    font_size = max(1, int(dpi * 0.5))
    font.setPixelSize(font_size)
    metrics = QFontMetricsF(font)
    while font_size > 1 and (
        metrics.horizontalAdvance(text) > banner_rect.width()
        or metrics.height() > banner_rect.height()
    ):
        font_size -= 1
        font.setPixelSize(font_size)
        metrics = QFontMetricsF(font)

    painter.setFont(font)
    painter.setPen(QColor(BANNER_TEXT_COLOR))
    painter.drawText(
        banner_rect,
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        text,
    )


def get_wlan_ip() -> str:

    if os.name == "nt":
        powershell_command = (
            "$adapter = Get-NetAdapter -Physical | "
            "Where-Object { $_.NdisPhysicalMedium -eq 9 -and $_.Status -eq 'Up' } | "
            "Select-Object -First 1; "
            "if ($adapter) { "
            "Get-NetIPAddress -InterfaceIndex $adapter.ifIndex -AddressFamily IPv4 "
            "-ErrorAction SilentlyContinue | "
            "Where-Object { $_.IPAddress -and $_.IPAddress -notlike '169.254.*' } | "
            "Select-Object -First 1 -ExpandProperty IPAddress "
            "}"
        )
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", powershell_command],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
        return "unavailable"

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
    except (socket.timeout, BlockingIOError):
        return None
    except Exception as e:
        print(f"Error receiving UDP frame: {e}")
        return None
    
def get_ssdv_frame_size(filename: str | Path) -> int:
    with open(filename, "rb") as ssdv_file:
        data = ssdv_file.read()

    frame_starts = [
        offset
        for offset in range(len(data) - 1)
        if data[offset] == 0x55 and data[offset + 1] in (0x66, 0x67)
    ]
    if not frame_starts:
        return 256
    if len(frame_starts) == 1:
        return len(data)

    frame_lengths = Counter(
        next_start - start
        for start, next_start in zip(frame_starts, frame_starts[1:])
    )
    return frame_lengths.most_common(1)[0][0]


def get_next_frame(
    filename: str | Path,
    packet_size: int,
) -> ssdv_frame | None:
    global frame_pos
    with open(filename, "rb") as ssdv_file:
        ssdv_file.seek(frame_pos)
        data = ssdv_file.read(packet_size)
        frame_pos = ssdv_file.tell()
    return ssdv_frame(data, source=str(filename)) if data else None
   
class SSDVViewerWindow(QMainWindow):
    def __init__(self, sock: socket.socket) -> None:
        super().__init__()
        self.sock = sock
        self.ssdv_image_temp = ssdv_image("temp_image")
        self.source = "UDP"
        self.source_file: Path | None = None
        self.source_packet_size = 256
        self.demo_process: subprocess.Popen[bytes] | None = None
        self.include_print_logo = False
        self.include_print_banner = False
        self.print_banner_text = ""

        self.setWindowTitle("SSDV Image Viewer")
        self.setStyleSheet(
            f"QMainWindow {{ background-color: {WINDOW_BACKGROUND_COLOR}; }}"
        )
        central_widget = QWidget()
        central_widget.setStyleSheet("QWidget { color: #f5f5dc; }")
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        header_layout = QHBoxLayout()
        logo_path = Path(__file__).resolve().parent.parent / "data" / "silversat-logo-small.png"
        logo_label = QLabel()
        logo_label.setObjectName("silversatLogo")
        logo_label.setPixmap(
            QPixmap(str(logo_path)).scaled(
                140,
                70,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        header_layout.addWidget(logo_label, alignment=Qt.AlignmentFlag.AlignLeft)
        header_layout.addStretch(1)
        menu_button = QPushButton("☰")
        menu_button.setAccessibleName("Menu")
        menu_button.setStyleSheet(BUTTON_STYLE)
        menu_button.setFixedSize(52, 52)
        menu_button.setFont(QFont("Helvetica", 22, QFont.Weight.Bold))
        menu_button.clicked.connect(self.open_menu)
        header_layout.addWidget(menu_button, alignment=Qt.AlignmentFlag.AlignRight)
        main_layout.addLayout(header_layout)

        image_group = QGroupBox("Received SSDV Image")
        image_group.setFont(QFont("Helvetica", 14))
        image_group.setStyleSheet(
            f"QGroupBox {{ color: #f5f5dc; "
            f"background-color: {WINDOW_BACKGROUND_COLOR}; }}"
        )
        image_layout = QVBoxLayout(image_group)
        self.figure = Figure(
            figsize=(8, 5),
            tight_layout=True,
            facecolor="black",
        )
        axes = self.figure.add_subplot(111)
        axes.set_facecolor(WINDOW_BACKGROUND_COLOR)
        self.image_artist = axes.imshow([[0.2]], cmap="gray", vmin=0, vmax=1)
        axes.axis("off")
        self.canvas = FigureCanvasQTAgg(self.figure)
        image_layout.addWidget(self.canvas)

        image_buttons_layout = QHBoxLayout()
        image_buttons_layout.addStretch(1)
        for label, callback in (("Print", self.print_image), ("Clear", self.clear_image)):
            button = QPushButton(label)
            button.setStyleSheet(BUTTON_STYLE)
            button.setFixedSize(120, 60)
            button.setFont(QFont("Helvetica", 14, QFont.Weight.Bold))
            button.clicked.connect(callback)
            image_buttons_layout.addWidget(button)
            if label == "Print":
                image_buttons_layout.addSpacing(16)
        image_buttons_layout.addStretch(1)
        image_layout.addLayout(image_buttons_layout)

        details_group = QGroupBox("SSDV Frame Header")
        details_group.setFont(QFont("Helvetica", 14))
        details_group.setStyleSheet(
            "QGroupBox { color: green; background-color: black; }"
        )
        details_layout = QVBoxLayout(details_group)
        self.frame_count_label = QLabel("Total frames: 0")
        self.frame_count_label.setFont(QFont("Helvetica", 14, QFont.Weight.Bold))
        self.frame_count_label.setStyleSheet("color: green; background-color: black;")
        details_layout.addWidget(self.frame_count_label)

        self.frame_details = QPlainTextEdit("Waiting for a frame...")
        self.frame_details.setReadOnly(True)
        self.frame_details.setFont(QFont("Helvetica", 14, QFont.Weight.Bold))
        self.frame_details.setStyleSheet(
            "color: green; background-color: black;"
        )
        details_layout.addWidget(self.frame_details)

        content_layout = QHBoxLayout()
        content_layout.addWidget(image_group, stretch=3)
        content_layout.addWidget(details_group, stretch=1)
        main_layout.addLayout(content_layout, stretch=1)

        ip_label = QLabel(
            f"WLAN IP address: {get_wlan_ip()}  |  UDP port: {UDP_PORT}"
        )
        ip_label.setStyleSheet("color: #f5f5dc;")
        ip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        main_layout.addWidget(ip_label)

        self.frame_timer = QTimer(self)
        self.frame_timer.timeout.connect(self.process_next_frame)
        self.frame_timer.start(int(GUI_timeout * 1000))

    def open_menu(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Menu")
        dialog.setFixedSize(220, 232)
        dialog.setStyleSheet(
            f"QDialog {{ background-color: {WINDOW_BACKGROUND_COLOR}; "
            "color: #f5f5dc; }"
            f"{BUTTON_STYLE}"
        )
        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        action_requested: str | None = None

        def request_action(action: str) -> None:
            nonlocal action_requested
            action_requested = action
            dialog.accept()

        source_button = QPushButton("Source")
        source_button.setFixedSize(140, 48)
        source_button.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        source_button.clicked.connect(lambda: request_action("source"))
        layout.addWidget(source_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        print_settings_button = QPushButton("Print Settings")
        print_settings_button.setFixedSize(140, 48)
        print_settings_button.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        print_settings_button.clicked.connect(
            lambda: request_action("print_settings")
        )
        layout.addWidget(
            print_settings_button,
            alignment=Qt.AlignmentFlag.AlignHCenter,
        )

        exit_button = QPushButton("Exit")
        exit_button.setFixedSize(140, 48)
        exit_button.setFont(QFont("Helvetica", 12, QFont.Weight.Bold))
        exit_button.clicked.connect(lambda: request_action("exit"))
        layout.addWidget(exit_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        dialog.exec()
        if action_requested == "source":
            self.select_source()
        elif action_requested == "print_settings":
            self.open_print_settings()
        elif action_requested == "exit":
            self.close()

    def open_print_settings(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Print Settings")
        dialog.setFixedWidth(320)
        dialog.setStyleSheet(
            f"QDialog {{ background-color: {WINDOW_BACKGROUND_COLOR}; "
            "color: white; }"
            "QLabel, QCheckBox { color: white; }"
            "QLineEdit { color: white; background-color: #303030; "
            "border: 1px solid #888; padding: 4px; }"
            f"{BUTTON_STYLE}"
        )
        layout = QVBoxLayout(dialog)
        layout.setSpacing(12)

        include_logo = QCheckBox("Include logo")
        include_logo.setChecked(self.include_print_logo)
        layout.addWidget(include_logo)

        include_banner = QCheckBox("Include banner")
        include_banner.setChecked(self.include_print_banner)
        layout.addWidget(include_banner)

        banner_layout = QHBoxLayout()
        banner_label = QLabel("Banner")
        banner_entry = QLineEdit(self.print_banner_text)
        banner_entry.setPlaceholderText("Enter a short message")
        banner_layout.addWidget(banner_label)
        banner_layout.addWidget(banner_entry, stretch=1)
        layout.addLayout(banner_layout)

        buttons_layout = QHBoxLayout()
        buttons_layout.addStretch(1)
        save_button = QPushButton("Save")
        save_button.setFixedSize(90, 40)
        save_button.clicked.connect(dialog.accept)
        buttons_layout.addWidget(save_button)
        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(90, 40)
        cancel_button.clicked.connect(dialog.reject)
        buttons_layout.addWidget(cancel_button)
        layout.addLayout(buttons_layout)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.include_print_logo = include_logo.isChecked()
            self.include_print_banner = include_banner.isChecked()
            self.print_banner_text = banner_entry.text()

    def select_source(self) -> None:
        choices = ("UDP", "File", "Demo", "Radio")
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Frame Source")
        dialog.setMinimumWidth(240)
        dialog.setStyleSheet(
            f"QDialog {{ background-color: {WINDOW_BACKGROUND_COLOR}; "
            "color: #f5f5dc; }"
            f"{BUTTON_STYLE}"
            "QPushButton:checked { background-color: #1d4ed8; "
            "border: 2px solid white; border-radius: 8px; color: white; }"
        )
        layout = QVBoxLayout(dialog)
        layout.setSpacing(16)
        button_group = QButtonGroup(dialog)
        button_group.setExclusive(True)
        selected_file: Path | None = None

        def select_choice(choice: str) -> None:
            global frame_pos
            nonlocal selected_file
            if choice == "File":
                data_directory = Path(__file__).resolve().parent.parent / "data"
                filename, _ = QFileDialog.getOpenFileName(
                    dialog,
                    "Select SSDV File",
                    str(data_directory),
                    "SSDV files (*.bin)",
                )
                if not filename:
                    return
                selected_file = Path(filename)

            packet_size = (
                get_ssdv_frame_size(selected_file) if selected_file is not None else None
            )
            if choice == "Demo":
                if not self.start_demo_transmitter():
                    return
            elif not self.stop_demo_transmitter():
                return

            source_changed = self.source != choice or selected_file is not None
            if selected_file is not None:
                self.source_file = selected_file
                self.source_packet_size = packet_size or 256
                frame_pos = 0
            self.source = choice
            if source_changed:
                self.clear_image()
            dialog.accept()

        def handle_source_button(checked: bool, choice: str) -> None:
            if checked:
                select_choice(choice)

        for choice in choices:
            button = QPushButton(choice)
            button.setFixedSize(120, 60)
            button.setCheckable(True)
            button.setChecked(choice == self.source)
            button_group.addButton(button)
            button.clicked.connect(
                lambda checked, source=choice: handle_source_button(checked, source)
            )
            layout.addWidget(button, alignment=Qt.AlignmentFlag.AlignHCenter)

        cancel_button = QPushButton("Cancel")
        cancel_button.setFixedSize(120, 60)
        cancel_button.clicked.connect(dialog.reject)
        layout.addWidget(cancel_button, alignment=Qt.AlignmentFlag.AlignHCenter)

        if dialog.exec() != QDialog.DialogCode.Accepted:
            return

    def start_demo_transmitter(self) -> bool:
        if self.demo_process is not None and self.demo_process.poll() is None:
            return True

        transmitter = Path(__file__).resolve().with_name("SSDV_UDP_Tx.py")
        try:
            self.demo_process = subprocess.Popen(
                [sys.executable, str(transmitter)],
                cwd=transmitter.parent.parent,
            )
        except OSError as error:
            QMessageBox.critical(
                self,
                "Demo Source Error",
                f"Could not start the SSDV transmitter:\n{error}",
            )
            self.demo_process = None
            return False
        return True

    def stop_demo_transmitter(self) -> bool:
        if self.demo_process is None:
            return True
        if self.demo_process.poll() is not None:
            self.demo_process = None
            return True

        try:
            self.demo_process.terminate()
            try:
                self.demo_process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                self.demo_process.kill()
                self.demo_process.wait()
        except OSError as error:
            QMessageBox.critical(
                self,
                "Demo Source Error",
                f"Could not stop the SSDV transmitter:\n{error}",
            )
            return False

        self.demo_process = None
        return True

    def process_next_frame(self) -> None:
        if self.source in ("UDP", "Demo"):
            frame = get_next_frame_UDP(self.sock)
        elif self.source == "File" and self.source_file is not None:
            frame = get_next_frame(self.source_file, self.source_packet_size)
        else:
            return

        if frame is None:
            return

        self.ssdv_image_temp.add_frame(frame)
        self.frame_count_label.setText(
            f"Total frames: {self.ssdv_image_temp.num_frames}"
        )
        self.frame_details.setPlainText(format_frame_details(frame))
        self.ssdv_image_temp.save_bin()
        self.ssdv_image_temp.decode_image()
        image_path = self.ssdv_image_temp.image_filename
        if os.path.exists(image_path):
            update_plot_image(image_path, self.image_artist, self.canvas)

    def clear_image(self) -> None:
        self.ssdv_image_temp.clear()
        clear_plot_image(self.image_artist, self.canvas)
        self.frame_count_label.setText("Total frames: 0")
        self.frame_details.clear()

    def print_image(self) -> None:
        image_path = Path(self.ssdv_image_temp.image_filename)
        image = QImage(str(image_path))
        if image.isNull():
            QMessageBox.warning(
                self,
                "Print Image",
                "There is no image available to print.",
            )
            return

        printers = QPrinterInfo.availablePrinters()
        if not printers:
            QMessageBox.critical(
                self,
                "Print Image",
                "No printers are available. Connect and install a printer, then try again.",
            )
            return

        printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        default_printer = QPrinterInfo.defaultPrinter()
        if not default_printer.isNull():
            printer.setPrinterName(default_printer.printerName())
        else:
            printer.setPrinterName(printers[0].printerName())

        paper_size = QPageSize(QPageSize.PageSizeId.Postcard)
        printer.setPageSize(paper_size)
        printer.setPageOrientation(
            QPageLayout.Orientation.Landscape
            if image.width() > image.height()
            else QPageLayout.Orientation.Portrait
        )

        dialog = QPrintDialog(printer, self)
        dialog.setWindowTitle("Select Printer")
        if dialog.exec() != QPrintDialog.DialogCode.Accepted:
            return

        if not printer.setPageSize(paper_size):
            QMessageBox.critical(
                self,
                "Print Image",
                "The selected printer does not support 4 x 6 photo paper.",
            )
            return
        printer.setPageOrientation(
            QPageLayout.Orientation.Landscape
            if image.width() > image.height()
            else QPageLayout.Orientation.Portrait
        )

        logo = QImage()
        if self.include_print_logo:
            logo_path = (
                Path(__file__).resolve().parent.parent
                / "data"
                / "silversat-logo-small.png"
            )
            logo = QImage(str(logo_path))
            if logo.isNull():
                QMessageBox.critical(
                    self,
                    "Print Image",
                    f"Could not load the SilverSat logo:\n{logo_path}",
                )
                return

        painter = QPainter()
        if not painter.begin(printer):
            QMessageBox.critical(
                self,
                "Print Image",
                f"Could not start printing to {printer.printerName()}.",
            )
            return

        page_rect = printer.pageRect(QPrinter.Unit.DevicePixel)
        image_size = image.size().scaled(
            page_rect.size().toSize(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )
        target_rect = page_rect.adjusted(
            (page_rect.width() - image_size.width()) / 2,
            (page_rect.height() - image_size.height()) / 2,
            -(page_rect.width() - image_size.width()) / 2,
            -(page_rect.height() - image_size.height()) / 2,
        )
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.drawImage(target_rect, image)
        if self.include_print_logo:
            draw_print_logo(
                painter,
                image,
                target_rect,
                logo,
                printer.resolution(),
            )
        if self.include_print_banner and self.print_banner_text:
            draw_print_banner(
                painter,
                target_rect,
                self.print_banner_text,
                printer.resolution(),
            )
        if not painter.end():
            QMessageBox.critical(
                self,
                "Print Image",
                f"Printing to {printer.printerName()} did not complete successfully.",
            )

    def closeEvent(self, event) -> None:
        if not self.stop_demo_transmitter():
            event.ignore()
            return
        self.frame_timer.stop()
        self.sock.close()
        super().closeEvent(event)


def main() -> None:
    app = QApplication(sys.argv)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)

    window = SSDVViewerWindow(sock)
    screen = app.primaryScreen()
    
    if screen is not None:
        screen_size = screen.availableGeometry().size()
        window.resize(int(screen_size.width() * 0.9), int(screen_size.height() * 0.9))
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
