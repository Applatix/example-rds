#! /usr/bin/env python
#
# AWS Boto SDK ref:
# https://boto3.readthedocs.io/en/latest/reference/services/rds.html#RDS.Client.create_db_cluster

import argparse
import boto3
import botocore
import logging
import os
import sys
import time
import uuid
import yaml

logger = logging.getLogger(__name__)


class RDSTools(object):

    def __init__(self, aws_access_key_id=None, aws_secret_access_key=None, aws_region=None):
        """
        :param aws_access_key_id:
        :param aws_secret_access_key:
        :param aws_region:
        :return:
        """
        if aws_access_key_id is None or aws_secret_access_key is None:
            aws_access_key_id = os.environ.get('AWS_ACCESS_KEY_ID')
            aws_secret_access_key = os.environ.get('AWS_SECRET_ACCESS_KEY')
        if aws_region is None:
            aws_region = os.environ.get('AWS_REGION') or 'us-west-2'
        assert all([aws_access_key_id, aws_secret_access_key, aws_region]), \
            'Require parameters AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, and AWS_REGION'

        self.session = boto3.Session(aws_access_key_id=aws_access_key_id,
                                     aws_secret_access_key=aws_secret_access_key,
                                     region_name=aws_region)
        self.rds_client = self.session.client('rds')
        self.ec2_client = self.session.client('ec2')
        self.log = logger

    def create_rds(self, config, response_file='rds.info', master_user_password=None, interval=20, wait=True):
        """
        :param config:
        :param response_file:
        :param master_user_password:
        :param interval:
        :param wait:
        :return:

        DBInstanceClass (string) --
        [REQUIRED]
        The compute and memory capacity of the DB instance. Note that not all instance classes are available
        in all regions for all DB engines.
        Valid Values: db.t1.micro | db.m1.small | db.m1.medium | db.m1.large | db.m1.xlarge | db.m2.xlarge |
                      db.m2.2xlarge | db.m2.4xlarge | db.m3.medium | db.m3.large | db.m3.xlarge | db.m3.2xlarge |
                      db.m4.large | db.m4.xlarge | db.m4.2xlarge | db.m4.4xlarge | db.m4.10xlarge | db.r3.large |
                      db.r3.xlarge | db.r3.2xlarge | db.r3.4xlarge | db.r3.8xlarge | db.t2.micro | db.t2.small |
                      db.t2.medium | db.t2.large

        Engine (string) --
        [REQUIRED]
        The name of the database engine to be used for this instance.
        Valid Values: mysql | mariadb | oracle-se1 | oracle-se2 | oracle-se | oracle-ee | sqlserver-ee | sqlserver-se |
                      sqlserver-ex | sqlserver-web | postgres | aurora
        """
        parameters = self._load_config(config)
        db_instance_identifier = parameters.get('DBInstanceIdentifier') + '-' + str(uuid.uuid4())
        parameters['DBInstanceIdentifier'] = db_instance_identifier
        parameters['MasterUserPassword'] = master_user_password

        sgs = parameters.get('VpcSecurityGroupIds', None)
        if sgs is None or sgs == [None]:
            self.log.info('There is no configured VpcSecurityGroupIds, automatically create one to open 0.0.0.0/0')
            sg_port = parameters.get('Port')
            sg_id = self.create_security_group(db_instance_identifier, sg_port)
            parameters['VpcSecurityGroupIds'] = [sg_id]

        try:
            _ = self.rds_client.create_db_instance(**parameters)
        except botocore.exceptions.ClientError as exc:
            if 'DBInstanceAlreadyExists' in exc.response['Error']['Message']:
                self.log.error('RDS instance %s exists already', db_instance_identifier)
            else:
                self.log.info('Delete security group %s, which is automatically created', db_instance_identifier)
                self.delete_security_group(db_instance_identifier)
                raise

        start_time = time.time()
        response = self.describe_db_instances(db_instance_identifier)
        while wait:
            response = self.describe_db_instances(db_instance_identifier)
            rds_instance = response['DBInstances'][0]
            status = rds_instance['DBInstanceStatus']
            self.log.info('Waiting, RDS instance (%s) is in %s status', db_instance_identifier, status)
            if status.lower() == 'available':
                elapsed = time.time() - start_time
                endpoint = rds_instance['Endpoint']
                host = endpoint['Address']
                port = endpoint['Port']
                self.log.info('It took %s seconds to get RDS %s ready', elapsed, db_instance_identifier)
                self.log.info('RDS instance: Host: %s, Port: %s', host, port)
                break
            time.sleep(interval)

        self.log.info('Save RDS instance info to file: %s', response)
        with open(response_file, 'w+') as f:
            f.write(str(response))
        return response_file

    def delete_rds(self, db_instance_identifier, skip_final_snapshot=True, interval=20):
        """
        :param db_instance_identifier:
        :param skip_final_snapshot:
        :param interval:
        :return:
        """
        response = self.describe_db_instances(db_instance_identifier)
        self.rds_client.delete_db_instance(DBInstanceIdentifier=db_instance_identifier,
                                           SkipFinalSnapshot=skip_final_snapshot)
        start_time = time.time()
        while True:
            try:
                response = self.describe_db_instances(db_instance_identifier)
                rds_instance = response['DBInstances'][0]
                status = rds_instance['DBInstanceStatus']
                self.log.info('Waiting, RDS instance (%s) is in %s status', db_instance_identifier, status)
            except botocore.exceptions.ClientError as _:
                elapsed = time.time() - start_time
                self.log.info('It took %s seconds to delete RDS %s', elapsed, db_instance_identifier)
                break
            time.sleep(interval)

        self.log.info('Delete security group %s, which is automatically created', db_instance_identifier)
        self.delete_security_group(db_instance_identifier)
        return response

    def describe_db_instances(self, db_instance_identifier, **kwargs):
        """
        :param db_instance_identifier:
        :param kwargs:
        :return:
        """
        return self.rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_identifier, **kwargs)

    def create_security_group(self, security_group_name, port, cidr_ip=None):
        """
        :param security_group_name:
        :param port
        :param cidr_ip:
        :return:
        """
        if cidr_ip is None:
            cidr_ip = '0.0.0.0/0'
        self.log.info('Creating security group %s, open port %s', security_group_name, port)
        response = self.ec2_client.create_security_group(GroupName=security_group_name,
                                                         Description='AWS RDS temp security group to ALL')
        sg_id = response['GroupId']
        self.ec2_client.authorize_security_group_ingress(GroupId=sg_id,
                                                         IpProtocol='tcp',
                                                         FromPort=port,
                                                         ToPort=port,
                                                         CidrIp=cidr_ip)
        self.log.info('Created: security group %s', sg_id)
        return sg_id

    def delete_security_group(self, sg_name):
        """
        :param sg_name:
        :return:
        """
        return self.ec2_client.delete_security_group(GroupName=sg_name)

    def _load_config(self, config_file):
        """
        :param config_file:
        :return:
        """
        if not config_file.endswith('.yaml'):
            raise NotImplementedError
        with open(config_file, 'r') as stream:
            paras = yaml.load(stream)
        return paras


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tools for AWS RDS')
    subparsers = parser.add_subparsers(dest='action', title='Actions')
    create_parser = subparsers.add_parser('create', help='Create AWS RDS')
    create_parser.add_argument('--dbtype', choices=['mysql', 'mariadb', 'postgresql'], help='The DB type to for the default YAML configuration file')
    create_parser.add_argument('--response', default='rdsinfo.txt', help='The RDS response info')
    create_parser.add_argument('--master_user_password', required=True, help='The root password for RDS instance')

    delete_parser = subparsers.add_parser('delete', help='Delete a AWS RDS')
    delete_parser.add_argument('--db_instance', required=True, help='The AWS RDS DB instance identifier')

    for par in [create_parser, delete_parser]:
        par.add_argument('--aws_access_key_id', required=True, help='The AWS ACCESS KEY')
        par.add_argument('--aws_secret_access_key', required=True, help='The AWS SECRET ACCESS KEY')
        par.add_argument('--aws_region', default='us-west-2', help='The AWS REGION')

    logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(threadName)s: %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%S',
                        level=logging.INFO,
                        stream=sys.stdout)
    args = parser.parse_args()

    rc = 0
    try:
        tool = RDSTools(aws_access_key_id=args.aws_access_key_id,
                        aws_secret_access_key=args.aws_secret_access_key,
                        aws_region=args.aws_region)
        if args.action == 'create':
            config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'rds_configuration', '{}.yaml'.format(args.dbtype))
            tool.create_rds(config_file, response_file=args.response, master_user_password=args.master_user_password)
        elif args.action == 'delete':
            tool.delete_rds(args.db_instance)
        else:
            parser.print_help(args)
    except Exception as exc:
        logger.exception(exc)
        rc = 1
    finally:
        sys.exit(rc)

