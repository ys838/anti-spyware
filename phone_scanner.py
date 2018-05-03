#!/usr/bin/env python3

import subprocess
import pandas as pd
import config
import os
import dataset
from datetime import datetime
import parse_dump
import blacklist
import re


db = dataset.connect(config.SQL_DB_PATH)


class AppScan(object):
    device_type = ''
    # app_info = pd.read_csv(config.APP_INFO_FILE, index_col='appId')
    app_info_conn = dataset.connect(config.APP_INFO_SQLITE_FILE)

    def __init__(self, dev_type, cli):
        assert dev_type in config.DEV_SUPPRTED, \
            "dev={!r} is not supported yet. Allowed={}"\
                .format(dev_type, config.DEV_SUPPRTED)
        self.device_type = dev_type
        self.cli = cli   # The cli of the device, e.g., adb or mobiledevice

    def setup(self):
        """If the device needs some setup to work."""
        pass

    def catch_err(self, p, cmd='', msg=''):
        try:
            p.wait(10)
            print("Returncode: ", p.returncode)
            if p.returncode != 0:
                m = ("[{}]: Error running {!r}. Error ({}): {}\n{}".format(
                    self.device_type, cmd, p.returncode, p.stderr.read(), msg
                ))
                config.add_to_error(m)
                return -1
            else:
                s = p.stdout.read().decode()
                if len(s) <= 100 and re.search('(?i)(fail|error)', s):
                    config.add_to_error(s)
                    return -1
                else:
                    return s
        except Exception as ex:
            config.add_to_error(ex)
            print("Exception>>>", ex)
            return -1

    def devices(self):
        raise Exception("Not implemented")

    def get_apps(self, serialno):
        pass

    def dump_file_name(self, serial, fsuffix='json'):
        return os.path.join(config.DUMP_DIR, '{}_{}.{}'.format(
            serial, self.device_type, fsuffix))

    def app_details(self, serialno, appid):
        try:
            d = pd.read_sql('select * from apps where appid=?', self.app_info_conn.engine,
                            params=(appid,))
            if not isinstance(d.get('permissions', ''), list):
                d['permissions'] = d.get('permissions', pd.Series([]))
                d['permissions'] = d['permissions'].fillna('').str.split(', ')
            if 'descriptionHTML' not in d:
                d['descriptionHTML'] = d['description']
            dfname = self.dump_file_name(serialno)
            if self.device_type == 'ios':
                ddump = parse_dump.IosDump(dfname)
            else:
                ddump = parse_dump.AndroidDump(dfname)
            info = ddump.info(appid)
            print("AppInfo: ", info, appid, dfname, ddump)
            # p = self.run_command(
            #     'bash scripts/android_scan.sh info {ser} {appid}',
            #     ser=serialno, appid=appid
            # ); p.wait()
            # d['info'] = p.stdout.read().decode().replace('\n', '<br/>')
            return d.fillna(''), info
        except KeyError as ex:
            print("Exception:::", ex)
            return pd.DataFrame([]), dict()

    def find_spyapps(self, serialno):
        """Finds the apps in the phone and add flags to them based on @blacklist.py
        Return the sorted dataframe
        """
        installed_apps = self.get_apps(serialno)
        # r = pd.read_sql('select appid, title from apps where appid in (?{})'.format(
        #     ', ?'*(len(installed_apps)-1)
        #     ), self.app_info_conn.engine, params=(installed_apps,))
        # r.rename({'appid': 'appId'}, axis='columns', copy=False, inplace=True)
        r = blacklist.app_title_and_flag(pd.DataFrame({'appId': installed_apps}))
        r['class_'] = r.flags.apply(blacklist.assign_class)
        r['score'] = r.flags.apply(blacklist.score)
        r['title'] = r.title.str.encode('ascii', errors='ignore').str.decode('ascii')
        r['flags'] = r.flags.apply(blacklist.flag_str)
        r.sort_values(by=['score', 'appId'], ascending=[False, True], inplace=True, na_position='last')
        r.set_index('appId', inplace=True)
        return r[['title', 'flags', 'score', 'class_']]

    def flag_apps(self, serialno):
        installed_apps = self.get_apps(serialno)
        app_flags = blacklist.flag_apps(installed_apps)
        return app_flags

    def uninstall(self, serialno, appid):
        pass

    def run_command(self, cmd, **kwargs):
        _cmd = cmd.format(
            cli=self.cli, **kwargs
        )
        print(_cmd)
        p = subprocess.Popen(
            _cmd,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True
        )
        return p

    def save(self, table, **kwargs):
        try:
            tab = db.get_table(table)
            kwargs['time'] = datetime.now()
            kwargs['device'] = kwargs.get('device', self.device_type)
            tab.insert(kwargs)
            db.commit()
            return True
        except Exception as ex:
            print(ex)
            return False


