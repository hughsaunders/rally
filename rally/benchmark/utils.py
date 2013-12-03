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

import multiprocessing
import os
import pytest
import random
import traceback

import fuel_health.cleanup as fuel_cleanup

from rally.benchmark import base
from rally.openstack.common.gettextutils import _  # noqa
from rally.openstack.common import log as logging
from rally import osclients
from rally import sshutils
from rally import utils


LOG = logging.getLogger(__name__)

# NOTE(msdubov): This list is shared between multiple scenario processes.
__openstack_clients__ = []


def _format_exc(exc):
    return [str(type(exc)), str(exc), traceback.format_exc()]


def _run_scenario_loop(args):
    i, cls, method_name, context, kwargs = args

    LOG.info("ITER: %s" % i)

    # NOTE(msdubov): Each scenario run uses a random openstack client
    #                from a predefined set to act from different users.
    cls.clients = random.choice(__openstack_clients__)

    cls.idle_time = 0

    scenario_specific_results = None
    try:
        with utils.Timer() as timer:
            scenario_specific_results = getattr(cls, method_name)(context,
                    **kwargs)
    except Exception as e:
        return {"time": timer.duration() - cls.idle_time,
                "idle_time": cls.idle_time, "error": _format_exc(e)}
    return {"time": timer.duration() - cls.idle_time,
            "idle_time": cls.idle_time, "error": None,
            "scenario_specific_results":scenario_specific_results}

    # NOTE(msdubov): Cleaning up after each scenario loop enables to delete
    #                the resources of the user the scenario was run from.
    cls.cleanup(context)


def _create_openstack_clients(users_endpoints, keys):
    # NOTE(msdubov): Creating here separate openstack clients for each of
    #                the temporary users involved in benchmarking.
    client_managers = [osclients.Clients(*[credentials[k] for k in keys])
                       for credentials in users_endpoints]

    clients = [
        dict((
            ("nova", cl.get_nova_client()),
            ("keystone", cl.get_keystone_client()),
            ("glance", cl.get_glance_client()),
            ("cinder", cl.get_cinder_client())
        )) for cl in client_managers
    ]

    return _prepare_for_instance_ssh(clients)


def _prepare_for_instance_ssh(clients):
    """Generate and store SSH keys, allow access to port 22.

    In order to run tests on instances it is necessary to have SSH access.
    This function generates an SSH key pair per user which is stored in the 
    clients dictionary. The public key is also submitted to nova via the 
    novaclient.

    A security group rule is created to allow access to instances on port 22.
    """


    for client_dict in clients:
        nova_client = client_dict['nova']

        if ('rally_ssh_key' not in
            [k.name for k in nova_client.keypairs.list()]):
            client_dict['ssh_key_pair'] = sshutils.generate_ssh_keypair()
            nova_client.keypairs.create(
                'rally_ssh_key',client_dict['ssh_key_pair']['public'])

        default_sec_group = nova_client.security_groups.find(name='default')
        if not [rule for rule in default_sec_group.rules if 
                rule['ip_protocol']=='tcp' 
                and rule['to_port']==22
                and rule['from_port']==22 
                and rule['ip_range']=={'cidr':'0.0.0.0/0'}
        ]:
            nova_client.security_group_rules.create(
                    default_sec_group.id, from_port=22, to_port=22,
                    ip_protocol='tcp', cidr='0.0.0.0/0')

    return clients


