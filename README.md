# Radiation Setup Server

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://opensource.org/licenses/GPL-3.0)

`radiation-setup` is the Python server component of the RADHelper framework.  
It acts as a main coordinator for radiation experiments by receiving log and control messages from remote clients (machines under test) and orchestrating experiment execution.

This server runs outside the beam room and communicates with devices through a network.

---

## 🚀 Features

Each DUT is configured along three independent axes:

- **`dut_mode`: `active` or `passive`** — how the app is (re)started. `active` DUTs run an OS and
  are driven over a console (login + kill/run commands from `json_files`). `passive` (bare-metal)
  DUTs have no OS/shell; the server instead runs a local `redeploy_cmd` (e.g. a JTAG/xsct script)
  to (re)load and start the app, immediately after power-on.
- **`console_type`: `telnet` or `jtag`** — only meaningful for `dut_mode: active` (`passive` DUTs
  never open a console). `telnet` (default) is a network Telnet connection. `jtag` logs in over a
  JTAG probe's serial/UART bridge instead, for DUTs with no network path to a console.
- **`connection_type`: `ethernet` or `jtag`** — how the server listens for DUT status/log messages
  (`#IT`, `#LOGFILE`, `#CMD`, ...). `ethernet` (default) is a UDP socket bound to
  `server_ip:receive_port`. `jtag` reads the JTAG probe's serial/UART bridge instead, for DUTs with
  no network stack at all.

Any combination is valid - see [`CLAUDE.md`](CLAUDE.md) for the full architecture writeup.

