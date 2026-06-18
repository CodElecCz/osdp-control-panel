"""
OSDP Control-Panel (CP) manager.

Uses the real pyosdp (libosdp) API:
  - osdp.Channel          abstract base; we provide a pyserial subclass
  - osdp.PDInfo           wraps address + channel + flags
  - osdp.ControlPanel     manages CP state machine (calls .start() / .stop())
  - osdp.Command.*        command type constants
  - osdp.LibFlag.*        per-PD behaviour flags
  - osdp.Capability.*     capability function codes

If pyosdp is not installed the manager runs in simulation mode.
"""
from __future__ import annotations

import logging
import queue
import threading
import time
import struct
from typing import Any

from PyQt6.QtCore import QObject, pyqtSignal

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# optional dependency
# ---------------------------------------------------------------------------
try:
    import osdp  # type: ignore
    import serial  # type: ignore  (pyserial – needed for real channel)

    OSDP_AVAILABLE = True
    logger.info("pyosdp loaded successfully")
except ImportError as _exc:
    osdp = None  # type: ignore
    serial = None  # type: ignore
    OSDP_AVAILABLE = False
    logger.warning("pyosdp not found – running in SIMULATION mode (%s)", _exc)


# ---------------------------------------------------------------------------
# pyserial-backed Channel implementation
# ---------------------------------------------------------------------------

if OSDP_AVAILABLE:
    class SerialChannel(osdp.Channel):
        """Concrete osdp.Channel backed by a pyserial Serial instance."""

        def __init__(self, port: str, baud_rate: int) -> None:
            super().__init__()
            self._ser = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0,          # non-blocking read
                write_timeout=1.0,
            )

        def read(self, max_bytes: int) -> bytes:
            try:
                data = self._ser.read(max_bytes)
                return data if data else b""
            except serial.SerialException:
                return b""

        def write(self, buf: bytes) -> int:
            try:
                return self._ser.write(buf)
            except serial.SerialException:
                return 0

        def flush(self) -> None:
            try:
                self._ser.flush()
            except serial.SerialException:
                pass

        def close(self) -> None:
            try:
                self._ser.close()
            except Exception:
                pass
else:
    SerialChannel = None  # type: ignore


# ---------------------------------------------------------------------------
# LED / Buzzer / Tone constants (re-exported so UI can import from here)
# ---------------------------------------------------------------------------

class LedColor:
    NONE = 0
    RED = 1
    GREEN = 2
    AMBER = 3
    BLUE = 4
    MAGENTA = 5
    CYAN = 6
    WHITE = 7

    NAMES = {
        0: "None", 1: "Red", 2: "Green", 3: "Amber",
        4: "Blue", 5: "Magenta", 6: "Cyan", 7: "White",
    }


class LedControlCode:
    NOP = 0
    CANCEL = 1
    SET = 2
    NAMES = {0: "NOP", 1: "Cancel", 2: "Set"}


class ToneCode:
    OFF = 1           # Off/No tone
    DEFAULT = 2       # Default beep
    ON = 3            # Alternate tone (continuous)
    NAMES = {1: "Off", 2: "Default beep", 3: "On"}


class EventType:
    """OSDP Event Type constants."""
    CARDREAD = 1      # Card read event
    KEYPRESS = 2      # Keypad press event
    MFGREP = 3        # Manufacturer specific reply event
    STATUS = 4        # Status event
    NOTIFICATION = 5  # LibOSDP notification event
    
    NAMES = {
        1: "CARDREAD",
        2: "KEYPRESS",
        3: "MFGREP",
        4: "STATUS",
        5: "NOTIFICATION",
    }


# ---------------------------------------------------------------------------
# Raw OSDP packet functions for bus scanning
# ---------------------------------------------------------------------------

def calculate_checksum(packet: bytes) -> int:
    """
    Computes a simple OSDP 8-bit 2's complement checksum.
    Required for legacy fallback devices running without CRC mode.
    """
    total = sum(packet)
    return (0x100 - (total & 0xFF)) & 0xFF

def calculate_osdp_crc(data: bytes) -> int:
    """
    Computes the standard OSDP / ISO 13239 16-bit CRC.
    Note: OSDP specification mandates initializing this to 0x1D0F.
    """
    crc = 0x1D0F  # 💡 FIXED: Changed from 0xFFFF to match the OSDP specification
    for byte in data:
        crc ^= (byte << 8)
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
                crc &= 0xFFFF
            else:
                crc = (crc << 1)
                crc &= 0xFFFF
    return crc

