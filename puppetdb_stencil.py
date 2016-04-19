#!/usr/bin/env python

"""
puppetdb-stencil is a tool to render puppet resources using templates.
"""

from __future__ import print_function
from __future__ import unicode_literals
import argparse
import logging
import sys
import os
import pypuppetdb
import jinja2


LOG = logging.getLogger('puppetdb_stencil')
METAPARAMS = ('require', 'before', 'subscribe', 'notify', 'audit', 'loglevel', 'noop', 'schedule', 'stage', 'alias', 'tag')
ALLOWED_METAPARAMS = ('alias')
NAMED_OBJECTS = ('host', 'hostgroup', 'servicegroup', 'servicedependency', 'contact', 'contactgroup', 'timeperiod', 'command')
# Allow templates from anywhere on the filesystem
LOADER = jinja2.FileSystemLoader(['.', '/'])
EXTENSIONS = ['jinja2.ext.with_', 'jinja2.ext.loopcontrols']
ENVIRONMENT = jinja2.Environment(trim_blocks=True, lstrip_blocks=True, loader=LOADER, extensions=EXTENSIONS)


def is_resource_visible(resource, localsite):
    return resource.exported and
        (('only-cross-site' not in resource.tags and 'no-cross-site' not in resource.tags) or
        ('only-cross-site' in resource.tags and 'no-cross-site' not in resource.tags and localsite == 'false') or
        ('only-cross-site' not in resource.tags and 'no-cross-site' in resource.tags and localsite == 'true'))


def render_resources(database, resource_type, localsite, template_names):
    """
    Render resources of the given type. They are queried from the given
    database and rendered using the first template from template_names that can
    be loaded.
    """
    # database.resources() is a generator, but we need to iterate it twice, so make a copy
    r = database.resources(resource_type)
    resources = []
    try:
        template = ENVIRONMENT.select_template(template_names)
    except jinja2.TemplatesNotFound:
        LOG.error('No template found for {0}'.format(resource_type))
    else:
        icinga_config = ''
        object_name = resource_type[7:]
        named_object = object_name in NAMED_OBJECTS
        service_dependencies = {}
        for resource in r:
            resources.append(resource)
            envs_to_ignore = []
            if is_resource_visible(resource, localsite):
                dto = {}
                dto['object_name'] = object_name
                dto['named_object'] = named_object
                dto['name'] = resource.name
                dto['parameters'] = []
                # capture resource parameters from puppet
                for key, value in resource.parameters.items():
                    if (key not in METAPARAMS or key in ALLOWED_METAPARAMS) and (isinstance(value, list)):
                        dto['parameters'].append({key: ','.join(value)})
                    else:
                        dto['parameters'].append({key: value})
                    envs_to_ignore.append((object_name + '_' + key).upper())
                # capture environment variable defaults
                for name in os.environ:
                    nameparts = name.split('_')
                    if nameparts[0].lower() == object_name and name not in envs_to_ignore:
                        dto['parameters'].append({'_'.join(nameparts[1:]).lower(): os.environ[name].lower()})
                icinga_config += template.render(dto=dto) + '\n'
            # collect child service dependencies under parent service_description
            for tag in resource.tags:
                if 'parent:' in tag:
                    parent_service_description_list = tag.split(':')
                    if len(parent_service_description_list) == 2:
                        parent_service_description = parent_service_description_list[1]
                        if parent_service_description not in service_dependencies:
                            service_dependencies[parent_service_description] = []
                        service_dependencies[parent_service_description].append(resource)
        # render service dependencies
        if len(service_dependencies) > 0:
            for item in service_dependencies:
                parent_service_description = item.replace('_', ' ')
                # lookup parent resource by its service_description
                for parent in resources:
                    if is_resource_visible(resource, localsite):
                        for key, value in parent.parameters.items():
                            if key == 'service_description' and parent_service_description in value.lower():
                                for child in service_dependencies[item]:
                                    dto = {}
                                    dto['object_name'] = 'servicedependency'
                                    dto['parameters'] = [{
                                        'host_name': parent.parameters['host_name'],
                                        'service_description': parent.parameters['service_description'],
                                        'dependent_host_name': child.parameters['host_name'],
                                        'dependent_service_description': child.parameters['service_description']
                                    }]
                                    icinga_config += template.render(dto=dto) + '\n'
        return icinga_config


def main():
    """
    Main function
    """
    parser = argparse.ArgumentParser(prog='puppetdb_stencil')
    parser.add_argument('resource_types', metavar='RESOURCE_TYPE', nargs='+')
    parser.add_argument('--templates', '-t', metavar='TEMPLATE', nargs='*')
    parser.add_argument('--debug', '-d', action='store_true')
    parser.add_argument('--host', '-H', default='localhost')
    parser.add_argument('--port', '-p', default='8080')
    parser.add_argument('--localsite', '-l', default='true')
    args = parser.parse_args()
    logging.basicConfig(level=logging.DEBUG if args.debug else logging.WARN)
    database = pypuppetdb.connect(host=args.host, port=args.port)
    for resource_type in args.resource_types:
        templates = ['{0}.jinja2'.format(resource_type)]
        if args.templates:
            templates += args.templates
        print(render_resources(database, resource_type, args.localsite, templates))


if __name__ == '__main__':
    main()
sys.exit(0)

