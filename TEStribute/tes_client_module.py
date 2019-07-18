""" Contains all functions to interact with the TES Service
"""
from tes_client import Client


def fetch_tasks_info(
        tes_url, cpu_cores, ram_gb, disk_gb, execution_time_min, preemtible=True, zones=[]
        ):
    """
    :param tes_url: url path of the Task Execution Schema service
    :param cpu_cores: number of cores required by the task
    :param ram_gb:  ram in GB for the task
    :param disk_gb: disk space needed by the task in GB
    :param preemtible: True/False for if the task can be run on preemtible
    :param zones: an array of the zones the task can be run on
    :param execution_time_min: time in minutes needed for the execution of the task

    :return: a dict with associated costs & rates (in cases where cost is not computed by TES)
    """
    client = Client.Client(tes_url)
    response = client.GetTaskInfo(
        cpu_cores, ram_gb, disk_gb, preemtible, zones, execution_time_min
    )
    dict_response = response._as_dict()
    return dict_response
