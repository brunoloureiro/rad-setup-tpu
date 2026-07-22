# Radiation Setup Server

[![License: GPL-3.0](https://img.shields.io/badge/License-GPLv3-blue.svg)](https://opensource.org/licenses/GPL-3.0)

`radiation-setup` is the Python server component of the RADHelper framework.  
It acts as a main coordinator for radiation experiments by receiving log and control messages from remote clients (machines under test) and orchestrating experiment execution.

This server runs outside the beam room and communicates with devices through a network.

---

## 🚀 Features

- Multi-machine UDP listener server
- Saves received data in organized files with timestamps and addresses
- Configurable experiment parameters through YAML files
- Integrates with [libLogHelper](https://github.com/radhelper/libLogHelper) on the client side
- Uses Telnet for remote device command execution

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
                     |  • Start TCP listeners      |
                     |  • Receive log/data objects |
                     |  • Save data to disk        |
                     +-----------------------------+
```

Messages from clients are logged using [libLogHelper](https://github.com/radhelper/libLogHelper).  
The server collects those messages over UDP and stores them under `logs/` with timestamps.

---

## ⚙️ Getting Started

### Prerequisites

**Server requirements**

- Python ≥ 3.10
- PyYAML ≥ 6.0
- pandas ≥ 1.3.5
- requests ≥ 2.27.1
- Telnet server installed

**Client requirements**

- `libLogHelper` C++ logging library (includes Python wrapper)
- Telnet or SSH server for running workloads on the device under test

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

Each device under test must have its own configuration file in `machines_cfgs/`.

Example:

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
json_files: [
    "machines_cfgs/dummy.json",
]

```

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


