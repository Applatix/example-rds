#! /usr/bin/env python

import argparse
import logging
import os
import sys
import zipfile

import MySQLdb
import requests

logger = logging.getLogger(__name__)

URL = 'http://seanlahman.com/files/database/lahman2016-sql.zip'


class MLBDataLoader(object):

    def __init__(self, dbhost, username='root', password=None, port=3306):
        """
        :param dbhost:
        :param username:
        :param password:
        :param port:
        :return:
        """
        db = MySQLdb.connect(dbhost, user=username, password=password, port=port)
        self.cursor = db.cursor()
        self.log = logger

    def run(self):
        """
        :return:
        """
        self.log.info('Downloading MLB sql file from URL "%s"', URL)
        sql_file = self.download_sql_file(URL)
        self.log.info('The MLB sql file is "%s"', sql_file)
        self.log.info('Loading SQL to DB ...')
        self.load_sql_to_db(sql_file)
        self.log.info('Complete: Successfully load SQL data to mysql database')

    def download_sql_file(self, url):
        """
        :param url:
        :return:
        """
        zipped = '/tmp/tmp.zip'
        unzipped = '/tmp/unzipped'

        with open(zipped, "wb") as f:
            response = requests.get(url)
            f.write(response.content)
        zipfile.ZipFile(zipped).extractall(unzipped)
        if os.path.exists(zipped):
            os.remove(zipped)
        for root, _, files in os.walk(unzipped):
            for f in files:
                if f.endswith('.sql'):
                    ff = os.path.join(root, f)
                    self.log.info('Got SQL file %s', ff)
                    return ff
        self.log.error('No SQL file')
        return

    def load_sql_to_db(self, sql_file):
        """
        :param sql_file:
        :return:
        """
        statement = ''
        for line in open(sql_file):
            line = line.strip()
            if line.startswith('--'):  # ignore sql comment lines
                continue
            if not line.endswith(';'):
                statement += line
            else:  # when you get a line ending in ';' then exec statement and reset for next statement
                statement += line
                try:
                    self.log.info('Execute SQL command %s', statement)
                    self.cursor.execute(statement)
                except Exception as exc:
                    self.log.info(exc)
                finally:
                    statement = ''


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Tool to load SQL data to MySQL database')
    parser.add_argument('--dbhost', required=True, help='The database host')
    parser.add_argument('--username', default='root', help='The database username')
    parser.add_argument('--password', help='The database password')
    parser.add_argument('--port', default=3306, type=int, help='The database password')
    logging.basicConfig(format='%(asctime)s.%(msecs)03d %(levelname)s %(name)s %(threadName)s: %(message)s',
                        datefmt='%Y-%m-%dT%H:%M:%S',
                        level=logging.INFO,
                        stream=sys.stdout)
    args = parser.parse_args()
    rc = 0
    try:
        loader = MLBDataLoader(args.dbhost, username=args.username, password=args.password, port=args.port)
        loader.run()
    except Exception as exc:
        logger.exception(exc)
        rc = 1
    finally:
        sys.exit(rc)