- Multi-machine listener server (UDP or JTAG serial, per DUT)
- Saves received data in organized files with timestamps and addresses
- Configurable experiment parameters through YAML files
- Integrates with [libLogHelper](https://github.com/radhelper/libLogHelper) on the client side
- `active` DUTs: Telnet or JTAG-serial console for remote command execution. `passive` DUTs: a
  local redeploy command (e.g. driving a JTAG probe) to (re)load and start the app
- DUTs can request server-side actions (e.g. a power cycle) at runtime through a `#CMD` message

---

## 🧩 Architecture Overview

```
 +----------------+        +----------------+         +----------------+
 |    Client A    |        |    Client B    |         |    Client N    |
 | (libLogHelper) | -----> | (libLogHelper) |  ...    | (libLogHelper) |
 +----------------+        +----------------+         +----------------+
          |                        |                          |
          v                        v                          v
                     +-----------------------------+
                     | Radiation Setup Server      |
                     |                             |
                     |  • Listen for DUT messages  |
                     |  • Receive log/data objects |
                     |  • Save data to disk        |
                     +-----------------------------+
```

Messages from clients are logged using [libLogHelper](https://github.com/radhelper/libLogHelper).
The server collects those messages - over a UDP socket (`connection_type: ethernet`) or a JTAG
probe's serial/UART bridge (`connection_type: jtag`), per DUT - and stores them under `logs/` with
timestamps.

---

## ⚙️ Getting Started

### Prerequisites

**Server requirements**

- Python ≥ 3.10
- PyYAML ≥ 6.0
- pandas ≥ 1.3.5
- requests ≥ 2.27.1
- pyserial ≥ 3.5 (only required if any DUT uses `connection_type: jtag` and/or `console_type: jtag`)
- Telnet client installed (only required if any DUT uses `console_type: telnet`, the default for
  `dut_mode: active`)

**Client requirements**

- `libLogHelper` C++ logging library (includes Python wrapper), for `dut_mode: active` DUTs
- A Telnet server (or JTAG-reachable console) for running workloads on `dut_mode: active` DUTs
- A JTAG probe (e.g. an FTDI-based UART bridge, or a Xilinx-style debug probe driven by
  `xsct`/`xsdb`) for `dut_mode: passive` DUTs, and/or for `connection_type: jtag`/`console_type: jtag`

---

## 📦 Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/radhelper/radiation-setup.git
cd radiation-setup
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

---

## 🛠 Configuration

### Server configuration

The server uses a YAML file (`server_parameters.yaml`) defining machines and global settings.

Example:

```yaml
server_ip: 192.168.1.5
server_log_file: server.log
server_log_store_dir: logs/
machines: [
  {
    "enabled": True, "cfg_file": "machines_cfgs/carola20001.yaml"
  },
  {
    "enabled": False, "cfg_file": "machines_cfgs/p20001.yaml"
  },
]
```

---

### Machine configuration

Each device under test must have its own configuration file in `machines_cfgs/`. Three independent
fields, `dut_mode`, `console_type`, and `connection_type`, select the combination that fits your
DUT - see "Features" above for what each value means.

**`dut_mode: active` (default), `connection_type: ethernet` (default)** - an OS-based DUT reachable
over Telnet, reporting status over UDP. This is the original/default mode:

```yaml
ip:  192.168.195.6
receive_port: 1024
hostname: caroldummy
username: carol
password: qwerty0
power_switch_ip: 192.168.1.100
power_switch_port: !!int 1
power_switch_model: lindy
boot_waiting_time: !!int 60
max_timeout_time: !!int 10
disable_os_soft_reboot: !!bool True
connection_type: ethernet
json_files: [
    "machines_cfgs/dummy.json",
]
```

**`connection_type: jtag`** - listen for DUT status/log messages over a JTAG probe's serial/UART
bridge instead of UDP (independent of `dut_mode`/`console_type`; this only changes how messages are
*received*):

```yaml
connection_type: jtag
jtag_port: /dev/ttyUSB0
jtag_baudrate: !!int 115200   # optional, defaults to 115200
```

**`dut_mode: active`, `console_type: jtag`** - an OS-based DUT with no network path to a console
(e.g. an isolated bring-up board), logged into over a JTAG probe's serial/UART bridge instead of
Telnet. `ip` is not needed; `username`/`password` still are. Independent of `connection_type` -
this DUT can still report status over Ethernet if its network stack works, even though its console
doesn't have one:

```yaml
console_type: jtag
console_jtag_port: /dev/ttyUSB2
console_jtag_baudrate: !!int 115200   # optional, defaults to 115200
username: carol
password: qwerty0
connection_type: ethernet   # or jtag, independently - see above
```

**`dut_mode: passive`** - a bare-metal DUT with no OS/shell. Instead of Telnet kill/run commands,
the server runs a local `redeploy_cmd` (e.g. a JTAG/xsct deployment script) to (re)load and start
the app, immediately after power-on:

```yaml
hostname: versal_bm_jtag
power_switch_ip: 192.168.0.100
power_switch_port: !!int 1
power_switch_model: lindy
boot_waiting_time: !!int 60   # unused for dut_mode: passive
max_timeout_time: !!int 5
dut_mode: passive
connection_type: jtag         # this DUT has no network stack, so messages come over JTAG too
jtag_port: /dev/ttyUSB1
redeploy_cmd: ["xsct", "/home/user/scripts/deploy.tcl"]
redeploy_timeout: !!int 90    # optional, defaults to 60
test_name: versal_bm_jtag     # used to name DUTLogging files (json_files is optional here)
```

See `machines_cfgs/versal_bm_jtag_passive.yaml` and `machines_cfgs/versal_bm_eth_passive.yaml` for
full worked examples (the latter is `dut_mode: passive` with `connection_type: ethernet` - a
bare-metal DUT that still has a working network stack to send its status messages over).

---

### Benchmark configuration

Benchmarks are described through JSON files.

Example:

```json
[
  {
    "killcmd": "killall -9 example_cxx",
    "exec": "/home/carol/libLogHelper/build/examples/example_cxx",
    "codename": "example_cxx",
    "header": "dummy example_cxx from LibLogHelper"
  }
]
```

---

### DUT-requested commands

A DUT can ask the server to perform an action at any time by sending a message (over whichever
`connection_type` is configured - UDP or JTAG serial) whose payload starts with `#CMD`, followed by
the command name:

```
#CMD HARD_REBOOT
#CMD SOFT_REBOOT
```

Supported commands:

| Command       | Effect                                                              |
|---------------|----------------------------------------------------------------------|
| `HARD_REBOOT` | Power cycle the DUT through its power switch, then restart the benchmark |
| `SOFT_REBOOT` | Kill and re-run the current benchmark, without power cycling the DUT |
| `OPEN_BEAM`   | **Stub only** - currently just logs that the command was received, no action taken yet |
| `CLOSE_BEAM`  | **Stub only** - currently just logs that the command was received, no action taken yet |

`OPEN_BEAM`/`CLOSE_BEAM` are sent by some DUT firmwares (e.g. the Versal bare-metal app) to signal
a beam-on/beam-off window. The server currently only logs these (`server/machine.py`'s
`__on_open_beam_command`/`__on_close_beam_command`) - real handling (e.g. tagging DUT logs with the
beam window, or driving experiment bookkeeping off of it) is not implemented yet and is intended to
be completed at a later date.

Commands are dispatched through `server/dut_commands.py`'s `DUTCommandDispatcher`. Adding a new
one only requires adding a member to the `DUTCommand` enum and registering a handler for it in
`Machine.__init__` (`server/machine.py`) — no other code needs to change.

---

## ▶️ Running the Server

Start the server with:

```bash
python3 server.py --config path/to/server_parameters.yaml
```

To view options:

```bash
python server.py -h
```

---



## 🤝 Contributing

- Pull requests are welcome
- Python code follows PEP8: The Python modules development follows (or at least we try) the 
[PEP8](https://www.python.org/dev/peps/pep-0008/) development rules. 
On the client side, we try to be as straightforward as possible.
If you wish to collaborate, submit a pull request. 

**It is preferable to use IntelliJ IDEA tools for editing, i.e., Pycharm and Clion.**

### Issues that need addressing:

- [ ] Telnet is silent failing, details [here](https://github.com/radhelper/radiation-setup/issues/1)
- [ ] Configurations should circulate only when the timestamp of 1h is finished; details [here](https://github.com/radhelper/radiation-setup/issues/3)
- [ ] After the user stops the server, the configurations on the device keep running. Details [here](https://github.com/radhelper/radiation-setup/issues/4)
- [ ] Evaluate the advantages of Telnet over SSH

---


