##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

'''
Unit test for all-things-Impact.
'''

import transaction

from zope.component import subscribers

from Products.Five import zcml

from Products.ZenTestCase.BaseTestCase import BaseTestCase
from Products.ZenUtils.guid.interfaces import IGUIDManager
from Products.ZenUtils.Utils import monkeypatch

from ZenPacks.zenoss.XenServer.tests.utils import (
    add_contained, add_noncontained,
    require_zenpack,
    )


@monkeypatch('Products.Zuul')
def get_dmd():
    '''
    Retrieve the DMD object. Handle unit test connection oddities.

    This has to be monkeypatched on Products.Zuul instead of
    Products.Zuul.utils because it's already imported into Products.Zuul
    by the time this monkeypatch happens.
    '''
    try:
        # original is injected by the monkeypatch decorator.
        return original()

    except AttributeError:
        connections = transaction.get()._synchronizers.data.values()[:]
        for cxn in connections:
            app = cxn.root()['Application']
            if hasattr(app, 'zport'):
                return app.zport.dmd


def impacts_for(thing):
    '''
    Return a two element tuple.

    First element is a list of object ids impacted by thing. Second element is
    a list of object ids impacting thing.
    '''
    from ZenPacks.zenoss.Impact.impactd.interfaces \
        import IRelationshipDataProvider

    impacted_by = []
    impacting = []

    guid_manager = IGUIDManager(thing.getDmd())
    for subscriber in subscribers([thing], IRelationshipDataProvider):
        for edge in subscriber.getEdges():
            source = guid_manager.getObject(edge.source)
            impacted = guid_manager.getObject(edge.impacted)
            if source.id == thing.id:
                impacted_by.append(impacted.id)
            elif impacted.id == thing.id:
                impacting.append(source.id)

    return (impacted_by, impacting)


def triggers_for(thing):
    '''
    Return a dictionary of triggers for thing.

    Returned dictionary keys will be triggerId of a Trigger instance and
    values will be the corresponding Trigger instance.
    '''
    from ZenPacks.zenoss.Impact.impactd.interfaces import INodeTriggers

    triggers = {}

    for sub in subscribers((thing,), INodeTriggers):
        for trigger in sub.get_triggers():
            triggers[trigger.triggerId] = trigger

    return triggers


def create_endpoint(dmd):
    '''
    Return an Endpoint suitable for Impact functional testing.
    '''
    # DeviceClass
    dc = dmd.Devices.createOrganizer('/XenServer')
    dc.setZenProperty('zPythonClass', 'ZenPacks.zenoss.XenServer.Endpoint')

    # Endpoint
    endpoint = dc.createInstance('endpoint')

    # Host
    from ZenPacks.zenoss.XenServer.Host import Host
    host1 = add_contained(endpoint, 'hosts', Host('host1'))

    from ZenPacks.zenoss.XenServer.PBD import PBD
    pbd1 = add_contained(host1, 'pbds', PBD('pbd1'))

    from ZenPacks.zenoss.XenServer.PIF import PIF
    pif1 = add_contained(host1, 'pifs', PIF('pif1'))

    # Storage
    from ZenPacks.zenoss.XenServer.SR import SR
    sr1 = add_contained(endpoint, 'srs', SR('sr1'))
    add_noncontained(sr1, 'pbds', pbd1)
    add_noncontained(sr1, 'suspend_image_for_hosts', host1)

    sr2 = add_contained(endpoint, 'srs', SR('sr2'))
    add_noncontained(sr2, 'crash_dump_for_hosts', host1)

    sr3 = add_contained(endpoint, 'srs', SR('sr3'))
    add_noncontained(sr3, 'local_cache_for_hosts', host1)

    from ZenPacks.zenoss.XenServer.VDI import VDI
    vdi1 = add_contained(sr1, 'vdis', VDI('vdi1'))

    # Network
    from ZenPacks.zenoss.XenServer.Network import Network
    network1 = add_contained(endpoint, 'networks', Network('network1'))
    add_noncontained(network1, 'pifs', pif1)

    # Pool
    from ZenPacks.zenoss.XenServer.Pool import Pool
    pool1 = add_contained(endpoint, 'pools', Pool('pool1'))
    add_noncontained(pool1, 'master', host1)
    add_noncontained(pool1, 'default_sr', sr1)
    add_noncontained(pool1, 'suspend_image_sr', sr2)
    add_noncontained(pool1, 'crash_dump_sr', sr3)

    # VM
    from ZenPacks.zenoss.XenServer.VM import VM
    vm1 = add_contained(endpoint, 'vms', VM('vm1'))
    add_noncontained(vm1, 'host', host1)

    from ZenPacks.zenoss.XenServer.VBD import VBD
    vbd1 = add_contained(vm1, 'vbds', VBD('vbd1'))
    add_noncontained(vbd1, 'vdi', vdi1)

    from ZenPacks.zenoss.XenServer.VIF import VIF
    vif1 = add_contained(vm1, 'vifs', VIF('vif1'))
    add_noncontained(vif1, 'network', network1)

    # vApp
    from ZenPacks.zenoss.XenServer.VMAppliance import VMAppliance
    vapp1 = add_contained(endpoint, 'vmappliances', VMAppliance('vapp1'))
    add_noncontained(vapp1, 'vms', vm1)

    return endpoint


