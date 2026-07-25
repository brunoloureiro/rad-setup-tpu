#!/usr/bin/env python3
"""
generate_bsp.py - Generate a standalone BSP from a linked XSA using the
Vitis 2025.1 Python API. Replaces the deprecated xsct-based generate_bsp.tcl.

Run via:
    vitis -s scripts/generate_bsp.py <xsa_path> <output_dir>

The script creates a Vitis platform component named 'bsp_platform' in a
workspace under <output_dir>/workspace/, builds it, and exits. The compiled
BSP ends up at:
    <output_dir>/workspace/bsp_platform/export/bsp_platform/sw/standalone_psv_cortexa72_0/

Arguments passed after the script name arrive in sys.argv[1:] when called
via 'vitis -s script.py arg1 arg2'.
"""

import sys
import os


def main():
    if len(sys.argv) < 3:
        print(
            "Usage: vitis -s scripts/generate_bsp.py <xsa_path> <output_dir>",
            file=sys.stderr,
        )
        sys.exit(1)

    xsa_path   = os.path.abspath(sys.argv[1])
    output_dir = os.path.abspath(sys.argv[2])
    workspace  = os.path.join(output_dir, "workspace")

    if not os.path.isfile(xsa_path):
        print(f"ERROR: XSA not found: {xsa_path}", file=sys.stderr)
        sys.exit(1)

    print(f"XSA:       {xsa_path}")
    print(f"Workspace: {workspace}")

    # 'vitis' is importable only when the script is run via 'vitis -s'.
    import vitis  # noqa: PLC0415

    client = vitis.create_client()
    client.set_workspace(path=workspace)

    # The processor name must be the full hierarchical instance name as it
    # appears in the XSA, not the short alias. The correct name was confirmed
    # from the xsct error output:
    #   "versal_cips_0_pspmc_0_psv_cortexa72_0"
    # 'psv_cortexa72_0' alone is rejected.
    comp = client.create_platform_component(
        name="bsp_platform",
        hw_design=xsa_path,
        os="standalone",
        cpu="psv_cortexa72_0",
        domain_name="standalone_psv_cortexa72_0",
    )

    # The default domain only includes core libraries (xil, xiltimer,
    # xilstandalone). The GUI-driven flow (gemm_tb_platform) additionally
    # requested these five libraries in its BSP settings -- without them,
    # the PS application link fails with "cannot find -laienginev2",
    # "-lxilsem", "-lxilpm", "-lmetal", "-lxilmailbox". Confirmed working
    # method via the domain object's own docstring: domain.set_lib().
    # NOTE: comp.get_domain(name=...) is used here to obtain the domain object.
    # Only the domain object's own methods (including set_lib, confirmed above)
    # were verified directly from your log output -- if get_domain isn't the
    # right accessor on this comp object, run dir(comp) in the interactive
    # shell to find the correct one (likely get_domain or list_domains-based).
    domain = comp.get_domain(name="standalone_psv_cortexa72_0")
    for lib_name in ("xilmailbox", "xilpm", "libmetal", "xilsem", "lwip220"):
        domain.set_lib(lib_name=lib_name)

    # lwip220 defaults to RAW API mode (no sockets/threads), which is what
    # src/ps/ethernet_channel.cpp is written against -- SOCKET_API needs a
    # real OS thread model this project's plain "standalone" domain doesn't
    # provide. Left at the .mld default (RAW_API) deliberately; no
    # domain.set_lib_config() call needed unless that ever changes.

    # Discover available domain config parameters (stdin/stdout among them) --
    # print once so you can see the exact parameter names and valid values
    # for your XSA's UART instance.

    #print(domain.list_params("os"))

    #print(domain.get_config(param_name="stdout"))  # adjust name based on what list_params(option="os") shows
    
    #domain.set_config(param_name="standalone_stdout", value="versal_cips_0_pspmc_0_psv_sbsauart_1")
    #domain.set_config(param_name="standalone_stdin", value="versal_cips_0_pspmc_0_psv_sbsauart_1")

    # Build the platform. 'vitis' drives the same underlying CMake build as
    # the GUI and correctly invokes the AArch64 cross-compiler, unlike the
    # deprecated 'xsct' path which produced x86_64 libraries in 2025.1.
    comp.build()

    client.close()

    bsp_export = os.path.join(
        workspace,
        "bsp_platform", "export", "bsp_platform",
        "sw", "standalone_psv_cortexa72_0",
    )
    print(f"BSP export: {bsp_export}")
    if not os.path.isdir(bsp_export):
        print(
            "WARNING: expected BSP export directory not found -- the workspace "
            "structure may differ; inspect the workspace and update BSP_DIR in "
            "the Makefile accordingly.",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
