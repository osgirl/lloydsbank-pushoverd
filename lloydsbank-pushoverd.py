#!/usr/bin/env python
# -*- coding: utf-8 -*-
# lloydsbank-pushoverd.py - Receive pushover notification with your Lloyds Bank account balance.
# This file is part of lloydsbank-pushoverd.
# Copyright (c) 2014 Tomasz Jan Góralczyk <tomg@fastmail.uk>
# License: MIT
from __future__ import print_function
from datetime import date, datetime
from decimal import Decimal as D
from hashlib import sha256
from urllib import urlencode
import argparse
import csv
import httplib
import json
import logging
import mechanize
import os.path
import re
import sys

# Default user agent.
USER_AGENT =  'Mozilla/5.0 (Windows NT 6.1; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/34.0.1847.116 Safari/537.36'

# Transaction log item.
class Transaction(object):
    # Dictionary of transaction types.
    TRANSACTION_TYPES = {
            'BGC': 'Bank giro credit',
            'BP': 'Bill payment',
            'CD': 'Card payment',
            'CHG': 'Charge',
            'CHQ': 'Cheque',
            'COMM': 'Comission',
            'COR': 'Correction',
            'CPT': 'Cashpoint',
            'CSH': 'Cash',
            'CSQ': 'Cash / Cheque',
            'DD': 'Direct Debit',
            'DEB': 'Debit card',
            'DEP': 'Deposit',
            'DR': 'Overdrawn balance',
            'EUR': 'Euro cheque',
            'FPI': 'Faster payments incoming',
            'FPO': 'Faster payments outgoing',
            'IB': 'Internet Banking',
            'MTU': 'Mobile top up',
            'PAY': 'Payment',
            'PSV': 'Paysave',
            'SAL': 'Salary',
            'SO': 'Standing order',
            'TFR': 'Transfer'
    }

    # Convert CSV data into a transaction object.
    def __init__(self, account_name, fields):
        self.account_name = account_name
        dt = datetime.strptime(fields['Transaction Date'], '%d/%m/%Y')
        self.date = date(dt.year, dt.month, dt.day)
        self.transaction_type = fields['Transaction Type']
        self.account_number = fields['Account Number']
        self.sort_code = fields['Sort Code'].strip("'")

        if fields['Debit Amount']:
            self.amount = -D(fields['Debit Amount'])
        else:
            self.amount = D(fields['Credit Amount'])

        self.balance = D(fields['Balance'])
        self.card = None

        self.raw_description = fields['Transaction Description']
        self.description = self._parse_description()

        # "Unique" hash of the transaction.
        self.hash = sha256(self.__repr__()).hexdigest()

    def _parse_description(self):
        desc = self.raw_description.strip()
        end_date = self.date.strftime("%d%b%y").upper()
        if desc.endswith(end_date):
            desc = desc[:-len(end_date)].strip()
        match = re.match('(.*?) CD (\d{4})$', desc)
        if match:
            desc = match.group(1).strip()
            self.card = match.group(2)
        return desc

    def __repr__(self):
        return "Transaction(%s, %s, %s, %s, %s)" % (
                self.account_name, self.date.strftime('%d/%m/%Y'), self.get_type_explanation(),
                self.description, self.amount)

    def get_type_explanation(self):
        if (self.transaction_type.startswith('CD')):
            four_digits = self.transaction_type[len('CD '):]
            return 'Paid by card **** **** **** %d' % four_digits
        else:
            return self.TRANSACTION_TYPES.get(self.transaction_type, '')


# Parse commandline arguments.
def parse_commandline():
    global USER_AGENT

    # Create parser.
    parser = argparse.ArgumentParser(
            description='Receive pushover notification with your Lloyds Bank account balance.')
    parser.add_argument('config', metavar='config-file.json', type=file,
            help='path to the configuration file')
    parser.add_argument('-f', '--force', action='store_true',
            help='send notification even if no new transactions are found')
    parser.add_argument('--log', default="~/.lloyds_transaction_log",
            metavar="~/.lloyds_transaction_log", help="file storing the unique ID of last transaction")

    # Parse and return arguments.
    return parser.parse_args()