class AndroidScan(AppScan):
    """NEED Android Debug Bridge (adb) tool installed. Ensure your Android device
    is connected through Developer Mode with USB Debugging enabled, and `adb
    devices` showing the device as connected before running this scan function.

    """

    def __init__(self):
        super(AndroidScan, self).__init__('android', config.ADB_PATH)
        self.serialno = None
        self.installed_apps = None
        # self.setup()

    def setup(self):
        p = self.run_command(
            '{cli} kill-server; {cli} start-server'
        )
        if p != 0:
            print("Setup failed with returncode={}. ~~ ex={!r}"
                  .format(p.returncode, p.stderr.read() + p.stdout.read()))

    def _get_apps_(self, serialno, flag):
        cmd = "{cli} -s {serial} shell pm list packages {flag} | sed 's/package://g' | sort"
        s = self.catch_err(self.run_command(cmd, serial=serialno, flag=flag),
                           msg="App search failed", cmd=cmd)

        if not s:
            self.setup()
            return []
        else:
            installed_apps = [x for x in s.split() if x]
            return installed_apps

    def get_apps(self, serialno):
        installed_apps = self._get_apps_(serialno, '-u')
        if installed_apps:
            q = self.run_command(
                'bash scripts/android_scan.sh scan {ser}',
                ser=serialno); q.wait()
            self.installed_apps = installed_apps
        return installed_apps

    def get_system_apps(self, serialno):
        apps = self._get_apps_(serialno, '-s')
        return apps

    def devices(self):
        cmd = '{cli} devices | tail -n +2 | cut -f1'
        return [l.strip() for l in self.run_command(cmd)
                .stdout.read().decode('utf-8').split('\n') if l.strip()]

    def devices_info(self):
        cmd = '{cli} devices -l'
        return self.run_command(cmd).stdout.read().decode('utf-8')

    # def dump_phone(self, serialno=None):
    #     if not serialno:
    #         serialno = self.devices()[0]
    #     cmd = '{cli} -s {serial} shell dumpsys'
    #     p = self.run_command(cmd, serial=serialno)
    #     outfname = os.path.join(config.DUMP_DIR, '{}.txt.gz'.format(serialno))
    #     # if p.returncode != 0:
    #     #     print("Dump command failed")
    #     #     return
    #     with gzip.open(outfname, 'w') as f:
    #         f.write(p.stdout.read())
    #     print("Dump success! Written to={}".format(outfname))

    def uninstall(self, appid, serialno):
        cmd = '{cli} -s {serial} uninstall {appid!r}'
        s = self.catch_err(self.run_command(cmd, serial=serialno, appid=appid),
                           cmd=cmd, msg="Could not uninstall")
        return s != -1


class IosScan(AppScan):
    """
    NEED https://github.com/imkira/mobiledevice installed
    (`brew install mobiledevice` or build from source).
    """
    def __init__(self):
        super(IosScan, self).__init__('ios', config.MOBILEDEVICE_PATH)
        self.installed_apps = None
        self.serialno = None

    def get_apps(self, serialno):
        self.serialno = serialno
        # cmd = '{cli} -i {serial} install browse | tail -n +2 > {outf}'
        cmd = '{cli} -i {serial} -B | tail -n +3 > {outf}'
        dumpf = self.dump_file_name(serialno, 'json')
        if self.catch_err(self.run_command(cmd, serial=serialno, outf=dumpf)) != -1:
            print("Dumped the data into: {}".format(dumpf))
            s = parse_dump.IosDump(dumpf)
            self.installed_apps = s.installed_apps()
        else:
            self.installed_apps = []
        return self.installed_apps

    def get_system_apps(self, serialno):
        dumpf = self.dump_file_name(serialno, 'json')
        if os.path.exists(dumpf):
            s = parse_dump.IosDump(dumpf)
            return s.system_apps()
        else:
            return []

    def devices(self):
        cmd = '{cli} --detect -t1 | tail -n 1'
        self.serialno = None
        s = self.catch_err(self.run_command(cmd), cmd=cmd, msg="")
        print(s)
        return [l.strip() for l in s.split('\n') if l.strip()]

    def uninstall(self, appid, serialno):
        cmd = '{cli} -i {serial} --uninstall_only --bundle_id {appid!r}'
        s = self.catch_err(self.run_command(cmd, serial=serialno, appid=appid),
                           cmd=cmd, msg="Could not uninstall")
        return s != -1


class TestScan(AppScan):
    def __init__(self):
        super(TestScan, self).__init__('android', cli='cli')

    def get_apps(self, serialno):
        # assert serialno == 'testdevice1'
        installed_apps = open(config.TEST_APP_LIST, 'r').read().splitlines()
        return installed_apps

    def devices(self):
        return ["testdevice1", "testdevice2"]

    def get_system_apps(self, serialno):
        return self.get_apps(serialno)[:10]

    def uninstall(self, appid, serialno):
        return True