def build_osdp_id_request(address: int) -> bytes:
    """
    Assembles a raw unencrypted osdp_ID (0x61) request frame matching 
    LibOSDP's exact structural alignment parameters.
    Length = 5 bytes header + 1 byte CMD + 1 byte data parameter + 2 bytes CRC = 9 bytes total.
    """
    mark_byte = 0xFF 
    som = 0x53
    
    # 💡 FIX 1: Expand length parameter to 9 bytes total to match LibOSDP structure
    len_lsb = 0x09  
    len_msb = 0x00
    ctrl = 0x04     # Bit 2 indicates 16-bit CRC tracking mode is enabled
    cmd = 0x61      # OSDP_CMD_ID code indicator token
    
    # 💡 FIX 2: Inject the missing mandatory structural data byte parameter block
    cmd_data_param = 0x00 

    # Compile the complete message block for verification calculation
    packet_header = bytes([som, address, len_lsb, len_msb, ctrl, cmd, cmd_data_param])
    
    # Calculate the CRC using the updated 7-byte core array mapping
    crc_val = calculate_osdp_crc(packet_header)
    crc_bytes = struct.pack("<H", crc_val)
    
    # Combine everything together along with the leading preamble marker
    return bytes([mark_byte]) + packet_header + crc_bytes

def parse_osdp_pdid_response(response: bytes) -> dict | None:
    """
    Parse OSDP responses, accepting either PDID (0x45) or NAK (0x41) packets.
    Dynamically switches between 8-bit Checksum and 16-bit CRC validation.
    Handles potential leading 0xFF marker bytes transparently.
    """
    if not response:
        return None

    # Strip leading 0xFF preamble mark byte if present
    if response[0] == 0xFF:
        response = response[1:]

    if len(response) < 6:
        return None
    
    # Verify SOM structure parameter
    if response[0] != 0x53:
        return None
        
    ctrl_byte = response[4]
    reply_code = response[5]
    
    # DYNAMIC INTEGRITY VALIDATION: Determine check footprint size (CRC vs Checksum)
    is_crc = bool(ctrl_byte & 0x04)
    validation_len = 2 if is_crc else 1
    
    # Extract structural length declared inside packet header parameters
    packet_declared_len = response[2] | (response[3] << 8)
    if len(response) < packet_declared_len:
        return None  # Truncated buffer array
        
    # Isolate data slice from validation tail bytes
    payload_to_verify = response[:packet_declared_len - validation_len]
    
    if is_crc:
        calculated_crc = calculate_osdp_crc(payload_to_verify)
        received_crc = response[packet_declared_len - 2] | (response[packet_declared_len - 1] << 8)
        if calculated_crc != received_crc:
            return None  # Frame corrupted
    else:
        calculated_chk = calculate_checksum(payload_to_verify)
        received_chk = response[packet_declared_len - 1]
        if calculated_chk != received_chk:
            return None  # Frame corrupted

    # MATCH AND PARSE EXTRACTED REPLIES
    if reply_code == 0x45:  # osdp_PDID packet pattern
        # 💡 FIX: Shift data slice back to index 6. The 12 identification bytes 
        # map sequentially with no trailing padding spaces here.
        data = response[6:18]
        if len(data) < 12:
            return None

        # Little-endian bitwise operations (LSB first) matching your hardware tree definitions
        return {
            "type": "PDID",
            "vendor_code": data[0] | (data[1] << 8) | (data[2] << 16),      # 3 bytes LSB first
            "model_number": data[3],                                        # Model byte configuration
            "version": data[4],                                             # Version byte configuration
            "serial_number": data[5] | (data[6] << 8) | (data[7] << 16) | (data[8] << 24), # 4 bytes LSB first
            "firmware_version": f"{data[9]}.{data[10]}.{data[11]}",         # Clean version string syntax output
        }
        
    elif reply_code == 0x41:  # osdp_NAK packet pattern
        nak_error_code = response[6]
        
        nak_reasons = {
            1: "Invalid Message Checksum / CRC",
            2: "Command Record Not Found / Secure Channel Required",
            3: "Unimplemented Command Type",
            4: "Unexpected Sequence Number",
            5: "Security Block Rejected / Not Supported",
            6: "Encrypted Payload Decryption Failure"
        }
        reason_text = nak_reasons.get(nak_error_code, f"Unknown NAK Error Code (0x{nak_error_code:02X})")
        
        return {
            "type": "NAK",
            "error_code": nak_error_code,
            "reason": reason_text
        }

    return None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class OsdpManager(QObject):
    """Wraps an osdp.ControlPanel running in a background thread.

    All public command methods are thread-safe (they post to an internal queue
    that is drained in the CP background thread).

    Signals
    -------
    pd_online(address)
    pd_offline(address)
    event_received(data)
    log_message(text)
    error_occurred(text)
    connected()
    disconnected()
    scan_started()
    scan_progress(address_checked, total)
    pd_discovered(address, info_dict)
    pd_capabilities(address, caps_list)
    scan_finished(count)
    """

    pd_online = pyqtSignal(int)
    pd_offline = pyqtSignal(int)
    event_received = pyqtSignal(dict)
    log_message = pyqtSignal(str)
    error_occurred = pyqtSignal(str)
    connected = pyqtSignal()
    disconnected = pyqtSignal()

    scan_started = pyqtSignal()
    scan_progress = pyqtSignal(int, int)
    pd_discovered = pyqtSignal(int, dict)
    pd_capabilities = pyqtSignal(int, list)
    scan_finished = pyqtSignal(int)

    _POLL_INTERVAL = 0.02   # seconds between command queue checks in monitor thread
    _ONLINE_CHECK_INTERVAL = 2.0  # seconds between online-status polls

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cp: "osdp.ControlPanel | None" = None
        self._channel: "SerialChannel | None" = None
        self._monitor_thread: threading.Thread | None = None
        self._monitor_running = False
        self._refresh_lock = threading.Lock()
        self._cmd_queue: queue.Queue[dict] = queue.Queue()
        self._pd_address: int = 0
        self._pd_was_online: bool | None = None
        self._sim_mode = not OSDP_AVAILABLE
        self._scan_thread: threading.Thread | None = None
        self._scan_running = False

    # ------------------------------------------------------------------
    # public API – connection
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return self._monitor_running and (
            self._monitor_thread is not None and self._monitor_thread.is_alive()
        )

    def connect(
        self,
        port: str,
        baud_rate: int,
        pd_address: int,
        scbk: bytes | None = None,
        install_mode: bool = True,
    ) -> None:
        if self._monitor_running:
            self.disconnect()

        self._pd_address = pd_address
        self._pd_was_online = None

        if self._sim_mode:
            self._log(
                f"[SIM] Connected to {port} @ {baud_rate} baud – "
                f"PD {pd_address} {'install-mode' if install_mode else 'secure-channel'}"
            )
            self._monitor_running = True
            self._monitor_thread = threading.Thread(
                target=self._sim_loop, daemon=True, name="osdp-sim"
            )
            self._monitor_thread.start()
            self.connected.emit()
            return

        # real hardware path
        try:
            self._channel = SerialChannel(port, baud_rate)
        except Exception as exc:
            self.error_occurred.emit(f"Failed to open {port}: {exc}")
            return

        flags: list = []
        if install_mode:
            flags.append(osdp.LibFlag.InstallMode)

        pd_info = osdp.PDInfo(
            address=pd_address,
            channel=self._channel,
            scbk=scbk if (scbk and not install_mode) else None,
            flags=flags,
        )

        try:
            # log_level options: 7=Debug, 6=Info, 4=Warning, 3=Error, 0=None
            self._cp = osdp.ControlPanel([pd_info], log_level=7)
            self._log("ControlPanel created with debug logging enabled")
            self._cp.set_event_handler(self._on_event)
            self._cp.start()
            self._log("ControlPanel started successfully")
        except Exception as exc:
            self._channel.close()
            self._channel = None
            self.error_occurred.emit(f"OSDP CP init failed: {exc}")
            return

        self._monitor_running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="osdp-monitor"
        )
        self._monitor_thread.start()
        self._log(
            f"Connected → {port} @ {baud_rate} baud | "
            f"PD addr {pd_address} | "
            f"{'Install mode' if install_mode else 'Secure channel'}"
        )
        self.connected.emit()

    def disconnect(self) -> None:
        if not self._monitor_running:
            return
        self._monitor_running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=2.0)
            self._monitor_thread = None
        if self._cp is not None:
            try:
                self._cp.stop()
            except Exception:
                pass
            self._cp = None
        if self._channel is not None:
            self._channel.close()
            self._channel = None
        self._pd_was_online = None
        self._log("Disconnected")
        self.disconnected.emit()

    # ------------------------------------------------------------------
    # public API – commands (all thread-safe, post to queue)
    # ------------------------------------------------------------------

    def send_led(
        self,
        *,
        reader: int = 0,
        led_number: int = 0,
        perm_control_code: int = LedControlCode.SET,
        perm_on_color: int = LedColor.GREEN,
        perm_off_color: int = LedColor.NONE,
        perm_on_count: int = 5,
        perm_off_count: int = 5,
        temp_control_code: int = LedControlCode.NOP,
        temp_on_color: int = LedColor.NONE,
        temp_off_color: int = LedColor.NONE,
        temp_on_count: int = 0,
        temp_off_count: int = 0,
        temp_timer_count: int = 0,
    ) -> None:
        if not self._check_connected():
            return
        if self._sim_mode:
            cmd = {"command": "CMD_LED", "reader": reader, "led_number": led_number}
        else:
            # Use osdp library structure - don't include 'command' key for send_command
            cmd = {
                "reader": reader,
                "led_number": led_number,
                "control_code": perm_control_code,
                "on_count": perm_on_count,
                "off_count": perm_off_count,
                "on_color": perm_on_color,
                "off_color": perm_off_color,
                "temp_control_code": temp_control_code,
                "temp_on_count": temp_on_count,
                "temp_off_count": temp_off_count,
                "temp_on_color": temp_on_color,
                "temp_off_color": temp_off_color,
                "timer_count": temp_timer_count,
            }
        self._enqueue((osdp.Command.LED, cmd) if not self._sim_mode else cmd)
        self._log(
            f"LED cmd → reader={reader} led={led_number} | "
            f"perm: cc={perm_control_code} "
            f"on={LedColor.NAMES.get(perm_on_color,'?')} "
            f"off={LedColor.NAMES.get(perm_off_color,'?')} "
            f"on_cnt={perm_on_count} off_cnt={perm_off_count} | "
            f"temp: cc={temp_control_code} timer={temp_timer_count}"
        )

    def send_buzz(
        self,
        *,
        reader: int = 0,
        tone_code: int = ToneCode.DEFAULT,
        on_count: int = 3,
        off_count: int = 3,
        rep_count: int = 3,
    ) -> None:
        if not self._check_connected():
            return
        if self._sim_mode:
            cmd = {
                "command": "CMD_BUZ", 
                "reader": reader, 
                #"tone": tone_code
                }
        else:
            # Determine control_code based on tone selection
            if tone_code == ToneCode.OFF:
                control_code_val = 1  # 1 = Explicitly turn off buzzer
            else:
                control_code_val = 2  # 2 = Standard tone/beep activation
            
            # Use osdp library structure
            cmd = {
                "reader": reader,
                "control_code": control_code_val,
                # "tone": tone_code,
                "on_count": on_count,
                "off_count": off_count,
                "rep_count": rep_count,
            }
        self._enqueue((osdp.Command.Buzzer, cmd) if not self._sim_mode else cmd)
        self._log(
            f"BUZZ cmd → reader={reader} tone={ToneCode.NAMES.get(tone_code,'?')} "
            f"on={on_count} off={off_count} rep={rep_count}"
        )

    def send_keyset(self, *, key_data: bytes) -> None:
        if not self._check_connected():
            return
        if len(key_data) != 16:
            self.error_occurred.emit("KEYSET: key_data must be exactly 16 bytes")
            return
        if self._sim_mode:
            cmd = {"command": "CMD_KEYSET", "key_type": 1, "key_data": key_data}
        else:
            # Use osdp library structure - don't include 'command' key for send_command
            cmd = {
                "key_data": key_data,
            }
        self._enqueue((osdp.Command.Keyset, cmd) if not self._sim_mode else cmd)
        self._log(f"KEYSET cmd → key={key_data.hex().upper()}")

    def send_mfg(self, *, vendor_code: bytes, command_data: bytes) -> None:
        if not self._check_connected():
            return
        if len(vendor_code) != 3:
            self.error_occurred.emit("MFG: vendor_code must be exactly 3 bytes")
            return
        if self._sim_mode:
            cmd = {
                "command": "CMD_MFG",
                "vendor_code": vendor_code,
                "data": command_data
            }
        else:
            # Convert vendor_code bytes to integer (little-endian)
            vendor_code_int = int.from_bytes(vendor_code, byteorder='little')
            
            # Use osdp library structure
            cmd = {
                "vendor_code": vendor_code_int,
                "data": command_data,
            }
        self._enqueue((osdp.Command.Manufacturer, cmd) if not self._sim_mode else cmd)
        self._log(
            f"MFG cmd → vendor={vendor_code.hex().upper()} "
            f"data={command_data.hex().upper()}"
        )

    # ------------------------------------------------------------------
    # bus scan
    # ------------------------------------------------------------------

    def scan_bus(
        self,
        port: str,
        baud_rate: int,
        max_pd_address: int = 126,
    ) -> None:
        """Scan addresses 0 … max_pd_address for connected PDs."""
        if self._scan_running:
            return
        if not port:
            self.error_occurred.emit("Scan: no serial port configured.")
            return

        max_pd_address = max(0, min(126, max_pd_address))

        was_connected = self.is_connected
        if was_connected:
            self._log("Scan: pausing main connection…")
            self.disconnect()

        self._scan_running = True
        self.scan_started.emit()

        target = self._scan_loop_sim if self._sim_mode else self._scan_loop_real
        self._scan_thread = threading.Thread(
            target=target,
            args=(port, baud_rate, max_pd_address) if not self._sim_mode else (max_pd_address,),
            daemon=True,
            name="osdp-scan",
        )
        self._scan_thread.start()

    def stop_scan(self) -> None:
        self._scan_running = False
        if self._scan_thread:
            self._scan_thread.join(timeout=2.0)
            self._scan_thread = None
        self._log("Scan: aborted by user")

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------

    def _enqueue(self, cmd: dict) -> None:
        self._cmd_queue.put(cmd)

    def _check_connected(self) -> bool:
        if not self.is_connected:
            self.error_occurred.emit("Not connected – please connect first.")
            return False
        return True

    def _log(self, text: str) -> None:
        logger.info(text)
        self.log_message.emit(text)

    def _on_event(self, pd_address: int, event: dict) -> int:
        payload = {"pd": pd_address, **event}
        self.event_received.emit(payload)
        
        # Get event type and name
        ev_type_code = event.get("event", event.get("type", 0))
        ev_type_name = EventType.NAMES.get(ev_type_code, f"UNKNOWN({ev_type_code})")
        
        # Format event details based on type
        if ev_type_code == EventType.CARDREAD:
            reader = event.get("reader_no", 0)
            fmt = event.get("format", 0)
            direction = event.get("direction", 0)
            length = event.get("length", 0)
            data = event.get("data", b"")
            data_hex = data.hex().upper() if isinstance(data, bytes) else str(data)
            details = f"reader={reader} format={fmt} dir={direction} len={length} data={data_hex}"
        elif ev_type_code == EventType.KEYPRESS:
            reader = event.get("reader_no", 0)
            data = event.get("data", b"")
            data_hex = data.hex().upper() if isinstance(data, bytes) else str(data)
            details = f"reader={reader} keys={data_hex}"
        else:
            details = str({k: v.hex().upper() if isinstance(v, bytes) else v 
                          for k, v in event.items() if k not in ["event", "type"]})
        
        self._log(f"Event from PD {pd_address}: {ev_type_name} → {details}")
        return 0

    def _osdp_log_callback(self, log_level: int, message: str) -> None:
        """Callback for libosdp log messages."""
        # Log levels: 0=EMERG, 1=ALERT, 2=CRIT, 3=ERROR, 4=WARN, 5=NOTICE, 6=INFO, 7=DEBUG
        level_names = ["EMERG", "ALERT", "CRIT", "ERROR", "WARN", "NOTICE", "INFO", "DEBUG"]
        level_name = level_names[log_level] if 0 <= log_level < len(level_names) else "UNKNOWN"
        log_msg = f"[libosdp:{level_name}] {message.strip()}"
        
        # Forward to Python logger
        if log_level <= 3:  # ERROR and below
            logger.error(log_msg)
        elif log_level == 4:  # WARN
            logger.warning(log_msg)
        else:  # INFO, DEBUG
            logger.debug(log_msg)
        
        # Also emit to UI
        self.log_message.emit(log_msg)

    # ------------------------------------------------------------------
    # monitor thread (real hardware) – drains cmd queue, polls online status
    # ------------------------------------------------------------------

    def _monitor_loop(self) -> None:
        last_online_check = 0.0
        while self._monitor_running and self._cp is not None:
            # drain command queue
            while True:
                try:
                    item = self._cmd_queue.get_nowait()
                except queue.Empty:
                    break
                try:
                    # item is either (command_enum, dict) or just dict for sim mode
                    if isinstance(item, tuple):
                        cmd_type, cmd_dict = item
                        
                        # Inject command ID directly into dictionary as flat structure
                        cmd_dict['command'] = cmd_type
                        self._log(f"Sending to PD {self._pd_address}: {cmd_type} | {cmd_dict}")
                        
                        # Retry up to 3 times if queue is full
                        max_retries = 3
                        command_sent = False

                        for attempt in range(max_retries):
                            try:
                                # 2. Catch native library-level structural errors cleanly
                                    result = self._cp.submit_command(self._pd_address, cmd_dict)
                                    if result:
                                        self._log(f"Command sent successfully")
                                        command_sent = True
                                        break
                                    else:
                                        if attempt < max_retries - 1:
                                            retry_delay_ms = int(self._POLL_INTERVAL * 1000)
                                            self._log(f"Queue full, retrying in {retry_delay_ms}ms... (attempt {attempt + 1}/{max_retries})")
                                            time.sleep(self._POLL_INTERVAL)

                            except (ValueError, KeyError, SystemError, Exception) as lib_err:
                                self._log(f"[CRITICAL] LibOSDP Core Rejected Structure on attempt {attempt + 1}: {lib_err}")
                                if attempt < max_retries - 1:
                                    time.sleep(self._POLL_INTERVAL)
                                    continue
                        
                        if not command_sent:
                            # Track the estimated queue state for diagnostics
                            self._log(f"[QUEUE DIAGNOSTIC] System rejected command injection. "
                                     f"Target PD: {self._pd_address} | "
                                     f"Pending messages waiting in queue: {self._cmd_queue.qsize()}")
                            self.error_occurred.emit(
                                f"Command rejected after {max_retries} attempts. "
                                f"The PD command queue is full or parameters are invalid."
                            )

                    else:
                        # Simulation mode
                        cmd_dict = item
                        self._log(f"[SIM] Sending: {cmd_dict}")
                        result = True
                    
                except Exception as exc:
                    import traceback
                    tb = traceback.format_exc()
                    self.error_occurred.emit(f"Send command error: {exc}")
                    logger.error(f"Command send failed:\n{tb}")

            # 2. THE THROTTLED REFRESH: Fetch events and monitor state
            # Uses cp.get_event() to let the native background engine handle the heavy lifting
            try:
                event = self._cp.get_event(self._pd_address, timeout=0)
                if event:
                    self._log(f"Received hardware event: {event}")
            except Exception as ev_err:
                pass

            # poll online status (only every _ONLINE_CHECK_INTERVAL seconds)
            current_time = time.time()
            if current_time - last_online_check >= self._ONLINE_CHECK_INTERVAL:
                last_online_check = current_time
                try:
                    online = self._cp.is_online(self._pd_address)
                    if online != self._pd_was_online:
                        self._pd_was_online = online
                        if online:
                            self.pd_online.emit(self._pd_address)
                            self._log(f"PD {self._pd_address} is ONLINE")
                            # Query and report PD ID and capabilities when PD comes online
                            try:
                                pd_id = _safe_get_pd_id(self._cp, self._pd_address)
                                if pd_id:
                                    self.pd_discovered.emit(self._pd_address, pd_id)
                                    self._log(f"PD {self._pd_address} ID retrieved")
                            except Exception as id_err:
                                self._log(f"Failed to query PD ID: {id_err}")
                            
                            try:
                                caps = _safe_get_caps(self._cp, self._pd_address)
                                if caps:
                                    self.pd_capabilities.emit(self._pd_address, caps)
                                    self._log(f"PD {self._pd_address} capabilities retrieved: {len(caps)} items")
                            except Exception as cap_err:
                                self._log(f"Failed to query capabilities: {cap_err}")
                        else:
                            self.pd_offline.emit(self._pd_address)
                            self._log(f"PD {self._pd_address} is OFFLINE")
                except Exception:
                    pass

            time.sleep(self._POLL_INTERVAL)

    # ------------------------------------------------------------------
    # simulation loop
    # ------------------------------------------------------------------

    def _sim_loop(self) -> None:
        self._log("[SIM] Refresh loop started")
        time.sleep(1.0)
        if self._monitor_running:
            self.pd_online.emit(self._pd_address)
            self._log(f"[SIM] PD {self._pd_address} is ONLINE (simulated)")

        while self._monitor_running:
            try:
                cmd = self._cmd_queue.get_nowait()
                self._log(f"[SIM] Command executed: {cmd}")
            except queue.Empty:
                pass
            time.sleep(self._POLL_INTERVAL)

        self._log("[SIM] Refresh loop stopped")

    # ------------------------------------------------------------------
    # scan loops
    # ------------------------------------------------------------------

    def _scan_loop_real(self, port: str, baud_rate: int, max_pd_address: int) -> None:
        total = max_pd_address + 1
        self._log(f"Scan: {port} @ {baud_rate} | probing addresses 0–{max_pd_address} using raw OSDP packets …")

        # Open the serial port directly for raw packet I/O
        try:
            ser = serial.Serial(
                port=port,
                baudrate=baud_rate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=0.2,  # 200ms read timeout per OSDP spec
                write_timeout=1.0,
            )
        except Exception as exc:
            self.error_occurred.emit(f"Scan: failed to open port – {exc}")
            self._scan_running = False
            self.scan_finished.emit(0)
            return

        reported: set[int] = set()

        for addr in range(total):
            if not self._scan_running:
                break
            self.scan_progress.emit(addr, total)
            self._log(f"Scan: probing address {addr} …")

            try:
                # Build and send CMD_ID (0x61) packet
                id_request = build_osdp_id_request(addr)
                self._log(f"Scan: TX → {id_request.hex().upper()}")
                ser.write(id_request)
                ser.flush()
                
                # Wait for PDID (0x45) response
                time.sleep(0.050)  # Give PD time to process and respond
                
                # Read response (expected 19 bytes for PDID)
                response = ser.read(100)  # Read up to 100 bytes
                
                if response:
                    self._log(f"Scan: RX ← {response.hex().upper()}")
                    pd_id = parse_osdp_pdid_response(response)
                    
                    if pd_id:
                        reported.add(addr)
                        
                        # 💡 Handle different response types safely
                        if pd_id["type"] == "PDID":
                            self._log(
                                f"Scan: found PD {addr} | "
                                f"Vendor=0x{pd_id['vendor_code']:06X} "
                                f"Model={pd_id['model_number']} "
                                f"Ver={pd_id['version']} "
                                f"SN=0x{pd_id['serial_number']:08X}"
                            )
                            # Emit the native parsed dictionary to your UI thread channel
                            self.pd_discovered.emit(addr, pd_id)
                            
                        elif pd_id["type"] == "NAK":
                            self._log(
                                f"Scan: found Secure PD {addr} | "
                                f"Status=Encrypted Link Required (NAK 0x{pd_id['error_code']:02X}: {pd_id['reason']})"
                            )
                            
                            # Create a clean data structure format so your PyQt UI fields 
                            # don't trigger KeyErrors when trying to render the row values
                            mock_secure_pd = {
                                "type": "PDID", # Match type expected by UI rendering handlers
                                "vendor_code": 0x000000,
                                "model_number": 0,
                                "version": 0,
                                "serial_number": 0,
                                "firmware_version": 0,
                                "is_secure_only": True  # Flag to show a "Locked" shield icon in UI
                            }
                            self.pd_discovered.emit(addr, mock_secure_pd)
                        
                        # Clear capabilities for raw discover sweeps
                        self.pd_capabilities.emit(addr, [])
                    else:
                        self._log(f"Scan: invalid PDID response from address {addr}")
                else:
                    self._log(f"Scan: no response from address {addr}")
                    
            except Exception as exc:
                self._log(f"Scan: error probing addr {addr}: {exc}")
            
            # Clear any remaining bytes in the buffer before next probe
            try:
                ser.reset_input_buffer()
            except Exception:
                pass

        try:
            ser.close()
        except Exception:
            pass

        self._scan_running = False
        self._log(f"Scan: finished – {len(reported)} PD(s) found")
        self.scan_finished.emit(len(reported))

    def _scan_loop_sim(self, max_pd_address: int) -> None:
        total = max_pd_address + 1
        self._log(f"[SIM] Scan started: addresses 0–{max_pd_address}")
        fake_pds = {a: False for a in [0, 5] if a <= max_pd_address}

        for addr in range(total):
            if not self._scan_running:
                break
            self.scan_progress.emit(addr, total)
            time.sleep(0.040)  # simulate one poll window per address
            if addr in fake_pds and not fake_pds[addr]:
                fake_pds[addr] = True
                info = {
                    "vendor_code": 0xCAFE00 if addr == 0 else 0x001234,
                    "model_number": 1 if addr == 0 else 7,
                    "version": 1 if addr == 0 else 2,
                    "serial_number": 0xDEADBEEF if addr == 0 else 0xABCD1234,
                    "firmware_version": 0x010203 if addr == 0 else 0x030001,
                }
                self.pd_discovered.emit(addr, info)
                self._log(f"[SIM] Found PD at address {addr}")
                self.pd_capabilities.emit(addr, _sim_caps())

        self._scan_running = False
        found = sum(1 for v in fake_pds.values() if v)
        self._log("[SIM] Scan finished")
        self.scan_finished.emit(found)