# Parse configuration file.
# f - File handle to configuration file.
def parse_configuration(f):
    # Read configuration from file.
    config = json.load(f)
    # Close the file.
    f.close()
    # Return config.
    return config


# Log into Lloyds internet banking and fetch account information.
# userid - User ID.
# password - password
# memorable_information - memorable information string
# account_names - Account names.
def get_account_information(userid, password, memorable_information):
    global USER_AGENT

    # Create a browser object.
    br = mechanize.Browser()
    br.set_handle_robots(False)
    br.addheaders = [('User-agent', USER_AGENT)]

    # Enter User ID and password.
    br.open('https://online.lloydsbank.co.uk/personal/logon/login.jsp')
    form_name = 'frmLogin'
    br.select_form(form_name)
    br['frmLogin:strCustomerLogin_userID'] = userid
    br['frmLogin:strCustomerLogin_pwd'] = password
    response = br.submit()
    assert response.code == 200 and form_name not in response.read()

    # Enter memorable information.
    form_name = 'frmentermemorableinformation1'
    br.select_form(form_name)
    prefix = '%s:strEnterMemorableInformation_memInfo' % form_name
    for control in br.form.controls:
        if control.name.startswith(prefix):
            label = control.get_labels()[0].text
            position = int(re.findall(r'^Character (\d+) :$', label)[0])
            # Make position 0-indexed
            position -= 1
            assert 0 <= position < len(memorable_information)
            br[control.name] = ["&nbsp;" + memorable_information[position]]
    br.submit()
    assert 'Personal Account Overview' in br.title()

    # Get account list.
    accounts = []
    for link in br.links():
        attrs = dict(link.attrs)
        if 'lkImageRetail' in attrs.get('id', ''):
            accounts.append((re.findall(r'^(.+?)\[IMG\]', link.text)[0], link.absolute_url))

    # Fetch transaction list for each account.
    transactions = []
    for account in accounts:
        br.open(account[1])
        export_link = br.find_link(text="Export")
        br.follow_link(export_link)
        br.select_form('frmTest')
        br.submit()

        rows = csv.DictReader(br.response())
        transactions += [Transaction(account[0], row) for row in rows]

    return sorted(transactions, key=lambda t: t.date, reverse=True)


# Send a pushover notification if a new transaction is found.
# force - Send a notification even if no new transactions are found.
def push_notifications(transactions, app_token, user_key,
        transaction_log='~/.lloyds_transaction_log', force=False):
    # Make sure transaction log isn't empty.
    assert len(transactions) > 0

    # Get hash of last transaction.
    hash_log = open(os.path.expanduser(transaction_log), 'r+')
    last_hash = hash_log.read()

    for transaction in transactions:
        if transaction.hash == last_hash and force is False:
            break
        elif transaction.hash == last_hash and force is True:
            message = "Account balance: £%s" % transaction.balance
        else:
            force = False # New transaction found. Don't force.
            message = "%s %s %s\nAccount balance: £%s" % (transaction.amount,
                    transaction.get_type_explanation(), transaction.description,
                    transaction.balance)

        # Send notification.
        conn = httplib.HTTPSConnection("api.pushover.net:443")
        conn.request("POST", "/1/messages.json", urlencode({
            "token": app_token,
            "user": user_key,
            "title": transaction.account_name,
            "message": message
            }), { "Content-type": "application/x-www-form-urlencoded" })
        conn.getresponse()

        # Send only one notification if forced.
        if transaction.hash == last_hash and force is True:
            break

    # Write last transaction hash to file and close it.
    hash_log.seek(0)
    hash_log.write(transactions[0].hash)
    hash_log.truncate()
    hash_log.close()


def main():
    # Parse command-line options.
    args = parse_commandline()
    # Load configuration file.
    config = parse_configuration(args.config)
    # Get transaction logs.
    transactions = get_account_information(config['userid'], config['password'],
            config['memorable_information'])
    # Send notifications.
    push_notifications(transactions, config['pushover']['token'], config['pushover']['user'],
            transaction_log=args.log, force=args.force)


if __name__ == '__main__':
    main()
