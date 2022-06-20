import struct
import sys
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtWidgets import QApplication, QMainWindow
from serial import Serial, SerialException
from serial.tools.list_ports import comports

from ui.design import Ui_MainWindow


class SerialManager:

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

    serial: Serial
    port: Optional[str]
    baudrate: int
    PACKET_LENGTH = 29
    PACKET_TERMINATOR = b"\x0A"

    def __init__(self):
        self.serial = Serial()
        self.port = None
        self.baudrate = 0

    @staticmethod
    def get_ports() -> List[str]:
        return [port.device for port in comports()]

    def connect(self):
        if self.port is None:
            raise SerialException("No port selected")

        self.serial.port = self.port
        self.serial.baudrate = self.baudrate
        self.serial.open()
        if not self.serial.isOpen():
            raise SerialException(f"Could not open serial port {self.port}")

    def disconnect(self):
        self.serial.close()

    def connected(self) -> bool:
        return self.serial.isOpen()

    def get_packet(self) -> Optional[Packet]:
        """
        Reads a packet from the serial port and parses it into a Packet object.
        Packet format:
        +--------------------+--------------------+--------------------+--------------------+
        |  Input (float32)   | Setpoint (float32) |   Error (float32)  |   Gain (float32)   |
        +--------------------+--------------------+--------------------+------+-------------+
        |  P Term (float32)  | I Term (float32)   | D Term (float32)   | 0x0A |
        +--------------------+--------------------+--------------------+------+
        0x0A is a packet terminator.
        Packet length: (4 * 7) + 1 = 29 bytes
        """
        data: bytes = self.serial.read_until(self.PACKET_TERMINATOR)
        # if line is desynced, discard the packet
        # now line is in sync, the next byte is the beginning of the next packet
        if len(data) != SerialManager.PACKET_LENGTH:
            return None
        data.rstrip(self.PACKET_TERMINATOR)
        return SerialManager.Packet(*struct.unpack("<7f", data))


class MainWindow(QMainWindow):
    serial: SerialManager

    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)

        self.ui.scanPortsButton.clicked.connect(self.update_ports_list)
        self.ui.connectButton.clicked.connect(self.toggle_serial)
        self.ui.portBaudrate.editingFinished.connect(self.update_baudrate)
        self.ui.noPortsFoundWarning.hide()
        self.ui.portErrorLabel.hide()
        self.ui.portError.hide()
        self.ui.portStatus.setText("Not connected")

        self.serial = SerialManager()

    def update_ports_list(self):
        # clear previous error message
        self.ui.portErrorLabel.hide()
        self.ui.portError.hide()

        ports: List[str] = self.serial.get_ports()

        self.ui.selectPortBox.clear()
        if ports:
            self.ui.noPortsFoundWarning.hide()
            self.ui.selectPortBox.addItems(ports)
        else:
            self.ui.noPortsFoundWarning.show()

    def toggle_serial(self):
        if self.serial.connected():
            self.serial.disconnect()
            self.ui.portStatus.setText("Not connected")
            self.ui.connectButton.setText("Connect")
        else:
            self.serial.port = self.ui.selectPortBox.currentText() or None

            try:
                self.serial.connect()
                self.ui.portStatus.setText("Connected")
                self.ui.connectButton.setText("Disconnect")
                self.ui.portErrorLabel.hide()
                self.ui.portError.hide()
            except SerialException as e:
                self.ui.portError.setText(str(e))
                self.ui.portErrorLabel.show()
                self.ui.portError.show()

    def update_baudrate(self):
        self.serial.baudrate = int(self.ui.portBaudrate.text())


app = QApplication(sys.argv)
window = MainWindow()
window.show()

sys.exit(app.exec())
