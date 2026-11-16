# OSDP Control Panel

A PyQt6 desktop application for connecting an OSDP control panel (CP) to peripheral devices (PDs) over a serial RS-485 interface. It is intended for development, commissioning, and bench testing of OSDP readers.

## Features

- Connect to a PD using a configurable serial port, baud rate, and PD address.
- Scan OSDP addresses and inspect discovered device IDs and advertised capabilities.
- Send reader LED and buzzer commands.
- Send manufacturer-specific commands and view PD events in the application log.
- Configure install mode or a secure channel and send a `KEYSET` command.
- Use a software simulation path for UI and workflow testing when `libosdp` is unavailable. Simulation does not communicate with a physical bus.

The application is built with Python, PyQt6, `pyserial`, and `libosdp` (`pyosdp`).

## Requirements

- Python 3.10 or later
- A compatible OSDP PD and an RS-485 serial adapter for hardware operation
- A supported serial port and matching communication settings

## Install and run

From the repository directory:

```bash
python -m venv .venv
```

Activate the virtual environment, then install the dependencies and start the application:

```bash
python -m pip install -r requirements.txt
python main.py
```

In **Settings**, select the serial port and configure its baud rate, PD address, and security mode. The **Scan Bus** panel can search addresses from 0 to 126. A scan temporarily pauses an active connection.

## Security note

The application persists the Secure Channel Base Key (SCBK) in `config.json` as plaintext. Do not put production keys in a committed configuration file. Use a test key for development, protect local configuration files, and rotate any real key that has been exposed.

## Project article

- [Česky: OSDP Control Panel](https://www.codelec.cz/blog/osdp-control-panel/)
- [English: OSDP Control Panel](https://www.codelec.cz/en/blog/osdp-control-panel/)
