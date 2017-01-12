import os
import socket
import time


def config_path():
    return os.path.join(os.path.expanduser("~"), '.madcore')


def config_file_path():
    return os.path.join(config_path(), 'config')


def create_project_config_dir():
    cfg_path = config_path()
    if not os.path.exists(cfg_path):
        os.makedirs(cfg_path)


def hostname_resolves(hostname):
    sleep_time = 3
    max_time = 600
    count = 0

    while True:
        try:
            socket.gethostbyname(hostname)
            return True
        except socket.error:
            time.sleep(sleep_time)
            count += sleep_time
            if count > max_time:
                break
