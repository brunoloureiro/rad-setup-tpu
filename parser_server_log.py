#!/usr/bin/python3
import argparse
import re

import pandas as pd


def parse_args() -> argparse.Namespace:
    """ Parse the args and return an args namespace and the tostring from the args    """
    parser = argparse.ArgumentParser(description='Radiation setup parser for the server logs')
    # parser = argparse.ArgumentParser(description='PyTorch DNN radiation setup')
    parser.add_argument('--logfile', help="Path to the logfile", required=True)

    args, remaining_argv = parser.parse_known_args()

    return args


def main() -> None:
    args = parse_args()
    lines = list()
    with open(args.logfile) as log_fp:
        for line in log_fp:
            m = re.match(r"(\d+)-(\d+)-(\d+) (\d+):(\d+):(\d+) (.*) (\S+).py:(\d+)", line)
            day, month, year, hour, minutes, seconds, detail, src_file, src_line = m.groups()
            line = dict()
            if "HARD REBOOT FOR" in detail:
                line["hard_reboot"] = 1
            if "SUCCESSFUL OS REBOOT" in detail:
                line["os_reboot"] = 1
            if "SUCCESSFUL SOFT REBOOT CMDS" in detail:
                line["app_reboot"] = 1
            m = re.match(r".*HOSTNAME:(\S+) .*", detail)
            if m:
                line["hostname"] = m.group(1)
            lines.append(line)

    df = pd.DataFrame(lines).fillna(0)
    print(df[df["hostname"] == 0])
    df = df.groupby(["hostname"]).sum()
    print(df)


if __name__ == '__main__':
    main()
