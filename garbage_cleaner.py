import boto3
import time
import datetime
from dateutil.parser import *
import manage_instances
import pytz

utc = pytz.UTC
CHECK_INTERVAL = 20


ec2_resources = boto3.resource('ec2')


def intiate():
	for instance in ec2_resources.instances.all():
		print(instance.id, instance.state)


def is_idle(instance_id):
	"""
	Evaluate if process is still running on the EC2 instance.
	:param instance_id: the ID of the EC2 instance to be checked for if idle.
	:return: a Boolean indicating whether idle or not
	"""
	# TODO: Use the 'push_command' module to probe EC2 instance whether it is idle i.e. still running
	raise NotImplementedError


def tag_idle_instances(instances):
	"""
	Adds a time stamp indicating the latest time the instance was observed idle.
	:param List instances to be tagged as idle:
	:return:
	"""
	if instances is None:
		return
	for i in range(len(instances)):
		if instances[i].state['Name'] in ['terminated', 'stopped']:
			continue
		if not is_idle(instances[i]):
			ec2_resources.create_tags(Resources=[instances[i].id], Tags=[{'Key': manage_instances.IDLE_TIME_KEY_TAG,
																		  'Value': str(datetime.datetime.now())}, ])


def get_tag_value(instance, key):
	"""
	Get the corresponding value to the key in the tags of an EC2 instance
	:param instance: The EC2 instance in question
	:param key: The key whose corresponding values is being search for.
	:return:
	"""
	if instance.tags is None:
		return None
	for tag in instance.tags:
		if tag['Key'] == key:
			return tag['Value']
	return None


def check_for_expired_instances(instances):
	"""
	Search from list of instances, those that are considered to be expired, i.e. considered to be idle for more
	than the maximum allowed idle time.
	:param instances:
	:return:
	"""
	if instances is None:
		return
	expired_instances = list()
	for instance in instances:
		if instance.state['Name'] == 'terminated':
			continue
		if instance.state['Name'] == 'stopped':
			expired_instances.append(instance)
			continue
		tag_datetime = parse(get_tag_value(instance, manage_instances.IDLE_TIME_KEY_TAG))  # get the last tagged time
		lt_datetime = instance.launch_time  # get lauch time of instance

		tag_datetime = utc.localize(tag_datetime)
		_datetime = max(lt_datetime, tag_datetime)  # get most recent

		lt_delta = utc.localize(datetime.datetime.now()) - _datetime

		uptime = lt_delta.total_seconds()

		# print(uptime)
		if uptime > manage_instances.MAX_LIFE_SPAN:
			print(instance.id)
			expired_instances.append(instance)

	return expired_instances


def garbage_cleaner_script():

	"""
	Daemon function that evaluates spunned ec2 server instances and tags them for cleaning up based on how
	 long they have been up for. This is determined by the 'MAX_LIFE_SPAN' variable
	:return:
	"""
	while True:
		instances = manage_instances.get_all_created_instances()
		tag_idle_instances(instances)
		# print('Check @ Time:', str(datetime.datetime.now()), '\n')
		expired_instances = check_for_expired_instances(instances)
		manage_instances.clean_up(expired_instances)
		if len(expired_instances) > 0:
			print('[' + str(datetime.datetime.now()) + '] Num. of instances to clean: ' + str(len(expired_instances)))
		time.sleep(CHECK_INTERVAL)


if __name__ == '__main__':
	garbage_cleaner_script()

