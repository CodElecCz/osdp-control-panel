# OSDP Control Panel: testing readers over RS-485

OSDP Control Panel is a Python and PyQt6 desktop application for working with OSDP peripheral devices (PDs), such as readers. It connects as a Control Panel (CP) over a serial RS-485 link and brings common development and commissioning tasks into one graphical interface.

## Discover and inspect devices

The **PD** panel can scan OSDP addresses from 0 to 126. For discovered devices it displays the vendor, model, version, serial number, and capabilities reported by the PD. Connection status and communication details appear in the application status area and live log.

To connect, configure a serial port, baud rate, and PD address. A bus scan pauses an active connection and lists the devices it finds.

## Control reader outputs

Dedicated tabs prepare OSDP commands for reader functions:

- **LED** — set a permanent LED state and optionally apply a temporary override with color, blink timing, and duration.
- **Buzzer** — configure the tone, on/off intervals, and repeat count.
- **MFG** — send a manufacturer-specific command with a vendor code and data.
- **Security** — configure secure-channel mode and send a `KEYSET` command.

The PD can also report events; these appear in the log alongside connection status and diagnostic messages.

## Architecture and testing

`OsdpManager` connects the Qt UI to `pyosdp`. UI commands are queued and processed by a monitoring thread so communication does not block the main window. If `libosdp` is unavailable, the application uses a simulation path with synthetic devices and commands; that path does not communicate over a physical bus.

## Run the application

Python 3.10 or later is required. From the repository root, create a virtual environment, install dependencies, and start the main module:

```bash
python -m venv .venv
python -m pip install -r requirements.txt
python main.py
```

Hardware operation requires an OSDP PD and a compatible RS-485 adapter. Configure the serial port, baud rate, address, and security mode in **Settings**.

> **Security:** The application stores the SCBK in `config.json` as plaintext. Use a test key for development, do not commit production keys in configuration files, and replace any real key that has been exposed.

Source code: [CodElecCz/osdp-control-panel](https://github.com/CodElecCz/osdp-control-panel).
