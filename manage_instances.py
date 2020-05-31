import boto3
import time
import datetime
from dateutil.parser import *
import re

TAG_KEY = 'auto'  # used to distinguished EC2 instances that were created using this library
MAX_LIFE_SPAN = 240  # 4 minutes
INSTANCE_TYPE = 't2.xlarge'  # Specify the instance type
MAX_STOPPED = 0  # Maximum number of expired ec2 instances that will be stopped instead of terminated.
# Note the distinction between the two.

INSTANCE_PROFILE_NAME = 'EC2Profile'  # Create and specify EC2 Profile Name  using AMI in AWS console
ROLE_NAME = 'EC2Role'  # Create and specify EC2 Role using AMI in AWS console
AMI_TEMPLATE_NAME = r'instance-server-v\d+'  #  To avoid using the ever-changing AMI id we use a ordered custom name instead

IDLE_TIME_KEY_TAG = "last_time_working"  # Key syntax for tagging when last an EC2 instance was observed not to be idle

ec2_resources = boto3.resource('ec2')


def get_instance_state(instance_id):
	for instance in get_all_created_instances():
		if instance.id == instance_id:
			return instance.state['Name']

	return None


def get_latest_ami_version():
	"""
	Select the latest version of the image based on the naming template.
	:return:
	"""

	ec2_client = boto3.client('ec2')
	images = ec2_client.describe_images(Owners=['self'])['Images']

	selected_image = (None, -1)  # (ami image object, ami image version)
	for image in images:
		if re.match(AMI_TEMPLATE_NAME, image['Name']):

			tmp_ver = int((re.search(r'\d+', image['Name'])).group(0))
			if tmp_ver > selected_image[1]:
				selected_image = (image, tmp_ver)

	if selected_image[1] == -1:
		raise KeyError('AMI with name "' + AMI_TEMPLATE_NAME + '" not found')
	else:
		return selected_image


def create_instances_from_image(num_instances=1, image_id=None):
	"""
	Instantiates EC2 instance from AMI identifier
	:param num_instances:
	:return:
	"""
	if image_id is None:
		print("Attempting to get AMI based on the template name: " + AMI_TEMPLATE_NAME + "...\n")
		ami_obj = get_latest_ami_version()
		print('Using ami version #' + str(ami_obj[1]) + ' ...')
		image_id = ami_obj[0]['ImageId']
	instances = ec2_resources.create_instances(
		ImageId=image_id,
		MinCount=num_instances,
		MaxCount=num_instances,
		KeyName=None,
		InstanceType=INSTANCE_TYPE)
	for instance in instances:
		ec2_resources.create_tags(Resources=[instance.id], Tags=[{'Key': 'type', 'Value': TAG_KEY}, {
			'Key': IDLE_TIME_KEY_TAG, 'Value': str(datetime.datetime.now())}, ], )

	return instances


def create_role():
	iam_client = boto3.client('iam')

	doc_str = '''{
		"Version": "2012-10-17",
		"Statement": [{
				"Effect": "Allow",
				"Principal": {
						"Service": "ec2.amazonaws.com"
						},
				"Action": "sts:AssumeRole"}]}'''
	try:
		response = iam_client.create_role(
			AssumeRolePolicyDocument=doc_str,
			Path='/',
			Description='Allows SSM agents on server EC2 instances to receive command and as well as s3 access amongst other priveledges.',
			RoleName=ROLE_NAME,
		)
		role_name = response["Role"]["RoleName"]
		iam_client.attach_role_policy(
			RoleName=role_name,
			PolicyArn='arn:aws:iam::aws:policy/service-role/AmazonEC2RoleforSSM'
			# This is the aws resource name of a managed policy provided by aws which gives ec2 ssm access, s3 access etc.
		)
		print('Created role "' + role_name + '" ...')
		return role_name

	except iam_client.exceptions.EntityAlreadyExistsException:
		print('Role with name "' + INSTANCE_PROFILE_NAME + '" already exists. Continuing ...')
		return ROLE_NAME


def create_instance_profile_from_iam_role(role_name):
	"""
	Creates Instance Profile from IAM Role
	:param role_name: Name od IAM Role
	:return:
	"""
	iam_client = boto3.client('iam')
	try:
		response = iam_client.create_instance_profile(
			InstanceProfileName=INSTANCE_PROFILE_NAME,
			Path='/')

		iam_client.add_role_to_instance_profile(
			InstanceProfileName=response['InstanceProfile']['InstanceProfileName'],
			RoleName=role_name)
		# wait for instance profile to be registered
		time.sleep(10)
	except iam_client.exceptions.EntityAlreadyExistsException:
		print('Instance profile with name "' + INSTANCE_PROFILE_NAME + '" already exists. Continuing ...')
	return INSTANCE_PROFILE_NAME


