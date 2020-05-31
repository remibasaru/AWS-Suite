import boto3
import json
import time

ssm_client = boto3.client(service_name='ssm')


def get_instance_list():
	"""
	Get instances that are SSM ready
	:return:
	"""
	detail = ssm_client.describe_instance_information()
	id_list = detail['InstanceInformationList']
	return id_list


def post_cmd_with_response(target_id, _command, _comment=""):
	"""

	Run a generic command on a remote EC2 server instance
	:param target_id: is the instance ID of the ec2 server in question
	:param _command: Shell command to be executed in the EC2 instance
	:param _comment: Description of the command
	:return: The command ID of the task. This can be later used to get response of executing the command
	"""
	id_list = get_instance_list()
	for i in range(len(id_list)):
		_id = id_list[i]['InstanceId']

		if _id == target_id and id_list[i]['PingStatus'] == 'Online':
			try:
				response = ssm_client.send_command(
					InstanceIds=[
						target_id
					],
					DocumentName="AWS-RunShellScript",
					Comment=_comment,
					Parameters={
						"commands": [_command]
					}
				)
			except:
				return None

			# print(response['Command'], '\n\n')
			command_id = response['Command']['CommandId']

			return command_id
	return None


def poll_cmd_for_result(cmd_id, target_id, walltime=10):

	"""
	Polls a server ec2 instance for the status of the sent command
	:param cmd_id: is the command Id of the send command returned by the 'post_cmd-with_response()' or 'run_remote_plaque_algo()' function
	:param target_id: is the instance ID of the ec2 server in question
	:param walltime: maximum time to wait for a result
	:return:
	"""
	cmd_invo = None
	count = 0
	if cmd_id is not None:
		while cmd_invo is None and count < walltime:
			# print('Polling ... \n')
			response = ssm_client.list_command_invocations(CommandId=cmd_id,
														   InstanceId=target_id,
														   Details=True)
			# cmd_invo = response['CommandInvocations']
			# print(response)
			if len(response['CommandInvocations']) == 1:
				cmd_invo = response['CommandInvocations'][0]
				if cmd_invo['CommandPlugins'][0]['Status'] not in ['Pending', 'InProgress', 'Delayed']:
					break
			time.sleep(1)
			count = count + 1

	if cmd_invo is not None:
		out_obj = {}
		print(cmd_invo['CommandPlugins'][0]['Output'])
		out_obj['Status'] = cmd_invo['CommandPlugins'][0]['Status']
		if out_obj['Status'] == 'Success':
			out_obj['Output'] = cmd_invo['CommandPlugins'][0]['Output']
		return out_obj

	return None





