# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import eventlet
import paramiko
import subprocess
from StringIO import StringIO

from rally import exceptions
from rally.openstack.common.gettextutils import _  # noqa
from rally.openstack.common import log as logging

DEFAULT_OPTIONS = ['-o', 'StrictHostKeyChecking=no']

LOG = logging.getLogger(__name__)


class SSHException(Exception):
    pass

def generate_ssh_keypair(key_size=2048):
    priv_key = paramiko.RSAKey.generate(key_size)
    priv_key_file = StringIO()
    priv_key.write_private_key(file_obj=priv_key_file)
    priv_key_file.seek(0)
    priv_key_string = priv_key_file.read()
    priv_key_file.seek(0)

    pub_key = paramiko.RSAKey(file_obj=priv_key_file)
    pub_key_string = "ssh-rsa %s" %(pub_key.get_base64(),)

    return {'private': priv_key_string,
            'public':  pub_key_string}


def upload_file(user, host, source, destination):
    cmd = ['scp'] + DEFAULT_OPTIONS + [source, '%s@%s:%s' % (user, host,
                                                             destination)]
    pipe = subprocess.Popen(cmd, stderr=subprocess.PIPE)
    (so, se) = pipe.communicate()
    if pipe.returncode:
        raise SSHException(se)


def execute_script(user, host, script, enterpreter='/bin/sh'):
    cmd = ['ssh'] + DEFAULT_OPTIONS + ['%s@%s' % (user, host), enterpreter]
    subprocess.check_call(cmd, stdin=open(script, 'r'))


def execute_command(user, host, cmd):
    pipe = subprocess.Popen(['ssh'] + DEFAULT_OPTIONS +
                            ['%s@%s' % (user, host)] + cmd,
                            stderr=subprocess.PIPE)
    (so, se) = pipe.communicate()
    if pipe.returncode:
        raise SSHException(se)



class SSH(object):
    """SSH common functions."""

    OPTIONS = ['-o', 'StrictHostKeyChecking=no']

    def __init__(self, ip, user, port=22):
        self.ip = ip
        self.user = user

    def execute(self, *cmd):
        pipe = subprocess.Popen(['ssh'] + self.OPTIONS +
                                ['%s@%s' % (self.user, self.ip)] + list(cmd),
                                stderr=subprocess.PIPE)
        (out, err) = pipe.communicate()
        if pipe.returncode:
            raise exceptions.SSHError(err)

    def execute_script(self, script, enterpreter='/bin/sh'):
        cmd = ['ssh'] + self.OPTIONS + ['%s@%s' % (self.user, self.ip),
                                        enterpreter]
        pipe = subprocess.Popen(cmd, stdin=open(script, 'r'),
                                stderr=subprocess.PIPE)
        (out, err) = pipe.communicate()
        if pipe.returncode:
            raise exceptions.SSHError(err)

    def wait(self, timeout=15, interval=1):
        with eventlet.timeout.Timeout(timeout, exceptions.TimeoutException):
            while True:
                try:
                    return self.execute('uname')
                except exceptions.SSHError as e:
                    LOG.debug(_('Ssh is still unavailable. '
                                'Exception is: ') + repr(e))
                    eventlet.sleep(interval)

    def upload(self, source, destination):
        cmd = ['scp'] + self.OPTIONS + [
            source, '%s@%s:%s' % (self.user, self.ip, destination)]
        pipe = subprocess.Popen(cmd, stderr=subprocess.PIPE)
        (out, err) = pipe.communicate()
        if pipe.returncode:
            raise exceptions.SSHError(err)
