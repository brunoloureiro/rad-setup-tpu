# Setup for radiation experiments

This repository contains the libraries and scripts necessary to create a beam experiment setup.

# Getting started

The setup is generally divided between the Device Under Test and the server that controls the devices (clients) through
the network. Hence, both parts have different requirements. The server module is based on Python, while the logging on the
client-side is based on C++. A wrapper is also available for Python-based applications, but the library building
is also necessary.

## Requirements

The server and the client have different requirements, listed as follows.

### Server

The server is a set of modules written in Python. The following packages and tools are necessary to run the server:

- Python >=3.8
- PyYAML >=6.0

### Client

The client-side is based on C++, and the following dependencies are required:

- C++ 14
- CMake >=3.16**
- Telnet server (any version)

## Installing

TODO

### On client-side

#### Building the log_helper
TODO

### On server-side
- Configure server_parameters.yaml
- Configure/Create machines_cfgs/\<machine name\>.yaml
- Configure/Create machines_cfgs/\<machine name\>/\<machine name\>/\<benchmark name\>.json
# Contribute

The Python modules development follows (or at least we try) the 
[PEP8](https://www.python.org/dev/peps/pep-0008/) development rules. 
On the client side, we try to be as straightforward as possible.
If you wish to collaborate, submit a pull request.
