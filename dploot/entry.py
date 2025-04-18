import argparse
import importlib.metadata
import logging
import sys
import traceback

from impacket.examples import logger

from dploot.action import (
    certificates,
    credentials,
    masterkeys,
    vaults,
    backupkey,
    rdg,
    sccm,
    triage,
    machinemasterkeys,
    machinecredentials,
    machinevaults,
    machinecertificates,
    machinetriage,
    browser,
    wifi,
    mobaxterm,
    )


ENTRY_PARSERS = [
    certificates,
    credentials,
    masterkeys,
    vaults,
    backupkey,
    rdg,
    sccm,
    triage,
    machinemasterkeys,
    machinecredentials,
    machinevaults,
    machinecertificates,
    machinetriage,
    browser,
    wifi,
    mobaxterm,
]

def main() -> None:
    logger.init()
    version = importlib.metadata.version("dploot")
    parser = argparse.ArgumentParser(description=f"DPAPI looting remotely in Python.\nVersion {version}", add_help=True)

    parser.add_argument("-debug", action="store_true", help="Turn DEBUG output ON")

    parser.add_argument("-quiet", action="store_true", help="Only output dumped credentials")

    subparsers = parser.add_subparsers(help="Action", dest="action", required=True)

    actions = dict()

    for entry_parser in ENTRY_PARSERS:
        action, entry = entry_parser.add_subparser(subparsers)
        actions[action] = entry

    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(1)

    options = parser.parse_args()

    if options.debug is True:
        logging.getLogger().setLevel(logging.DEBUG)
    elif options.quiet is True:
        logging.getLogger().setLevel(logging.CRITICAL)
    else:
        logging.getLogger().setLevel(logging.INFO)

    logging.debug(f"{options=}")
    try:
        actions[options.action](options)
    except Exception as e:
        logging.error("Got error: %s" % e)
        if options.debug:
            traceback.print_exc()
        else:
            logging.error("Use -debug to print a stacktrace")


if __name__ == "__main__":
    main()
