from __future__ import print_function, unicode_literals

import os
import time

import boto3
import requests
import urllib3
from botocore.exceptions import ClientError
from jenkins import Jenkins

import const
import utils
from configs import config
from libs.figlet import figlet
from logs import logging
from jenkins import JenkinsException


class MadcoreBase(object):
    log = logging.getLogger(__name__)
    log_simple = logging.getLogger('no_formatter')

    def __init__(self, *args, **kwargs):
        super(MadcoreBase, self).__init__(*args, **kwargs)

    @property
    def config_path(self):
        return utils.config_path()

    def get_template_local(self, template_file):
        with open(os.path.join(self.config_path, 'cloudformation', template_file)) as content_file:
            content = content_file.read()
        return content

    @classmethod
    def get_ipv4(cls):
        http = urllib3.PoolManager()
        r = http.request('GET', 'http://ipv4.icanhazip.com/')
        if r.status is not 200:
            raise RuntimeError('No Internet')
        return r.data.strip()
        # return '8.8.8.8'

    @classmethod
    def list_diff(cls, l1, l2):
        return [x for x in l1 if x not in l2]

    def get_allowed_domains(self, url=None):
        try:
            url = url or 'https://raw.githubusercontent.com/madcore-ai/plugins/master/domain-index.json'
            return requests.get(url).json()
        except Exception:
            self.log.error("Error downloading domain from: '%s'" % url)

    def log_piglet(self, msg):
        self.log_simple.info(figlet.renderText(msg))


class CloudFormationBase(MadcoreBase):
    def __init__(self, *args, **kwargs):
        super(CloudFormationBase, self).__init__(*args, **kwargs)
        self.session = None
        self.cf_client = None

        self.create_aws_objects()

    def get_aws_client(self, name, **kwargs):
        params = self.get_aws_connection_params.copy()
        params.update(kwargs)
        return boto3.client(name, **params)

    def get_aws_resource(self, name, **kwargs):
        params = self.get_aws_connection_params.copy()
        params.update(kwargs)
        return boto3.resource(name, **params)

    @property
    def get_aws_connection_params(self):
        region_name = config.get_aws_data('region_name')

        params = {}
        if region_name:
            params['region_name'] = region_name

        return params

    def create_aws_objects(self):
        self.session = boto3.Session(**self.get_aws_connection_params)
        self.cf_client = self.session.client('cloudformation')

    @classmethod
    def stack_name(cls, stack_short_name):
        """Given the short stack name, like s3, network, core, output the proper name"""

        return const.STACK_SHORT_NAMES[stack_short_name]

    def get_stack(self, stack_name, debug=True):
        try:
            r = self.cf_client.describe_stacks(
                StackName=stack_name
            )
            return r['Stacks'][0]
        except ClientError as e:
            if debug:
                self.log.error(e)
        except Exception as e:
            if debug:
                self.log.error(e)

        return None

    def get_stack_by_short_name(self, stack_short_name):
        return self.get_stack(self.stack_name(stack_short_name))

    @classmethod
    def get_param_from_dict(cls, dic, param):
        return next(i for i in dic if i['ParameterKey'] == param)['ParameterValue']

    @classmethod
    def get_output_from_dict(cls, dic, param):
        return next(i for i in dic if i['OutputKey'] == param)['OutputValue']

    @classmethod
    def maintain_loop(cls, response, last_event_id, event_type):
        events = sorted(response['StackEvents'], key=lambda x: x['Timestamp'], reverse=True)
        event = events[0]
        # this can be one of: update, create
        event_type = event_type.upper()

        if (event['EventId'] != last_event_id) and \
                (event['ResourceType'] == 'AWS::CloudFormation::Stack') and \
                (event['ResourceStatus'] in ['%s_COMPLETE' % event_type, '%s_ROLLBACK_COMPLETE' % event_type,
                                             'ROLLBACK_COMPLETE']):
            return False

        return True

    def show_stack_events_progress(self, stack_name, event_type, wait_seconds=3):
        try:
            response_events = self.cf_client.describe_stack_events(
                StackName=stack_name
            )
        except ClientError as e:
            self.log.error(e)
            return

        shown_events = []

        # Kinda a hack to not show old stuff
        for event in response_events['StackEvents']:
            if event['EventId'] not in shown_events:
                shown_events.append(event['EventId'])

        last_event_id = response_events['StackEvents'][0]['EventId']

        # TODO@geo Maybe we should investigate and see if we can create this table using PrettyTable?
        # Display top of updates stream
        self.app.stdout.write("{: <45} {: <23} {: <}".format("Resource", "Status", "Details"))

        # Steam updates until we hit a closing case
        while self.maintain_loop(response_events, last_event_id, event_type):
            time.sleep(wait_seconds)
            try:
                response_events = self.cf_client.describe_stack_events(
                    StackName=stack_name,
                )
            except ClientError:
                # we reach a point when we try to describe the stack events but is already deleted
                break

            events = sorted(response_events['StackEvents'], key=lambda x: x['Timestamp'])

            for event in events:
                if event['EventId'] not in shown_events:

                    if 'ResourceStatusReason' not in event:
                        event['ResourceStatusReason'] = ""

                    self.app.stdout.write("{: <40} {: <30} {: <}".format(event['ResourceType'],
                                                                         event['ResourceStatus'],
                                                                         event['ResourceStatusReason']))
                    shown_events.append(event['EventId'])

    def show_stack_create_events_progress(self, stack_name, **kwargs):
        self.show_stack_events_progress(stack_name, 'create', **kwargs)

    def show_stack_update_events_progress(self, stack_name, **kwargs):
        self.show_stack_events_progress(stack_name, 'update', **kwargs)

    def show_stack_delete_events_progress(self, stack_name, **kwargs):
        self.show_stack_events_progress(stack_name, 'delete', **kwargs)

    def get_core_public_ip(self):
        dns_stack = self.get_stack(const.STACK_CORE)
        return self.get_output_from_dict(dns_stack['Outputs'], 'MadCorePublicIp')


