# Versal support

## Quick reset

Use the tcl scripts to re-deploy upon seeing a crash/exit/abort/etc.

### SDCs

The current implementation of the experiment setup (re)loads the input/golden data from DRAM... this is obviously problematic. One option is to actually have it re-read from SD card (adds a lot of overhead + interrupts), or to have the server push the binary via xsdb (not the worst, but need to benchmark it). The other option is just a full elf reset each time. Benchmark and evaluate these options.
