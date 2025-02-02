# -*- coding: utf8 -*-
import json

import boto3
import mock
import os
import unittest

try:
    from mock import patch
except ImportError:
    from unittest.mock import patch

from zappa.asynchronous import AsyncException, LambdaAsyncResponse, SnsAsyncResponse, SqsAsyncResponse
from zappa.asynchronous import import_and_get_task, get_func_task_path


class TestZappa(unittest.TestCase):
    def setUp(self):
        self.sleep_patch = mock.patch('time.sleep', return_value=None)
        # Tests expect us-east-1.
        # If the user has set a different region in env variables, we set it aside for now and use us-east-1
        self.users_current_region_name = os.environ.get('AWS_DEFAULT_REGION', None)
        os.environ['AWS_DEFAULT_REGION'] = 'us-east-1'
        if not os.environ.get('PLACEBO_MODE') == 'record':
            self.sleep_patch.start()

    def tearDown(self):
        if not os.environ.get('PLACEBO_MODE') == 'record':
            self.sleep_patch.stop()
        del os.environ['AWS_DEFAULT_REGION']
        if self.users_current_region_name is not None:
            # Give the user their AWS region back, we're done testing with us-east-1.
            os.environ['AWS_DEFAULT_REGION'] = self.users_current_region_name

    ##
    # Sanity Tests
    ##

    def test_test(self):
        self.assertTrue(True)
        self.assertFalse(False)

    def test_nofails_classes(self):

        boto_session = boto3.Session(region_name=os.environ['AWS_DEFAULT_REGION'])

        a = AsyncException()
        l = LambdaAsyncResponse(boto_session=boto_session)
        # s = SnsAsyncResponse()
        s = SnsAsyncResponse(arn="arn:abc:def", boto_session=boto_session)
        q = SqsAsyncResponse(queue_url="https://example.com", boto_session=boto_session)

    def test_nofails_funcs(self):
        funk = import_and_get_task("tests.test_app.async_me")
        get_func_task_path(funk)
        self.assertEqual(funk.__name__, 'async_me')

    ##
    # Functional tests
    ##
    def test_sync_call(self):
        funk = import_and_get_task("tests.test_app.async_me")
        self.assertEqual(funk.sync('123'), "run async when on lambda 123")

    def test_async_call_with_defaults(self):
        """Change a task's asynchronousity at runtime."""
        # Import the task first to make sure it is decorated whilst the
        # environment is unpatched.
        async_me = import_and_get_task("tests.test_app.async_me")
        lambda_async_mock = mock.Mock()
        lambda_async_mock.return_value.send.return_value = "Running async!"
        with mock.patch.dict('zappa.asynchronous.ASYNC_CLASSES',
                             {'lambda': lambda_async_mock}):
            # First check that it still runs synchronously by default
            self.assertEqual(async_me("123"),
                             "run async when on lambda 123")

            # Now patch the environment to make it look like we are running on
            # AWS Lambda
            options = {
                'AWS_LAMBDA_FUNCTION_NAME': 'MyLambda',
                'AWS_REGION': 'us-east-1'
            }
            with mock.patch.dict(os.environ, options):
                self.assertEqual(async_me("qux"),
                                 "Running async!")

        # And check the dispatching class got called correctly
        lambda_async_mock.assert_called_once_with(aws_region='us-east-1',
                                             capture_response=False,
                                             delay_seconds=0,
                                             lambda_function_name="MyLambda",
                                             large_messages_payload_bucket=None)
        lambda_async_mock.return_value.send.assert_called_with(
            get_func_task_path(async_me), ("qux",), {})


    def test_async_sqs_call(self):
        """
        Call a task with sqs async service.
        """

        async_sqs_me = import_and_get_task("tests.test_app.async_sqs_me")
        sqs_client_mock = mock.Mock()
        sqs_client_mock.get_queue_url = mock.MagicMock(
            return_value={'QueueUrl': 'https://us-east-1.queue.amazonaws.com/1'}
        )
        sqs_client_mock.send_message = mock.MagicMock(
            return_value={
                'MD5OfMessageBody': 'string',
                'MD5OfMessageAttributes': 'string',
                'MessageId': '1234',
                'SequenceNumber': '1'
            }
        )
        with mock.patch('zappa.asynchronous.SQS_CLIENT', sqs_client_mock, create=True):
            # First check that it still runs synchronously by default
            self.assertEqual(async_sqs_me("123"),
                             "run async with sqs service when on lambda 123")

            # Now patch the environment to make it look like we are running on
            # AWS Lambda
            options = {
                'AWS_LAMBDA_FUNCTION_NAME': 'MyLambda',
                'AWS_REGION': 'us-east-1'
            }
            with mock.patch.dict(os.environ, options):
                async_sqs_me("qux")

        # And check the sqs client got invoked correctly
        sqs_client_mock.get_queue_url.assert_called_once_with(QueueName='MyLambda-zappa-async')
        sqs_client_mock.send_message.assert_called_once_with(
            QueueUrl='https://us-east-1.queue.amazonaws.com/1',
            MessageBody=json.dumps({
                "task_path": get_func_task_path(async_sqs_me),
                "capture_response": False,
                "response_id": None,
                "args": ["qux"],
                "kwargs": {},
                "zappaAsyncCommand": "zappa.asynchronous.route_sqs_task"
            }),
            DelaySeconds=0
        )
