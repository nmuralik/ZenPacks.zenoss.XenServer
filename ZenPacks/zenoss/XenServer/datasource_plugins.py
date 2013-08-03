##############################################################################
#
# Copyright (C) Zenoss, Inc. 2013, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

import logging
LOG = logging.getLogger('zen.XenServer')

import collections
import math

from cStringIO import StringIO
from lxml import etree

from twisted.internet.defer import inlineCallbacks, returnValue

from Products.ZenModel.MinMaxThreshold import rpneval

from ZenPacks.zenoss.PythonCollector.datasources.PythonDataSource import \
    PythonDataSourcePlugin

from ZenPacks.zenoss.XenServer.utils import add_local_lib_path

# Allows txxenapi to be imported.
add_local_lib_path()

import txxenapi


# Module stash for clients. Allows sharing authenticated sessions.
clients = {}


def get_client(addresses, username, password):
    '''
    Return a client. From the cache of existing clients if possible.
    '''
    client_key = (tuple(addresses), username, password)

    global clients
    if client_key not in clients:
        clients[client_key] = txxenapi.Client(
            addresses, username, password)

    return clients[client_key]


def iterparse(xml, tag):
    '''
    Generate elements with given tag in xml string.
    '''
    for _, element in etree.iterparse(StringIO(xml), tag=tag):
        yield element
        element.clear()


class XenServerXAPIDataSourcePlugin(PythonDataSourcePlugin):
    proxy_attributes = [
        'xenserver_addresses',
        'zXenServerUsername',
        'zXenServerPassword',
        ]

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            datasource.xapi_classname,
            )

    @classmethod
    def params(cls, datasource, context):
        return {
            'xapi_classname': datasource.talesEval(datasource.xapi_classname, context),
            'xapi_ref': datasource.talesEval(datasource.xapi_ref, context),
            }

    def collect(self, config):
        ds0 = config.datasources[0]

        client = get_client(
            ds0.xenserver_addresses,
            ds0.zXenServerUsername,
            ds0.zXenServerPassword)

        return client.xenapi[ds0.params['xapi_classname']].get_all_records()

    def onSuccess(self, results, config):
        # Create of map of ref to datasource.
        datasources = dict(
            (x.params['xapi_ref'], x) for x in config.datasources)

        data = self.new_data()

        for ref, properties in results.iteritems():
            datasource = datasources.get(ref)
            if not datasource:
                # We're not monitoring whatever this thing is. Skip it.
                continue

            points = dict((x.path, x) for x in datasource.points)

            for path, point in points.items():
                value = properties.get(path)

                if value is None:
                    continue

                if point.rpn:
                    try:
                        value = rpneval(value, point.rpn)
                    except Exception:
                        LOG.exception('Failed to evaluate RPN: %s', point.rpn)
                        continue

                data['values'][datasource.component][point.id] = (value, 'N')

                # Prune points so we know what's missing.
                del(points[path])

            if points:
                LOG.info(
                    "missing values for %s:%s:%s %s",
                    config.id,
                    datasource.component,
                    datasource.datasource,
                    points.keys())

            # Prune datasources so we know what's missing.
            del(datasources[ref])

        if datasources:
            LOG.info(
                "missing records for %s:%s %s",
                config.id,
                config.datasources[0].datasource,
                datasources.keys())

        data['events'].append({
            'eventClassKey': 'XAPICollectionSuccess',
            'eventKey': '|'.join(map(str, config.datasources[0].config_key)),
            'summary': 'XAPI: successful collection',
            'device': config.id,
            'severity': 0,
            })

        return data

    def onError(self, result, config):
        LOG.error(
            'error for %s %s: %s',
            config.id,
            config.datasources[0].datasource,
            result)

        data = self.new_data()
        data['events'].append({
            'eventClassKey': 'XAPICollectionError',
            'eventKey': '|'.join(map(str, config.datasources[0].config_key)),
            'summary': str(result),
            'device': config.id,
            'severity': 5,
        })

        return data


def aggregate_values(datapoint, columns):
    '''
    Return column values aggregated according to datapoint configuration.
    '''
    aggregate = {
        'AVERAGE': lambda x: sum(x) / len(x),
        'MAX': max,
        'MIN': min,
        'SUM': sum,
        }

    return aggregate[datapoint.params['group_aggregation']]([
        aggregate[datapoint.params['time_aggregation']](x) for x in columns])


class XenServerRRDDataSourcePlugin(PythonDataSourcePlugin):
    proxy_attributes = [
        'xenserver_addresses',
        'zXenServerUsername',
        'zXenServerPassword',
        ]

    @classmethod
    def config_key(cls, datasource, context):
        return (
            context.device().id,
            datasource.getCycleTime(context),
            )

    @classmethod
    def params(cls, datasource, context):
        if hasattr(context, 'xenrrd_prefix'):
            return {'prefix': context.xenrrd_prefix()}

        return {}

    @inlineCallbacks
    def collect(self, config):
        ds0 = config.datasources[0]

        client = get_client(
            ds0.xenserver_addresses,
            ds0.zXenServerUsername,
            ds0.zXenServerPassword)

        prefix_tree = collections.defaultdict(
            lambda: collections.defaultdict(
                lambda: collections.defaultdict(
                    list)))

        for datasource in config.datasources:
            prefix = datasource.params.get('prefix')
            if not prefix:
                continue

            for datapoint in datasource.points:
                datapoint.row_indexes = []
                prefix_tree[prefix[0]][prefix[1]][prefix[2]].append(datapoint)

        for address in ds0.xenserver_addresses:
            time_check_result = yield client.rrd_updates(address, start=1e11)

            for _, end in etree.iterparse(StringIO(time_check_result), tag='end'):
                server_time = end.text

            if not server_time:
                continue

            start = int(server_time) - ds0.cycletime - 5
            result = yield client.rrd_updates(address, start=start, host=True)

            row_data = collections.defaultdict(list)

            for _, element in etree.iterparse(StringIO(result)):
                if element.tag == 'meta':
                    step = int(element.findtext('step'))

                    if ds0.cycletime % step:
                        LOG.warn(
                            "%s:%s RRD interval (%s) not evenly divisible into datasource cycle (%s). Skipping collection",
                            config.id, address, step, ds0.cycletime)

                        continue

                    for i, entry in enumerate(element.iter('entry')):
                        etype, euuid, elabel = entry.text.split(':')[1:]

                        points = prefix_tree[etype][euuid]
                        for label_prefix, point in points.iteritems():
                            if elabel.startswith(label_prefix):
                                point.row_indexes.append(i)

                elif element.tag == 'row':
                    for i, v in enumerate(element.iter('v')):
                        try:
                            value = float(v.text)
                        except (TypeError, ValueError):
                            continue

                        if not math.isnan(value):
                            row_data[i].append(value)

            # Looping through all datasource and datapoints for each
            # host is sub-optimal, but it allows for continual
            # monitoring of virtual resource even when they've moved to
            # another host without our knowledge.

            for datasource in config.datasources:
                for datapoint in datasource.points:
                    if not datapoint.row_indexes:
                        continue

                    # Time aggregation.
                    if len(datapoint.row_indexes) == 1:
                        pass

                    # Time and group aggregation.
                    else:
                        pass

        data = self.new_data()
        returnValue(data)