class JenkinsBase(CloudFormationBase, MadcoreBase):
    def __init__(self, *args, **kwargs):
        super(JenkinsBase, self).__init__(*args, **kwargs)

    @property
    def jenkins_endpoint(self):
        return 'https://jenkins.%s' % config.get_full_domain()

    def show_job_console_output(self, jenkins_server, job_name, build_number, sleep_time=1):
        self.log.info("Get console output for job: '%s'\n", job_name)
        output_lines = []

        # wait until job is is started to get the output
        while True:
            job_info = jenkins_server.get_job_info(job_name, depth=1)

            if job_info['builds'] and job_info['builds'][0]['building']:
                self.log.debug("Job removed from queue, start processing")
                break
            time.sleep(1)

        while True:
            output = jenkins_server.get_build_console_output(job_name, build_number)
            new_output = output.split(os.linesep)

            output_diff = self.list_diff(new_output, output_lines)

            job_info = jenkins_server.get_job_info(job_name, depth=1)
            if not output_diff and not job_info['builds'][0]['building']:
                break

            output_lines = new_output
            # only display if there are new lines
            if output_diff:
                for line in output_diff:
                    self.log.info(line.strip())

            time.sleep(sleep_time)

    def create_jenkins_server(self):
        return Jenkins(self.jenkins_endpoint)

    def jenkins_run_job_show_output(self, job_name, parameters=None, sleep_time=1, retry_times=3):
        """We are retrying this method because there may be cases when jenkins gives an error when making API calls"""

        while True:
            retry_time = 0

            try:
                jenkins_server = self.create_jenkins_server()
                job_info = jenkins_server.get_job_info(job_name, depth=1)

                build_number = job_info['nextBuildNumber']

                if job_info['builds'] and job_info['builds'][0]['building']:
                    # current job is already building, get it's number
                    build_number = job_info['builds'][0]['number']
                    self.log.info("Job '%s' already running." % job_name)
                else:
                    # start the job
                    jenkins_server.build_job(job_name, parameters=parameters)
                    self.log.info("Build job '%s'.", job_name)

                self.show_job_console_output(jenkins_server, job_name, build_number, sleep_time=sleep_time)

                # get the job SUCCESS status
                job_info = jenkins_server.get_job_info(job_name, depth=1)

                return job_info['lastBuild']['result'] in ['SUCCESS']
            except JenkinsException as e:
                retry_time += 1
                if retry_time > retry_times:
                    break
                self.log.error(e)
                self.log.info("Retry: %s", retry_time)

    def wait_until_jenkins_is_up(self, verify=False):
        max_sleep = 60 * 10
        elapsed_sec = 0
        sleep_time = 10

        while True:
            try:
                response = requests.get(self.jenkins_endpoint, verify=verify)
                response.raise_for_status()
                return True
            except:
                elapsed_sec += sleep_time
                if elapsed_sec > max_sleep:
                    break
                time.sleep(sleep_time)

        return False


class Stdout(object):
    log = logging.getLogger('no_formatter')

    def write(self, msg):
        self.log.info(msg)