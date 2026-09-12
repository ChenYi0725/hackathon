"""Render the single-host CloudFormation template; this command creates no AWS resources."""
import json
from pathlib import Path


def template():
    parameters = {
        'VpcId': {'Type': 'AWS::EC2::VPC::Id'},
        'SubnetId': {'Type': 'AWS::EC2::Subnet::Id'},
        'ImageId': {'Type': 'AWS::EC2::Image::Id', 'Description': 'Canonical Ubuntu 24.04 amd64 AMI in the selected region'},
        'SourceRevision': {'Type': 'String', 'AllowedPattern': '[0-9a-f]{40}'},
    }
    for i in range(1, 6):
        parameters[f'ClientCidr{i}'] = {
            'Type': 'String', 'AllowedPattern': r'(\d{1,3}\.){3}\d{1,3}/32',
            'Description': 'One allowed client IPv4 address (/32 only)',
        }
    tags = [{'Key': 'Project', 'Value': 'landwise'}]
    return {
        'AWSTemplateFormatVersion': '2010-09-09',
        'Description': 'Landwise: one CPU host, encrypted EBS, five client IPs, SSM, regional Bedrock',
        'Parameters': parameters,
        'Resources': {
            'Role': {'Type': 'AWS::IAM::Role', 'Properties': {
                'AssumeRolePolicyDocument': {'Version': '2012-10-17', 'Statement': [{
                    'Effect': 'Allow', 'Principal': {'Service': 'ec2.amazonaws.com'}, 'Action': 'sts:AssumeRole',
                }]},
                'ManagedPolicyArns': ['arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore'],
                'Policies': [{'PolicyName': 'RegionalBedrock', 'PolicyDocument': {
                    'Version': '2012-10-17', 'Statement': [{
                        'Effect': 'Allow', 'Action': ['bedrock:InvokeModel'],
                        'Resource': {'Fn::Sub': 'arn:aws:bedrock:${AWS::Region}::foundation-model/qwen.qwen3-32b-v1:0'},
                    }],
                }}], 'Tags': tags,
            }},
            'Profile': {'Type': 'AWS::IAM::InstanceProfile', 'Properties': {'Roles': [{'Ref': 'Role'}]}},
            'WebSecurityGroup': {'Type': 'AWS::EC2::SecurityGroup', 'Properties': {
                'GroupDescription': 'HTTP from four approved IPv4 addresses and the operator; administration through SSM',
                'VpcId': {'Ref': 'VpcId'}, 'Tags': tags,
                'SecurityGroupIngress': [
                    {'IpProtocol': 'tcp', 'FromPort': 80, 'ToPort': 80, 'CidrIp': {'Ref': f'ClientCidr{i}'}}
                    for i in range(1, 6)
                ],
            }},
            'Host': {'Type': 'AWS::EC2::Instance', 'Properties': {
                'ImageId': {'Ref': 'ImageId'}, 'InstanceType': 't3.large',
                'IamInstanceProfile': {'Ref': 'Profile'},
                'NetworkInterfaces': [{'DeviceIndex': '0', 'AssociatePublicIpAddress': True,
                                       'SubnetId': {'Ref': 'SubnetId'}, 'GroupSet': [{'Ref': 'WebSecurityGroup'}]}],
                'MetadataOptions': {'HttpTokens': 'required', 'HttpPutResponseHopLimit': 1},
                'BlockDeviceMappings': [{'DeviceName': '/dev/sda1', 'Ebs': {
                    'VolumeType': 'gp3', 'VolumeSize': 40, 'Encrypted': True, 'DeleteOnTermination': False,
                }}],
                'CreditSpecification': {'CPUCredits': 'standard'},
                'Tags': tags + [{'Key': 'Name', 'Value': 'landwise-web'},
                                {'Key': 'SourceRevision', 'Value': {'Ref': 'SourceRevision'}}],
                'UserData': {'Fn::Base64': {'Fn::Join': ['', [
                    '#!/usr/bin/env bash\nexport SOURCE_REV=', {'Ref': 'SourceRevision'},
                    '\nexport AWS_DEFAULT_REGION=', {'Ref': 'AWS::Region'}, '\n',
                    Path(__file__).with_name('bootstrap.sh').read_text(),
                ]]}},
            }},
        },
        'Outputs': {
            'InstanceId': {'Value': {'Ref': 'Host'}},
            'SecurityGroupId': {'Value': {'Ref': 'WebSecurityGroup'}},
            'Url': {'Value': {'Fn::Sub': 'http://${Host.PublicIp}'}},
        },
    }


if __name__ == '__main__':
    print(json.dumps(template(), ensure_ascii=False, indent=2))
