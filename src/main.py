import struct
import sys
from dataclasses import dataclass
from typing import Optional
from threading import Event
import enum

from PySide6.QtWidgets import QApplication, QMainWindow
from PySide6.QtCore import Signal, Slot, QObject, QThread
from serial import Serial, SerialException
import serial.tools.list_ports

from ui.design import Ui_MainWindow
from util import crc16_xmodem

DEFAULT_BAUDRATE = 9600


class SerialManager(QObject):
    """
    Provides non-blocking access to serial port for parsing telemetry packets.
    """

    class State(enum.Enum):
        """
        State of COBS decoder.
        """
        SCAN = 0  # next byte will be read literal
        ESC = 1   # next byte is COBS-escaped character
        START = 2  # next byte is start of the packet

    @dataclass
    class Packet:
        """
        Packet class for serial data.
        Fields are stored in order they go in the packet.
        """
        input: float
        setpoint: float
        error: float
        gain: float
        p_term: float
        i_term: float
        d_term: float

    state: State
    serial: Serial
    port: Optional[str]
    baudrate: Optional[int]
    cobs_code: int
    packet: bytearray
    thread: Optional[QThread]
    stop_event = Event()

    packet_received = Signal(Packet)

    PACKET_LENGTH = 28
    PACKET_TERMINATOR = 0x00

    def __init__(self):
        super().__init__()
        self.serial = Serial(timeout=0)  # non-blocking access
        self.port = None
        self.baudrate = None
        self.thread = QThread()
        self.moveToThread(self.thread)
        self.thread.started.connect(self.worker)

    @staticmethod
    def get_ports() -> list[str]:
        return [port.device for port in serial.tools.list_ports.comports()]

    @Slot()
    def open(self):
        self.thread.wait()
        if self.port is None:
            raise SerialException("No port selected")

        self.serial.port = self.port
        self.serial.baudrate = self.baudrate
        self.serial.open()
        if not self.serial.isOpen():
            raise SerialException(f"Could not open serial port {self.port}")
        self.packet = bytearray()
        self.state = self.State.START
        self.stop_event.clear()
        self.thread.start()

    @Slot()
    def close(self):
        self.stop_event.set()

    def connected(self) -> bool:
        return self.serial.isOpen()

    def worker(self):
        while not self.stop_event.is_set():
            data = self.serial.read_all()
            for c in data:
                packet = self.update(c)
                if packet is not None:
                    self.packet_received.emit(packet)
        self.serial.close()
        QThread.currentThread().quit()

    def update(self, c: int) -> Optional[Packet]:
        """
        Update packet parser with character `c` and try to parse a Packet object from internal buffer.
        If no complete packet is available, returns None. Raises IOError if the received packet is not valid.
        Uses COBS for packet framing. (see https://en.wikipedia.org/wiki/Consistent_Overhead_Byte_Stuffing)
        Packet format:
        +--------------------+---------//-----+--------------------------------+------+
        | COBS overhead byte | payload // ... | CRC-CCITT of payload (2 bytes) | 0x00 |
        +--------------------+---------//-----+------------- ------------------+------+
        NOTE: For packet creation, at first, checksum of payload is computed,
              after that payload + checksum gets encoded with COBS
        0x00 is a packet terminator.
        """
        packet = None

        match (self.state, c):
            case (self.State.START, _):
                # start of packet byte does not represent any payload character
                self.cobs_code = c
                self.state = self.State.SCAN

            case (self.State.SCAN, self.PACKET_TERMINATOR):
                # unexpected packet termination, drop this packet
                print(f"[!] Unexpected packet termination, received part: {self.packet.hex(' ')}")
                self.state = self.State.START  # start over
                self.packet = bytearray()

            case (self.State.ESC, self.PACKET_TERMINATOR):
                # packet is complete, process it
                packet = self.parse_packet(self.packet)
                self.state = self.State.START
                self.packet = bytearray()

            case (self.State.SCAN, _):
                self.packet.append(c)

            case (self.State.ESC, _):
                self.packet.append(self.PACKET_TERMINATOR)
                self.cobs_code = c
                self.state = self.State.SCAN

        if self.cobs_code == 1:
            # next byte is COBS-escaped
            self.state = self.State.ESC

        self.cobs_code -= 1
        return packet

    @staticmethod
    def parse_packet(packet: bytearray) -> Optional[Packet]:
        """
        Verify checksum of packet and parse it into a Packet object.
        If checksum is invalid, returns None.
        Checksum is the last two bytes of the packet, CRC-XMODEM is used.
        """
        if len(packet) != SerialManager.PACKET_LENGTH + 2:
            return None

        packet_payload = packet[:-2]
        packet_checksum = struct.unpack("<H", packet[-2:])[0]
        real_checksum = crc16_xmodem(packet_payload)

        print(f"Received packet: {packet_payload.hex(' ')}, checksum: {hex(packet_checksum)}")
        print(f"Calculated checksum: {hex(real_checksum)}")

        if packet_checksum != real_checksum:
            return None

        return SerialManager.Packet(*struct.unpack("<7f", packet_payload))


class MainWindow(QMainWindow):
    serial: SerialManager

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.serial = SerialManager()

        self.ui.scanPortsButton.clicked.connect(self.update_ports_list)
        self.ui.connectButton.clicked.connect(self.toggle_serial)
        self.ui.portBaudrate.editingFinished.connect(self.update_baudrate)
        self.ui.portBaudrate.setText(str(DEFAULT_BAUDRATE))
        self.ui.noPortsFoundWarning.hide()
        self.ui.portErrorLabel.hide()
        self.ui.portError.hide()
        self.ui.portStatus.setText("Not connected")

        self.update_baudrate()
        self.serial.packet_received.connect(self.on_packet)

    def cleanup(self):
        if self.serial.connected():
            self.serial.close()

    @Slot()
    def on_packet(self, packet: SerialManager):
        print(packet)

    def update_ports_list(self):
        # clear previous error message
        self.ui.portErrorLabel.hide()
        self.ui.portError.hide()

        ports: list[str] = self.serial.get_ports()

        self.ui.selectPortBox.clear()
        if ports:
            self.ui.noPortsFoundWarning.hide()
            self.ui.selectPortBox.addItems(ports)
        else:
            self.ui.noPortsFoundWarning.show()

    def toggle_serial(self):
        if self.serial.connected():
            self.serial.close()
            self.ui.portStatus.setText("Not connected")
            self.ui.connectButton.setText("Connect")
        else:
            self.serial.port = self.ui.selectPortBox.currentText() or None

            try:
                self.serial.open()
                self.ui.portStatus.setText("Connected")
                self.ui.connectButton.setText("Disconnect")
                self.ui.portErrorLabel.hide()
                self.ui.portError.hide()
            except SerialException as e:
                self.ui.portError.setText(str(e))
                self.ui.portErrorLabel.show()
                self.ui.portError.show()

    def update_baudrate(self):
        try:
            val = int(self.ui.portBaudrate.text())
        except ValueError:
            val = None
        self.serial.baudrate = val


app = QApplication(sys.argv)
window = MainWindow()
window.show()

ret_val = app.exec()
window.cleanup()

sys.exit(ret_val)
