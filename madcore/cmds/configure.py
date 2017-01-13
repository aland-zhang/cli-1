from __future__ import print_function, unicode_literals

import ssl
import sys

from cliff.lister import Lister

from madcore.base import JenkinsBase
from madcore.cmds.selftest import SelfTest
from madcore.configs import config
from madcore.configure import MadcoreConfigure
from madcore.const import DOMAIN_REGISTRATION
from madcore.libs.cloudformation import StackCreate
from madcore.logs import logging


class Configure(JenkinsBase, Lister):
    _description = "Configure madcore"
    log = logging.getLogger(__name__)

    def take_action(self, parsed_args):
        # TODO#geo this is a hack to skip ssl verification when we do jenkins registration
        ssl._create_default_https_context = ssl._create_unverified_context

        configure = MadcoreConfigure()
        config_results = configure.start_configuration()

        self.log_piglet("Create Stacks")
        stack_create = StackCreate(self.app)
        stack_create.take_action(parsed_args)
        self.log_piglet("Done")

        self.log_piglet("Wait until Jenkins is up")
        if self.wait_until_jenkins_is_up():
            self.log.info("Jenkins is up, continue.")
        else:
            self.log.error("Error while waiting for jenkins. EXIT.")
            sys.exit(1)
        self.log_piglet("Done")

        self.log_piglet("Start domain registration")
        if not config.is_domain_registered:
            self.log.info("Start domain registration.")

            job_name = 'madcore.registration'
            parameters = DOMAIN_REGISTRATION.copy()
            parameters['Hostname'] = config.get_full_domain()
            parameters['Email'] = config.get_user_data('email')

            success = self.jenkins_run_job_show_output(job_name, parameters=parameters)

            if success:
                self.log.info("Successfully run job '%s'.", job_name)
                config.set_user_data({"registration": True})
            else:
                self.log.error("Error while executing job '%s'.", job_name)
                config.set_user_data({"registration": False})
        else:
            self.log.info("Domain already registered.")
        self.log_piglet("Done")

        self.log_piglet("Run selftests")
        selftest = SelfTest(self.app, self.app_args)
        selftest.take_action(parsed_args)
        self.log_piglet("Done")

        return config_results