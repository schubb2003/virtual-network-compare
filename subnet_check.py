#!/usr/local/bin/python
"""
Author: Scott Chubb scott.chubb@netapp.com
Date:	13-Feb-2019
Written for Python 3.4 and above
No warranty is offered, use at your own risk.  While these scripts have been tested in lab situations, all use cases cannot be accounted for.
MVIP and username are required, password is not as getpass is invoked if password is blank
This script was created to be able to compare host access IPs to the SVIP virtual network and determine if the connections were local or routed
As of v1, it only works on clusters with a single virtual network and has no error checking
	If you have multiple VLANs the script only checks the first one. 
v1.1 - added basic connectivity error checking and updated some comments to help identify what is happening where
"""

import argparse
#from pprint import pprint
from getpass import getpass
from solidfire.factory import ElementFactory

session_array = []
ip_array = []

def get_inputs():
	"""
	Gather inputs, requires mvip, user, password, called in connect_cluster
	"""
	parser = argparse.ArgumentParser()
	parser.add_argument('-m', type=str,
						required=True,
						metavar='mvip',
						help='MVIP name or IP')
	parser.add_argument('-u', type=str,
						required=True,
						metavar='username',
						help='Source username to connect with')
	parser.add_argument('-p', type=str,
						required=False,
						metavar='password',
						help='Source password for user')
	args = parser.parse_args()
	sfmvip = args.m
	sfuser = args.u
	if not args.p:
		sfpass = getpass("Enter password for user{} on cluster {}: ".format(sfuser, sfmvip))
	else:
		sfpass = args.p
	return sfmvip, sfuser, sfpass

def connect_cluster():
	"""
	Attempt to connect to the cluster
	"""
	sfmvip, sfuser, sfpass = get_inputs()
	try:
		sfe = ElementFactory.create(sfmvip,sfuser,sfpass, print_ascii_art=False)
		return sfe
	except Exception as ex:
		if "Bad Credentials" in str(ex):
			print("Incorrect user or password entered, please re-enter:\n")
			sfuser = input("Enter user name: ")
			sfpass = getpass("Enter password for user {} on cluster {}: ".format(sfuser, sfmvip))
			sfe = ElementFactory.create(sfmvip,sfuser,sfpass, print_ascii_art=False)
			return sfe
		elif "host has failed to respond" in str(ex):
			sfmvip = input("Please re-enter MVIP: ")
			sfe = ElementFactory.create(sfmvip,sfuser,sfpass, print_ascii_art=False)
			return sfe
		else:
			print("Script will exit due to an unhandled exception: \n{}".format(str(ex)))
			exit()
			

def find_net_info(sfe):
	"""
	Gather the networking information for virtual networks
	Looks at the subnet and determines the block size for use in find_block
	"""
	print("-" * 20 + " find_net_info started")
	virt_net = sfe.list_virtual_networks()
	json_virt_net = virt_net.to_json()
	#pprint(json_virt_net)
	virt_mask = json_virt_net['virtualNetworks'][0]['netmask']
	svip = json_virt_net['virtualNetworks'][0]['svip']

	# Break the netmask into constituent octets to get the one that determines the host network
	mask_oct1 = int(virt_mask.split(".")[0])
	mask_oct2 = int(virt_mask.split(".")[1])
	mask_oct3 = int(virt_mask.split(".")[2])
	mask_oct4 = int(virt_mask.split(".")[3])

	# Return the octet that has the determining bits
	if mask_oct1 != 255:
		oct_pos = 0
		comp_oct = mask_oct1
	elif mask_oct2 != 255:
		oct_pos = 1
		comp_oct = mask_oct2
	elif mask_oct3 != 255:
		oct_pos = 2
		comp_oct = mask_oct3
	else:
		oct_pos = 3
		comp_oct = mask_oct4

	# Find the network block size
	comp_block = 256 - comp_oct 

	# Find the SVIP host bits
	comp_svip = int(svip.split(".")[oct_pos])
	int_svip = int(comp_svip)
	return int_svip, comp_block, oct_pos

def find_block(int_svip, comp_block):
	"""
	Take the block size and determine the block range for the subnet in question
	"""
	print("-" * 20 + " find_block started")
	bsz = comp_block
	outsz = 0
	bsdict = {}
	bsdict [0] = bsz
	# Build the dictionary of the host networks
	while outsz < 255:
		outsz = outsz + bsz
		bsdict[outsz] = (outsz + bsz) -1
		#print(outsz)
	
	# Determine the upper and lower bounds of the host network
	for key in bsdict.keys():
		if int_svip >= key and int_svip <= bsdict[key]:
			block_start = key
			block_end = bsdict[key]

	#print("Block start is {}\nBlock end is {}".format(block_start, block_end))
	return block_start, block_end

def find_sessions(sfe):
	"""
	Build a list of all the iSCSI sessions on the cluster
	"""
	print("-" * 20 + " find_sessions started")
	isessions = sfe.list_iscsisessions()
	json_isessions = isessions.to_json()
	return json_isessions
	
def get_initiator_IP(json_isessions):
	"""
	pull the IP from the host session
	"""
	print("-" * 20 + " get_initiator started")
	for session in json_isessions['sessions']:
		session_array.append(session['initiatorIP'])
	return session_array

def main(oct_pos):
	"""
	Actually do the work, split the host IP and compare it to the block_start and block_end
	Compare that the IP is greater than or equal to block start and less then or equal to block end
	"""
	print("-" * 20 + " main started")
	for ip_port in session_array:
		ip = ip_port.split(":")[0]
		ip_array.append(ip)

	# Determine if the host and the cluster are in the same host network or are connecting via a routed network
	for ip_comp in ip_array:
		determine_oct = int(ip_comp.split(".")[oct_pos])
		print(block_start, determine_oct, block_end)
		if determine_oct  >= block_start and determine_oct <= block_end:
			print("Pass, {} is in the right subnet".format(ip_comp))
		else:
			print("**Fail**, {} is not in the right subnet".format(ip_comp))


if __name__ == "__main__":
	sfe = connect_cluster()
	int_svip, comp_block, oct_pos = find_net_info(sfe)
	block_start, block_end = find_block(int_svip, comp_block)
	json_isessions = find_sessions(sfe)
	get_initiator_IP(json_isessions)
	main(oct_pos)