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

"""Tests for utils."""
import mock
import multiprocessing

from rally.benchmark import runner
from rally import test
from tests import fakes


class MockedPool(object):

    def __init__(self, concurrent=1):
        pass

    def close(self):
        pass

    def join(self):
        pass

    def apply_async(self, func, args=()):
        func(*args)


class ScenarioTestCase(test.TestCase):

    def setUp(self):
        super(ScenarioTestCase, self).setUp()
        admin_keys = ["admin_username", "admin_password",
                      "admin_tenant_name", "uri"]
        self.fake_kw = dict(zip(admin_keys, admin_keys))

    def test_init_calls_register(self):
        with mock.patch("rally.benchmark.utils.osclients") as mock_osclients:
            mock_osclients.Clients.return_value = fakes.FakeClients()
            with mock.patch("rally.benchmark.runner.base") as mock_base:
                runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
            self.assertEqual(mock_base.mock_calls,
                             [mock.call.Scenario.register()])

    def test_create_temp_tenants_and_users(self):
        with mock.patch("rally.benchmark.utils.osclients") as mock_osclients:
            mock_osclients.Clients.return_value = fakes.FakeClients()
            srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
            tenants = 10
            users_per_tenant = 5
            endpoints = srunner._create_temp_tenants_and_users(
                                                    tenants, users_per_tenant)
            self.assertEqual(len(endpoints), tenants * users_per_tenant)
            endpoint_keys = set(["username", "password", "tenant_name",
                                 "uri"])
            for endpoint in endpoints:
                self.assertTrue(endpoint_keys.issubset(endpoint.keys()))

    def test_run_scenario(self):
        with mock.patch("rally.benchmark.utils.osclients") as mock_osclients:
            mock_osclients.Clients.return_value = fakes.FakeClients()
            with mock.patch("rally.benchmark.runner.rutils") as mock_utils:
                srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
                runner.__openstack_clients__ = ["client"]
                active_users = 2
                times = 3
                duration = 0.01

                mock_utils.Timer = fakes.FakeTimer
                results = srunner._run_scenario(fakes.FakeScenario,
                                                "do_it", {}, "continuous",
                                                {"times": times,
                                                 "active_users": active_users,
                                                 "timeout": 2})
                expected = [{"time": 10, "idle_time": 0, "error": None,
                             "scenario_output": None}
                            for i in range(times)]
                self.assertEqual(results, expected)

                results = srunner._run_scenario(fakes.FakeScenario,
                                                "do_it", {}, "continuous",
                                                {"duration": duration,
                                                 "active_users": active_users,
                                                 "timeout": 2})
                expected = [{"time": 10, "idle_time": 0, "error": None,
                             "scenario_output": None}
                            for i in range(active_users)]
                self.assertEqual(results, expected)

    @mock.patch("rally.benchmark.utils.osclients")
    @mock.patch("multiprocessing.pool.IMapIterator.next")
    @mock.patch("rally.benchmark.runner.time.time")
    @mock.patch("rally.benchmark.utils._prepare_for_instance_ssh")
    def test_run_scenario_timeout(self, mock_prepare_for_instance_ssh,
                                  mock_time, mock_next, mock_osclients):

        mock_time.side_effect = [1, 2, 3, 10]
        mock_next.side_effect = multiprocessing.TimeoutError()
        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        runner.__openstack_clients__ = ["client"]
        times = 4
        active_users = 2
        results = srunner._run_scenario(fakes.FakeScenario,
                                        "too_long", {}, "continuous",
                                        {"times": times,
                                         "active_users": active_users,
                                         "timeout": 0.01})
        self.assertEqual(len(results), times)
        for r in results:
            self.assertEqual(r['time'], 0.01)
            self.assertEqual(r['error'][0],
                             str(multiprocessing.TimeoutError))

        duration = 0.1
        results = srunner._run_scenario(fakes.FakeScenario,
                                        "too_long", {}, "continuous",
                                        {"duration": duration,
                                         "active_users": active_users,
                                         "timeout": 0.01})
        self.assertEqual(len(results), active_users)
        for r in results:
            self.assertEqual(r['time'], 0.01)
            self.assertEqual(r['error'][0],
                             str(multiprocessing.TimeoutError))

    def test_run_scenario_exception_inside_test(self):
        with mock.patch("rally.benchmark.utils.osclients") as mock_osclients:
            mock_osclients.Clients.return_value = fakes.FakeClients()
            srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
            runner.__openstack_clients__ = ["client"]
            times = 1
            duration = 0.01
            active_users = 2
            with mock.patch("rally.benchmark.runner.rutils") as mock_utils:
                mock_utils.Timer = fakes.FakeTimer
                results = srunner._run_scenario(fakes.FakeScenario,
                                                "something_went_wrong", {},
                                                "continuous",
                                                {"times": times,
                                                 "active_users": active_users,
                                                 "timeout": 1})
                self.assertEqual(len(results), times)
                for r in results:
                    self.assertEqual(r['time'], 10)
                    self.assertEqual(r['error'][:2],
                                     [str(Exception), "Something went wrong"])

                results = srunner._run_scenario(fakes.FakeScenario,
                                                "something_went_wrong", {},
                                                "continuous",
                                                {"duration": duration,
                                                 "active_users": active_users,
                                                 "timeout": 1})
                self.assertEqual(len(results), active_users)
                for r in results:
                    self.assertEqual(r['time'], 10)
                    self.assertEqual(r['error'][:2],
                                     [str(Exception), "Something went wrong"])

    def test_run_scenario_exception_outside_test(self):
        pass

    @mock.patch("rally.benchmark.runner.multiprocessing")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run_scenario_continuously_for_times(self, mock_osclients,
                                                 mock_multi):
        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        runner.__openstack_clients__ = ["client"]
        times = 3
        active_users = 4
        timeout = 5
        mock_multi.Pool = mock.MagicMock()
        srunner._run_scenario_continuously_for_times(fakes.FakeScenario,
                                                     "do_it", {},
                                                     times, active_users,
                                                     timeout)
        expect = [
            mock.call(active_users),
            mock.call().imap(
                runner._run_scenario_loop,
                [(i, fakes.FakeScenario, "do_it", {})
                    for i in xrange(times)]
            )
        ]
        expect.extend([mock.call().imap().next(timeout) for i in range(times)])
        expect.extend([
            mock.call().close(),
            mock.call().join()
        ])
        self.assertEqual(mock_multi.Pool.mock_calls, expect)

    @mock.patch("rally.benchmark.utils.infinite_run_args")
    @mock.patch("rally.benchmark.runner.multiprocessing")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run_scenario_continuously_for_duration(self, mock_osclients,
                                                    mock_multi, mock_generate):
        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        runner.__openstack_clients__ = ["client"]
        duration = 0
        active_users = 4
        timeout = 5
        mock_multi.Pool = mock.MagicMock()
        mock_generate.return_value = {}
        srunner._run_scenario_continuously_for_duration(fakes.FakeScenario,
                                                        "do_it", {}, duration,
                                                        active_users, timeout)
        expect = [
            mock.call(active_users),
            mock.call().imap(runner._run_scenario_loop, {}),
            mock.call().terminate(),
            mock.call().join()
        ]
        self.assertEqual(mock_multi.Pool.mock_calls, expect)

    @mock.patch("rally.benchmark.runner._run_scenario_loop")
    @mock.patch("rally.benchmark.runner.time.sleep")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run_scenario_periodically(self, mock_osclients,
                                       mock_sleep, mock_run_scenario_loop):
        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        runner.__openstack_clients__ = ["client"]
        times = 3
        period = 4
        timeout = 5
        srunner._run_scenario_periodically(fakes.FakeScenario, "do_it", {},
                                           times, period, timeout)

        expected = [mock.call((i, fakes.FakeScenario, "do_it", {}))
                    for i in xrange(times)]
        self.assertEqual(mock_run_scenario_loop.mock_calls, expected)

        expected = [mock.call(period * 60) for i in xrange(times - 1)]
        mock_sleep.has_calls(expected)

    @mock.patch("rally.benchmark.runner.base")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run_continuous(self, mock_osclients, mock_base):
        FakeScenario = mock.MagicMock()
        FakeScenario.init = mock.MagicMock(return_value={})

        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        srunner._run_scenario_continuously_for_times = \
            mock.MagicMock(return_value="result")
        srunner._run_scenario_continuously_for_duration = \
            mock.MagicMock(return_value="result")
        srunner._create_temp_tenants_and_users = mock.MagicMock(
                                                            return_value=[])
        srunner._delete_temp_tenants_and_users = mock.MagicMock()

        mock_base.Scenario.get_by_name = \
            mock.MagicMock(return_value=FakeScenario)
        mock_osclients.return_value = ["client"]
        result = srunner._run_scenario(FakeScenario, "do_it", {"a": 1},
                                       "continuous", {"times": 2,
                                                      "active_users": 3,
                                                      "timeout": 1})
        self.assertEqual(result, "result")
        srunner._run_scenario_continuously_for_times.assert_called_once_with(
                                    FakeScenario, "do_it", {"a": 1}, 2, 3, 1)
        result = srunner._run_scenario(FakeScenario, "do_it", {"a": 1},
                                       "continuous", {"duration": 2,
                                                      "active_users": 3,
                                                      "timeout": 1})
        self.assertEqual(result, "result")
        srunner._run_scenario_continuously_for_duration.\
            assert_called_once_with(FakeScenario, "do_it", {"a": 1}, 2, 3, 1)

    @mock.patch("rally.benchmark.runner.base")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run_periodic(self, mock_osclients, mock_base):
        FakeScenario = mock.MagicMock()
        FakeScenario.init = mock.MagicMock(return_value={})

        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        srunner._run_scenario_periodically = mock.MagicMock(
                                                        return_value="result")
        srunner._create_temp_tenants_and_users = mock.MagicMock(
                                                            return_value=[])
        srunner._delete_temp_tenants_and_users = mock.MagicMock()

        mock_base.Scenario.get_by_name = \
            mock.MagicMock(return_value=FakeScenario)
        mock_osclients.return_value = ["client"]
        result = srunner._run_scenario(FakeScenario, "do_it", {"a": 1},
                                       "periodic", {"times": 2, "period": 3,
                                                    "timeout": 1})
        self.assertEqual(result, "result")
        srunner._run_scenario_periodically.assert_called_once_with(
                                    FakeScenario, "do_it", {"a": 1}, 2, 3, 1)

    @mock.patch("rally.benchmark.utils.create_openstack_clients")
    @mock.patch("rally.benchmark.runner.base")
    @mock.patch("rally.benchmark.utils.osclients")
    def test_run(self, mock_osclients, mock_base, mock_clients):
        FakeScenario = mock.MagicMock()
        FakeScenario.init = mock.MagicMock(return_value={})

        mock_osclients.Clients.return_value = fakes.FakeClients()
        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        srunner._run_scenario = mock.MagicMock(return_value="result")
        srunner._create_temp_tenants_and_users = mock.MagicMock(
                                                        return_value=[])
        srunner._delete_temp_tenants_and_users = mock.MagicMock()

        mock_base.Scenario.get_by_name = \
            mock.MagicMock(return_value=FakeScenario)
        result = srunner.run("FakeScenario.do_it", {})
        self.assertEqual(result, "result")
        srunner.run("FakeScenario.do_it",
                    {"args": {"a": 1}, "init": {"arg": 1},
                     "config": {"timeout": 1, "times": 2, "active_users": 3,
                                "tenants": 5, "users_per_tenant": 2}})
        srunner.run("FakeScenario.do_it",
                    {"args": {"a": 1}, "init": {"fake": "arg"},
                     "execution_type": "continuous",
                     "config": {"timeout": 1, "duration": 40,
                                "active_users": 3, "tenants": 5,
                                "users_per_tenant": 2}})

        expected = [
            mock.call(FakeScenario, "do_it", {}, "continuous", {}),
            mock.call(FakeScenario, "do_it", {"a": 1}, "continuous",
                      {"timeout": 1, "times": 2, "active_users": 3,
                       "tenants": 5, "users_per_tenant": 2}),
            mock.call(FakeScenario, "do_it", {"a": 1}, "continuous",
                      {"timeout": 1, "duration": 40, "active_users": 3,
                       "tenants": 5, "users_per_tenant": 2})
        ]
        self.assertEqual(srunner._run_scenario.mock_calls, expected)

        expected = [
            mock.call(1, 1),
            mock.call(5, 2),
            mock.call(5, 2)
        ]
        self.assertEqual(srunner._create_temp_tenants_and_users.mock_calls,
                         expected)

        expected = [
            mock.call.init({}),
            mock.call.init({"arg": 1}),
            mock.call.init({"fake": "arg"}),
        ]
        self.assertEqual(FakeScenario.mock_calls, expected)

    @mock.patch("rally.benchmark.utils.create_openstack_clients")
    @mock.patch("rally.benchmark.runner.base")
    @mock.patch("rally.benchmark.utils.osclients")
    @mock.patch("rally.benchmark.utils.delete_keystone_resources")
    @mock.patch("multiprocessing.Pool")
    def test_generic_cleanup(self, mock_pool, mock_del_keystone_res,
                             mock_osclients, mock_base, mock_clients):
        FakeScenario = mock.MagicMock()
        FakeScenario.init = mock.MagicMock(return_value={})

        mock_cms = [fakes.FakeClients(), fakes.FakeClients(),
                    fakes.FakeClients()]
        clients = [
            dict((
                ("nova", cl.get_nova_client()),
                ("keystone", cl.get_keystone_client()),
                ("glance", cl.get_glance_client()),
                ("cinder", cl.get_cinder_client())
            )) for cl in mock_cms
        ]
        mock_clients.return_value = clients

        srunner = runner.ScenarioRunner(mock.MagicMock(), self.fake_kw)
        srunner._run_scenario = mock.MagicMock(return_value="result")
        srunner._create_temp_tenants_and_users = mock.MagicMock(
                                                        return_value=[])
        srunner._delete_temp_tenants_and_users = mock.MagicMock()

        mock_base.Scenario.get_by_name = \
            mock.MagicMock(return_value=FakeScenario)

        for index in range(len(clients)):
            client = clients[index]
            nova = client["nova"]
            cinder = client["cinder"]
            for count in range(3):
                uid = index + count
                img = nova.images.create()
                nova.servers.create("svr-%s" % (uid), img.uuid, index)
                nova.keypairs.create("keypair-%s" % (uid))
                nova.security_groups.create("secgroup-%s" % (uid))
                nova.networks.create("net-%s" % (uid))
                cinder.volumes.create("vol-%s" % (uid))
                cinder.volume_types.create("voltype-%s" % (uid))
                cinder.transfers.create("voltransfer-%s" % (uid))
                cinder.volume_snapshots.create("snap-%s" % (uid))
                cinder.backups.create("backup-%s" % (uid))

        mock_pool.return_value = MockedPool()

        srunner.run("FakeScenario.do_it",
                    {"args": {"a": 1}, "init": {"arg": 1},
                     "config": {"timeout": 1, "times": 2, "active_users": 3,
                                "tenants": 5, "users_per_tenant": 2}})

        def _assert_purged(manager, resource_type):
            resources = manager.list()
            self.assertEqual([], resources, "%s not purged: %s" %
                             (resource_type, resources))

        for client in clients:
            nova = client["nova"]
            cinder = client["cinder"]
            _assert_purged(nova.servers, "servers")
            _assert_purged(nova.keypairs, "key pairs")
            _assert_purged(nova.security_groups, "security groups")
            _assert_purged(nova.networks, "networks")

            _assert_purged(cinder.volumes, "volumes")
            _assert_purged(cinder.volume_types, "volume types")
            _assert_purged(cinder.backups, "volume backups")
            _assert_purged(cinder.transfers, "volume transfers")
            _assert_purged(cinder.volume_snapshots, "volume snapshots")

            for image in nova.images.list():
                self.assertEqual("DELETED", image.status,
                                 "image not purged: %s" % (image))

        expected = [mock.call(clients[0]["keystone"], resource) for resource in
                    ["users", "tenants", "services", "roles"]]

        self.assertEqual(mock_del_keystone_res.mock_calls, expected)