# ---------------------------------------------------------------------------
# scan helpers
# ---------------------------------------------------------------------------

_CAP_MAP: list[tuple[Any, str]] = []  # populated lazily after osdp import

def _build_cap_map() -> None:
    global _CAP_MAP
    if _CAP_MAP or not OSDP_AVAILABLE:
        return
    c = osdp.Capability
    _CAP_MAP = [
        (c.ContactStatusMonitoring, "Contact Status Monitoring"),
        (c.OutputControl,           "Output Control"),
        (c.CardDataFormat,          "Card Data Format"),
        (c.LEDControl,              "Reader LED Control"),
        (c.AudibleControl,          "Reader Audible Output"),
        (c.TextOutput,              "Reader Text Output"),
        (c.TimeKeeping,             "Time Keeping"),
        (c.CheckCharacter,          "Check Character Support"),
        (c.CommunicationSecurity,   "Communication Security"),
        (c.ReceiveBufferSize,       "Receive Buffer Size"),
        (c.CombinedMessageSize,     "Combined Message Size"),
        (c.SmartCard,               "Smart Card Support"),
        (c.Readers,                 "Readers"),
        (c.Biometrics,              "Biometrics"),
    ]


def _safe_get_pd_id(cp: "osdp.ControlPanel", address: int) -> dict:
    try:
        pd_id = cp.get_pd_id(address)
        if pd_id is None:
            return {}
        return {
            "vendor_code": getattr(pd_id, "vendor_code", 0),
            "model_number":     getattr(pd_id, "model", 0),  # Changed to model_number for tree widget
            "version":          getattr(pd_id, "version", 0),
            "serial_number":    getattr(pd_id, "serial_number", 0),
            "firmware_version": getattr(pd_id, "firmware_version", 0),
        }
    except Exception:
        return {}


def _safe_get_caps(cp: "osdp.ControlPanel", address: int) -> list[dict]:
    _build_cap_map()
    caps: list[dict] = []
    for cap_const, name in _CAP_MAP:
        try:
            level, num_items = cp.check_capability(address, cap_const)
            if level > 0:
                caps.append({
                    "name": name,
                    "compliance_level": level,
                    "num_items": num_items,
                })
        except Exception:
            pass
    return caps


def _sim_caps() -> list[dict]:
    return [
        {"name": "Reader LED Control",    "compliance_level": 1, "num_items": 1},
        {"name": "Reader Audible Output", "compliance_level": 1, "num_items": 1},
        {"name": "Card Data Format",      "compliance_level": 1, "num_items": 1},
        {"name": "Communication Security","compliance_level": 1, "num_items": 1},
        {"name": "Readers",               "compliance_level": 1, "num_items": 1},
    ]
