###########################################################################
#
# This program is part of Zenoss Core, an open source monitoring platform.
# Copyright (C) 2011, 2012 Zenoss Inc.
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License version 2 or (at your
# option) any later version as published by the Free Software Foundation.
#
# For complete information please visit: http://www.zenoss.com/oss/
#
###########################################################################

import logging
LOG = logging.getLogger('zen.XenServer')

from twisted.internet import defer
from twisted.internet.defer import DeferredList

from Products.DataCollector.plugins.CollectorPlugin import PythonPlugin
from Products.DataCollector.plugins.DataMaps import ObjectMap, RelationshipMap

from ZenPacks.zenoss.XenServer.utils import add_local_lib_path
from ZenPacks.zenoss.XenServer.lib import XenAPI

from pprint import pprint, pformat
add_local_lib_path()


def fetch_from_xen(sx):
    all_hosts = sx.host.get_all_records()
    all_host_cpus = sx.host_cpu.get_all_records()
    all_VMs = sx.VM.get_all_records()              # A dictionary of virtual machines
    all_VDIs = sx.VDI.get_all_records()              # A dictionary of virtual disk images
    all_VIFs = sx.VIF.get_all_records()              # A dictionary of virtual network interfaces
    all_PIFs = sx.PIF.get_all_records()              # A dictionary of virtual network interfaces
    all_SRs = sx.SR.get_all_records()              # A dictionary of virtual network interfaces
    
    real_VMs_keys = [ x for x in all_VMs if not all_VMs[x]['is_a_template'] and not all_VMs[x]['is_control_domain'] ]
    real_VMs = {}
    for i in real_VMs_keys:
        real_VMs[i] = all_VMs[i]

    for vm in real_VMs.values():
        del vm['last_booted_record']
    
    return {
        'VMs':      real_VMs, 
        'VDIs':     all_VDIs, 
        'VIFs':     all_VIFs,
        'PIFs':     all_PIFs,
        'hosts':    all_hosts,
        'host_cpus':    all_host_cpus,
        'SRs':      all_SRs,
    }


class XenServer(PythonPlugin):
    deviceProperties = PythonPlugin.deviceProperties + (
        'zXenServerHostname',
        'zXenServerUsername',
        'zXenServerPassword',
        'zXenServerSSL',
        )

    def collect(self, device, unused):
        LOG.info('*** Modeler %s collecting data for server %s', self.name(), device.id)

        if 1: # not hasattr(self, '_xenapi_session'):
            if not device.zXenServerUsername:
                LOG.error('zXenServerUsername is not set. Not discovering')
                return None

            if not device.zXenServerPassword:
                LOG.error('zXenServerPassword is not set. Not discovering')
                return None

            try:
                if device.zXenServerHostname:
                    session = XenAPI.Session(device.zXenServerHostname)
                else:
                    session = XenAPI.Session('http://%s' % device.manageIp)
            except:
                session = XenAPI.Session('http://%s' % device.manageIp)

            session.xenapi.login_with_password(device.zXenServerUsername, device.zXenServerPassword)
            self._xenapi_session = session

        LOG.info('*** Modeler %s collector fetching data for server %s', self.name(), device.id)
        fetch = fetch_from_xen(session.xenapi)
        LOG.info(pformat(fetch))

        LOG.info('*** Modeler %s collector launching deferred for server %s', self.name(), device.id)
        deferred = defer.Deferred()
        deferred.addCallback(self._combine)
        return deferred 

    def _combine(self):
        LOG.info('*** Modeler %s combining data for server %s', self.name(), device.id)
        return fetch


    def process(self, results):
        # See https://dev.zenoss.com/tracint/browser/trunk/enterprise/zenpacks/ZenPacks.zenoss.EMC.base/ZenPacks/zenoss/EMC/base/modeler/emc.py
        LOG.info('*** Modeler %s processing data for server %s', self.name(), device.id)

        maps = []
        return maps