class TestImpact(BaseTestCase):
    def afterSetUp(self):
        super(TestImpact, self).afterSetUp()

        import Products.ZenEvents
        zcml.load_config('meta.zcml', Products.ZenEvents)

        try:
            import ZenPacks.zenoss.DynamicView
            zcml.load_config('configure.zcml', ZenPacks.zenoss.DynamicView)
        except ImportError:
            return

        try:
            import ZenPacks.zenoss.Impact
            zcml.load_config('meta.zcml', ZenPacks.zenoss.Impact)
            zcml.load_config('configure.zcml', ZenPacks.zenoss.Impact)
        except ImportError:
            return

        import ZenPacks.zenoss.XenServer
        zcml.load_config('configure.zcml', ZenPacks.zenoss.XenServer)

    def endpoint(self):
        '''
        Return a XenServer endpoint device populated in a suitable way
        for Impact testing.
        '''
        if not hasattr(self, '_endpoint'):
            self._endpoint = create_endpoint(self.dmd)

        return self._endpoint

    def assertTriggersExist(self, triggers, expected_trigger_ids):
        '''
        Assert that each expected_trigger_id exists in triggers.
        '''
        for trigger_id in expected_trigger_ids:
            self.assertTrue(
                trigger_id in triggers, 'missing trigger: %s' % trigger_id)

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_Endpoint(self):
        endpoint = self.endpoint()

        impacts, impacted_by = impacts_for(endpoint)

        # Endpoint -> Host
        self.assertTrue(
            'host1' in impacts,
            'missing impact: {} <- {}'.format('host1', endpoint))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_Host(self):
        host1 = self.endpoint().getObjByPath('hosts/host1')

        impacts, impacted_by = impacts_for(host1)

        # Endpoint -> Host
        self.assertTrue(
            'endpoint' in impacted_by,
            'missing impact: {} -> {}'.format('endpoint', host1))

        # PBD -> Host
        self.assertTrue(
            'pbd1' in impacted_by,
            'missing impact: {} -> {}'.format('pbd1', host1))

        # SR -> Host
        self.assertTrue(
            'sr1' in impacted_by,
            'missing impact: {} -> {}'.format('sr1', host1))

        self.assertTrue(
            'sr2' in impacted_by,
            'missing impact: {} -> {}'.format('sr2', host1))

        self.assertTrue(
            'sr3' in impacted_by,
            'missing impact: {} -> {}'.format('sr3', host1))

        # PIF -> Host
        self.assertTrue(
            'pif1' in impacted_by,
            'missing impact: {} -> {}'.format('pif1', host1))

        # Host -> Pool
        self.assertTrue(
            'pool1' in impacts,
            'missing impact: {} <- {}'.format('pool1', host1))

        # Host -> VM
        self.assertTrue(
            'vm1' in impacts,
            'missing impact: {} <- {}'.format('vm1', host1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_Network(self):
        network1 = self.endpoint().getObjByPath('networks/network1')

        impacts, impacted_by = impacts_for(network1)

        # PIF -> Network
        self.assertTrue(
            'pif1' in impacted_by,
            'missing impact: {} -> {}'.format('pif1', network1))

        # Network -> VIF
        self.assertTrue(
            'vif1' in impacts,
            'missing impact: {} <- {}'.format('vif1', network1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_PBD(self):
        pbd1 = self.endpoint().getObjByPath('hosts/host1/pbds/pbd1')

        impacts, impacted_by = impacts_for(pbd1)

        # PBD -> SR
        self.assertTrue(
            'sr1' in impacts,
            'missing impact: {} <- {}'.format('sr1', pbd1))

        # PBD -> Host
        self.assertTrue(
            'host1' in impacts,
            'missing impact: {} <- {}'.format('host1', pbd1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_PIF(self):
        pif1 = self.endpoint().getObjByPath('hosts/host1/pifs/pif1')

        impacts, impacted_by = impacts_for(pif1)

        # PIF -> Network
        self.assertTrue(
            'network1' in impacts,
            'missing impact: {} <- {}'.format('network1', pif1))

        # PIF -> Host
        self.assertTrue(
            'host1' in impacts,
            'missing impact: {} <- {}'.format('host1', pif1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_Pool(self):
        pool1 = self.endpoint().getObjByPath('pools/pool1')

        impacts, impacted_by = impacts_for(pool1)

        # Host -> Pool
        self.assertTrue(
            'host1' in impacted_by,
            'missing impact: {} -> {}'.format('host1', pool1))

        # SR -> Pool
        self.assertTrue(
            'sr1' in impacted_by,
            'missing impact: {} -> {}'.format('sr1', pool1))

        self.assertTrue(
            'sr2' in impacted_by,
            'missing impact: {} -> {}'.format('sr2', pool1))

        self.assertTrue(
            'sr3' in impacted_by,
            'missing impact: {} -> {}'.format('sr3', pool1))

        # Pool -> VM
        self.assertTrue(
            'vm1' in impacts,
            'missing impact: {} <- {}'.format('vm1', pool1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_SR(self):
        sr1 = self.endpoint().getObjByPath('srs/sr1')
        sr2 = self.endpoint().getObjByPath('srs/sr2')
        sr3 = self.endpoint().getObjByPath('srs/sr3')

        sr1_impacts, sr1_impacted_by = impacts_for(sr1)
        sr2_impacts, sr2_impacted_by = impacts_for(sr2)
        sr3_impacts, sr3_impacted_by = impacts_for(sr3)

        # PBD -> SR
        self.assertTrue(
            'pbd1' in sr1_impacted_by,
            'missing impact: {} -> {}'.format('pbd1', sr1))

        # SR -> Host
        self.assertTrue(
            'host1' in sr1_impacts,
            'missing impacts: {} <- {}'.format('host1', sr1))

        self.assertTrue(
            'host1' in sr2_impacts,
            'missing impacts: {} <- {}'.format('host1', sr2))

        self.assertTrue(
            'host1' in sr3_impacts,
            'missing impacts: {} <- {}'.format('host1', sr3))

        # SR -> Pool
        self.assertTrue(
            'pool1' in sr1_impacts,
            'missing impacts: {} <- {}'.format('pool1', sr1))

        self.assertTrue(
            'pool1' in sr2_impacts,
            'missing impacts: {} <- {}'.format('pool1', sr2))

        self.assertTrue(
            'pool1' in sr3_impacts,
            'missing impacts: {} <- {}'.format('pool1', sr3))

        # SR -> VDI
        self.assertTrue(
            'vdi1' in sr1_impacts,
            'missing impacts: {} <- {}'.format('vdi1', sr1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_VBD(self):
        vbd1 = self.endpoint().getObjByPath('vms/vm1/vbds/vbd1')

        impacts, impacted_by = impacts_for(vbd1)

        # VDI -> VBD
        self.assertTrue(
            'vdi1' in impacted_by,
            'missing impact: {} -> {}'.format('vdi1', vbd1))

        # VBD -> VM
        self.assertTrue(
            'vm1' in impacts,
            'missing impact: {} <- {}'.format('vm1', vbd1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_VDI(self):
        vdi1 = self.endpoint().getObjByPath('srs/sr1/vdis/vdi1')

        impacts, impacted_by = impacts_for(vdi1)

        # SR -> VDI
        self.assertTrue(
            'sr1' in impacted_by,
            'missing impact: {} -> {}'.format('sr1', vdi1))

        # VDI -> VBD
        self.assertTrue(
            'vbd1' in impacts,
            'missing impact: {} <- {}'.format('vbd1', vdi1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_VIF(self):
        vif1 = self.endpoint().getObjByPath('vms/vm1/vifs/vif1')

        impacts, impacted_by = impacts_for(vif1)

        # Network -> VIF
        self.assertTrue(
            'network1' in impacted_by,
            'missing impact: {} -> {}'.format('network1', vif1))

        # VIF -> VM
        self.assertTrue(
            'vm1' in impacts,
            'missing impact: {} <- {}'.format('vm1', vif1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_VM(self):
        vm1 = self.endpoint().getObjByPath('vms/vm1')

        impacts, impacted_by = impacts_for(vm1)

        # Host -> VM
        self.assertTrue(
            'host1' in impacted_by,
            'missing impact: {} -> {}'.format('host1', vm1))

        # Pool -> VM
        self.assertTrue(
            'pool1' in impacted_by,
            'missing impact: {} -> {}'.format('pool1', vm1))

        # VBD -> VM
        self.assertTrue(
            'vbd1' in impacted_by,
            'missing impact: {} -> {}'.format('vbd1', vm1))

        # VIF -> VM
        self.assertTrue(
            'vif1' in impacted_by,
            'missing impact: {} -> {}'.format('vif1', vm1))

        # VM -> VMAppliance
        self.assertTrue(
            'vapp1' in impacts,
            'missing impact: {} <- {}'.format('vapp1', vm1))

    @require_zenpack('ZenPacks.zenoss.Impact')
    def test_VMAppliance(self):
        vapp1 = self.endpoint().getObjByPath('vmappliances/vapp1')

        impacts, impacted_by = impacts_for(vapp1)

        # VM -> VMAppliance
        self.assertTrue(
            'vm1' in impacted_by,
            'missing impact: {} -> {}'.format('vm1', vapp1))


def test_suite():
    from unittest import TestSuite, makeSuite
    suite = TestSuite()
    suite.addTest(makeSuite(TestImpact))
    return suite
