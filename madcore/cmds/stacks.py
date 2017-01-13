from __future__ import print_function, unicode_literals

from cliff.lister import Lister

from madcore.base import CloudFormationBase
from madcore.logs import logging


class Stacks(CloudFormationBase, Lister):
    _description = "List stacks"

    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        self.log.info('stack list')
        cf = self.get_aws_resource('cloudformation')
        return (('Name', 'Status', 'Creation Time', 'Last Updated Time'),
                ([(stack.name, stack.stack_status, stack.creation_time, stack.last_updated_time) for stack in
                  cf.stacks.all()])
                )