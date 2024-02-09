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
- PyYAML>=6.0
- typing>=3.7.4.1
- requests>=2.27.1
- argparse>=1.4.0
- pandas>=1.3.5

### Client

For client-side communication with the socket server, the [libLogHelper](https://github.com/radhelper/libLogHelper) library is required. 
This is a C++ library that logs information during testing, and also includes a wrapper for Python applications.

Additionally, a Telnet server must be available on the client to execute command line programs being evaluated.

### On the server-side
- Configure server_parameters.yaml
- Configure/Create machines_cfgs/\<machine name\>.yaml
- Configure/Create machines_cfgs/\<machine name\>/\<machine name\>/\<benchmark name\>.json


# Contribute

The Python modules development follows (or at least we try) the 
[PEP8](https://www.python.org/dev/peps/pep-0008/) development rules. 
On the client side, we try to be as straightforward as possible.
If you wish to collaborate, submit a pull request.