def remove_instance_profile(instance_profile_name=None):

	"""
		Function to remove the instance profile. Removes the default Instance Profile if None is passed in
	:param instance_profile_name:
	:return:
	"""
	if instance_profile_name is None:
		instance_profile_name = INSTANCE_PROFILE_NAME
	iam_client = boto3.client('iam')
	iam_client.delete_instance_profile(InstanceProfileName=instance_profile_name)


def get_instance_profile():

	"""
		Function to get instance profile from default name
	:return:
	"""
	iam_client = boto3.client('iam')

	def find_profile_by_name():
		response = iam_client.list_instance_profiles()
		if response is not None:
			for temp_instance_profile in response['InstanceProfiles']:
				if temp_instance_profile['InstanceProfileName'] == INSTANCE_PROFILE_NAME:
					return temp_instance_profile
		else:
			print('Unable to get list of available instance profiles!')
		return None

	# First attempt to find instance profile by name
	instance_profile = find_profile_by_name()

	if instance_profile is None:
		# try create profile with ssm agent permission
		print('Default instance profile not found ...')
		print('Attempting to create new instance profile ...')
		IAM_role = create_role()
		create_instance_profile_from_iam_role(IAM_role)
		instance_profile = find_profile_by_name()
		if instance_profile is None:
			print('Unable to create instance policy!')
			return None
		else:
			print('Successfully created new instance profile "' + INSTANCE_PROFILE_NAME + '"')
			return instance_profile
	else:
		return instance_profile


def attach_instance_profile(target_id, instance_profile=None):
	"""
	Attach instance profile to EC2 instance
	:param target_id:
	:param instance_profile:
	:return:
	"""
	if instance_profile is None:  # if none is provided try use the predefine one
		instance_profile = get_instance_profile()
	if instance_profile is None:
		print('No instance profile passed in and unable to create or get default instance profile.')
		return False

	ec2_client = boto3.client('ec2')
	ec2_client.associate_iam_instance_profile(
		IamInstanceProfile={
			'Arn': instance_profile['Arn'],
			'Name': instance_profile['InstanceProfileName']},
		InstanceId=target_id)

	return True


def terminate_images(instance_ids):
	"""
	Terminate instances based on passed in list of instance ids
	:param instance_ids: List of instance ID to the EC" instances to be terminated
	:return:
	"""
	ec2_resources.instances.filter(InstanceIds=instance_ids).terminate()


def stop_instances(instance_ids):
	"""
	Stop instances based on passed in list of instance ids
	:param instance_ids: List of instance ID to the EC" instances to be stopped
	:return:
	"""
	ec2_resources.instances.filter(InstanceIds=instance_ids).stop()


def clean_up(instances):
	"""
	Helper function to terminate list of instances passed into it
	:param instances: List of instances to be terminated

	:return:
	"""
	stp_count = 0
	for instance in instances:
		if stp_count < MAX_STOPPED:
			stop_instances([instance.id])
			stp_count = stp_count + 1
		# print('Stopping ...  \n')
		else:
			terminate_images([instance.id])
		# print('Terminating ... \n')


def get_all_created_instances():

	"""
	Return list of images that are tagged with the "TAG_KEY" keyword i.e. that were spunned using this module.
	:return: List of instances created within this library
	"""
	ec2 = boto3.resource('ec2')
	created_instances = list()
	for instance in ec2.instances.all():
		if instance.tags is None:
			continue
		# print (instance.id)
		# print(instance.tags)
		for tag in instance.tags:
			if tag['Key'] == 'type':
				if tag['Value'] == TAG_KEY:
					created_instances.append(instance)
				break

	return created_instances


def get_running_instances(instances):
	"""
	Function to get running instances from list of EC2 instances
	:param instances:
	:return:  List od instances
	"""
	if instances is None:
		return
	valid_instances = list()
	for i in range(len(instances)):
		if instances[i].state['Name'] == 'running':
			valid_instances.append(instances[i])

	return valid_instances


def wait_for_instance_start_up(instance, time_out=500):
	sleep_time = 5
	ready = True

	if instance.state['Name'] == 'terminated':
		ready = False
		return ready

	while instance.state['Name'] not in ('running', 'stopped', 'terminated'):
		time.sleep(sleep_time)
		instance.load()
		print(time_out)
		time_out = time_out - sleep_time
		if time_out < 0:
			ready = False
			break

	return ready


def expired(instances):
	if instances is None:
		return
	expired_instances = list()
	for instance in instances:
		print(instance)
		if instance.state['Name'] == 'terminated':
			continue
		# print (instance.launch_time)
		lt_datetime = parse(str(instance.launch_time))
		lt_delta = datetime.datetime.now(lt_datetime.tzinfo) - lt_datetime
		uptime = lt_delta.total_seconds()

		# print(uptime)
		if uptime > MAX_LIFE_SPAN:
			print(instance.id)
			expired_instances.append(instance)

	return expired_instances


if __name__ == '__main__':

	instances_created = create_instances_from_image(num_instances=2)
	for instance in instances_created:
		wait_for_instance_start_up(instance)
		attach_instance_profile(instance.id)







