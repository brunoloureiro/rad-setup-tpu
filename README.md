# Setup for radiation experiments

This repository contains the libraries and scripts necessary to create a beam experiment setup.

# Getting started

The setup is generally divided between the Device Under Test and the server that controls the devices (clients) through
the network. 
The server module is based on Python 3.10. 
An older version of the setup server is available at [radiation-setup with Python 3.8](https://github.com/radhelper/radiation-setup/tree/support_python3.8)

## Requirements

The requirements are divided into server and client requirements.

### Server

The following packages and tools are necessary to run the server:

- Python >=3.10
- PyYAML>=6.0
- typing>=3.7.4.1
- requests>=2.27.1
- argparse>=1.4.0
- pandas>=1.3.5
- Telnet Server

### Client

For client-side communication with the socket server, the [libLogHelper](https://github.com/radhelper/libLogHelper) library is required. 
This is a C++ library that logs information during testing, and also includes a wrapper for Python applications.

Additionally, a Telnet server must be available on the client to execute command line programs being evaluated.

### On the server-side

The possible parameters for the server.py are:
```bash
usage: server.py [-h] [-c PATH_YAML_FILE]

Server to monitor radiation experiments

options:
-h, --help            show this help message and exit
-c PATH_YAML_FILE, --config <Path to an YAML FILE that contains the server parameters. Default is ./server_parameters.yaml>
```

To get started, you need to configure the server_parameters.yaml file. 
This file will be used as a server parameter and contains the server's main parameters. 
[You can refer to the example provided for detailed guidance](https://github.com/radhelper/radiation-setup/blob/main/server_parameters.yaml).


Next, you will need to create a machine.yaml file for each board that you want to evaluate.
This file will describe the main parameters for the device. 
[You can refer to the example provided for more information](https://github.com/radhelper/radiation-setup/blob/main/machines_cfgs/carolk401.yaml). 

For each benchmark, you must create a JSON file describing the benchmark parameters. 
These parameters will be passed to the system under test. 
[You can refer to the example provided for detailed guidance](https://github.com/radhelper/radiation-setup/blob/main/machines_cfgs/dummy.json).


# Contribute

The Python modules development follows (or at least we try) the 
[PEP8](https://www.python.org/dev/peps/pep-0008/) development rules. 
On the client side, we try to be as straightforward as possible.
If you wish to collaborate, submit a pull request. 

**It is preferable to use IntelliJ IDEA tools for editing, i.e., Pycharm and Clion.**

## Issues that need addressing:

- [ ] Telnet is silent failing, details [here](https://github.com/radhelper/radiation-setup/issues/1)
- [ ] Configurations should circulate only when the timestamp of 1h is finished; details [here](https://github.com/radhelper/radiation-setup/issues/3)
- [ ] After the user stops the server, the configurations on the device keep running. Details [here](https://github.com/radhelper/radiation-setup/issues/4)
- [ ] Evaluate the advantages of Telnet over SSH

  


