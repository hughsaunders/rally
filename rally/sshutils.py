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
import os
import paramiko
import random
import select
import socket
import string
import time
from StringIO import StringIO

from rally import exceptions
from rally.openstack.common.gettextutils import _  # noqa
from rally.openstack.common import log as logging

LOG = logging.getLogger(__name__)

class SSH(object):
    """SSH common functions."""

    def __init__(self, ip, user, port=22, key=None, key_string=None, timeout=1800):
        """Initialize SSH client with ip, username and the default values.

        timeout - the timeout for execution of the command
        """
        self.ip = ip
        self.user = user
        self.timeout = timeout
        self.client = None
        if key_string:
            self.key_string=key_string
        else:
            if key:
                self.key = key
            else:
                self.key = os.path.expanduser('~/.ssh/id_rsa')

    @classmethod
    def generate_ssh_keypair(cls, key_size=2048):
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


    def _get_ssh_connection(self):
        self.client = paramiko.SSHClient()
        self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        connect_params={
            'hostname': self.ip,
            'username': self.user
        }
        if self.key_string:
            connect_params['pkey']=paramiko.RSAKey(
                    file_obj=StringIO(self.key_string))
        else:
            connect_params['key_filename']=self.key
        self.client.connect(**connect_params)

    def _is_timed_out(self, start_time):
        return (time.time() - self.timeout) > start_time

    def execute(self, *cmd):
        """Execute the specified command on the server."""
        stdout=''
        stderr=''
        self._get_ssh_connection()
        cmd = ' '.join(cmd)
        transport = self.client.get_transport()
        channel = transport.open_session()
        channel.fileno()
        channel.exec_command(cmd)
        channel.shutdown_write()
        poll = select.poll()
        poll.register(channel, select.POLLIN)
        start_time = time.time()
        while True:
            ready = poll.poll(16)
            if not any(ready):
                if not self._is_timed_out(start_time):
                    continue
                raise exceptions.TimeoutException('SSH Timeout')
            if not ready[0]:
                continue
            out_chunk = err_chunk = None
            if channel.recv_ready():
                out_chunk = channel.recv(4096)
                LOG.debug(out_chunk)
                stdout+=out_chunk
            if channel.recv_stderr_ready():
                err_chunk = channel.recv_stderr(4096)
                LOG.debug(err_chunk)
                stderr+=err_chunk
            if channel.closed and not err_chunk and not out_chunk:
                break
        exit_status = channel.recv_exit_status()
        if 0 != exit_status:
            raise exceptions.SSHError(
                'SSHExecCommandFailed with exit_status %s'
                % exit_status)
        self.client.close()
        return {'stdout': stdout, 'stderr': stderr}

    def upload(self, source, destination):
        """Upload the specified file to the server."""
        if destination.startswith('~'):
            destination = '/home/' + self.user + destination[1:]
        self._get_ssh_connection()
        ftp = self.client.open_sftp()
        ftp.put(os.path.expanduser(source), destination)
        ftp.close()

    def execute_script(self, script, enterpreter='/bin/sh'):
        """Execute the specified local script on the remote server."""
        destination = '/tmp/' + ''.join(
            random.choice(string.lowercase) for i in range(16))

        self.upload(script, destination)
        self.execute('%s %s' % (enterpreter, destination))
        self.execute('rm %s' % destination)

    def wait(self, timeout=120, interval=1):
        """Wait for the host will be available via ssh."""
        with eventlet.timeout.Timeout(timeout, exceptions.TimeoutException):
            while True:
                try:
                    return self.execute('uname')
                except (socket.error, exceptions.SSHError) as e:
                    LOG.debug(
                        _('Ssh is still unavailable. (Exception was: %r)') % e)
                    eventlet.sleep(interval)