class ScenarioRunner(object):
    """Tool that gets and runs one Scenario."""
    def __init__(self, task, cloud_config):
        self.task = task
        self.endpoints = cloud_config
        keys = ["admin_username", "admin_password", "admin_tenant_name", "uri"]
        self.clients = _create_openstack_clients([self.endpoints], keys)[0]
        base.Scenario.register()

    def _create_temp_tenants_and_users(self, tenants, users_per_tenant):
        self.tenants = [self.clients["keystone"].tenants.create("tenant_%d" %
                                                                i)
                        for i in range(tenants)]
        self.users = []
        temporary_endpoints = []
        for tenant in self.tenants:
            for uid in range(users_per_tenant):
                username = "user_%(tid)s_%(uid)d" % {"tid": tenant.id,
                                                     "uid": uid}
                password = "password"
                user = self.clients["keystone"].users.create(username,
                                                             password,
                                                             "%s@test.com" %
                                                             username,
                                                             tenant.id)
                self.users.append(user)
                user_credentials = {
                    "username": username,
                    "password": password,
                    "tenant_name": tenant.name,
                    "uri": self.endpoints["uri"],
                    "ssh_key_pair": sshutils.generate_ssh_keypair()
                    }
                temporary_endpoints.append(user_credentials)


        return temporary_endpoints

    def _delete_temp_tenants_and_users(self):
        for user in self.users:
            user.delete()
        for tenant in self.tenants:
            tenant.delete()

    def _run_scenario(self, ctx, cls, method, args, times, concurrent,
                      timeout):
        test_args = [(i, cls, method, ctx, args) for i in xrange(times)]

        pool = multiprocessing.Pool(concurrent)
        iter_result = pool.imap(_run_scenario_loop, test_args)

        results = []
        for i in range(len(test_args)):
            try:
                result = iter_result.next(timeout)
            except multiprocessing.TimeoutError as e:
                result = {"time": timeout, "error": _format_exc(e)}
            except Exception as e:
                result = {"time": None, "error": _format_exc(e)}
            results.append(result)

        pool.close()
        pool.join()
        return results

    def run(self, name, kwargs):
        cls_name, method_name = name.split(".")
        cls = base.Scenario.get_by_name(cls_name)

        args = kwargs.get('args', {})
        timeout = kwargs.get('timeout', 10000)
        times = kwargs.get('times', 1)
        concurrent = kwargs.get('concurrent', 1)
        tenants = kwargs.get('tenants', 1)
        users_per_tenant = kwargs.get('users_per_tenant', 1)

        temp_users = self._create_temp_tenants_and_users(tenants,
                                                         users_per_tenant)

        # NOTE(msdubov): Call init() with admin openstack clients
        cls.clients = self.clients
        ctx = cls.init(kwargs.get('init', {}))

        # NOTE(msdubov): Launch scenarios with non-admin openstack clients
        global __openstack_clients__
        keys = ["username", "password", "tenant_name", "uri"]
        __openstack_clients__ = _create_openstack_clients(temp_users, keys)

        results = self._run_scenario(ctx, cls, method_name, args,
                                     times, concurrent, timeout)

        self._delete_temp_tenants_and_users()

        return results


def _run_test(test_args, ostf_config, queue):

    os.environ['CUSTOM_FUEL_CONFIG'] = ostf_config

    with utils.StdOutCapture() as out:
        status = pytest.main(test_args)

    queue.put({'msg': out.getvalue(), 'status': status,
               'proc_name': test_args[1]})


def _run_cleanup(config):

    os.environ['CUSTOM_FUEL_CONFIG'] = config
    fuel_cleanup.cleanup()


class Verifier(object):

    def __init__(self, task, cloud_config_path):
        self._cloud_config_path = os.path.abspath(cloud_config_path)
        self.task = task
        self._q = multiprocessing.Queue()

    @staticmethod
    def list_verification_tests():
        verification_tests_dict = {
            'sanity': ['--pyargs', 'fuel_health.tests.sanity'],
            'smoke': ['--pyargs', 'fuel_health.tests.smoke', '-k',
                      'not (test_007 or test_008 or test_009)'],
            'no_compute_sanity': ['--pyargs', 'fuel_health.tests.sanity',
                                  '-k', 'not infrastructure'],
            'no_compute_smoke': ['--pyargs', 'fuel_health.tests.smoke',
                                 '-k', 'user or flavor']
        }
        return verification_tests_dict

    def run_all(self, tests):
        """Launches all the given tests, trying to parameterize the tests
        using the test configuration.

        :param tests: Dictionary of form {'test_name': [test_args]}

        :returns: List of dicts, each dict containing the results of all
                  the run() method calls for the corresponding test
        """
        task_uuid = self.task['uuid']
        res = []
        for test_name in tests:
            res.append(self.run(tests[test_name]))
            LOG.debug(_('Task %s: Completed test `%s`.') %
                      (task_uuid, test_name))
        return res

    def run(self, test_args):
        """Launches a test (specified by pytest args).

        :param test_args: Arguments to be passed to pytest, e.g.
                          ['--pyargs', 'fuel_health.tests.sanity']

        :returns: Dict containing 'status', 'msg' and 'proc_name' fields
        """
        task_uuid = self.task['uuid']
        LOG.debug(_('Task %s: Running test: creating multiprocessing queue') %
                  task_uuid)

        test = multiprocessing.Process(target=_run_test,
                                       args=(test_args,
                                             self._cloud_config_path, self._q))
        test.start()
        test.join()
        result = self._q.get()
        if result['status'] and 'Timeout' in result['msg']:
            LOG.debug(_('Task %s: Test %s timed out.') %
                      (task_uuid, result['proc_name']))
        else:
            LOG.debug(_('Task %s: Process %s returned.') %
                      (task_uuid, result['proc_name']))
        self._cleanup()
        return result

    def _cleanup(self):
        cleanup = multiprocessing.Process(target=_run_cleanup,
                                          args=(self._cloud_config_path,))
        cleanup.start()
        cleanup.join()
        return
